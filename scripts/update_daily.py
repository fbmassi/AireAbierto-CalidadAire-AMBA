#!/usr/bin/env python3
"""
Actualización DIARIA de AireAbierto (lo que corre el botón 'actualizar_datos.command').
Refresca los datos hasta HOY, reconstruye el dataset, reentrena y regenera los
datos del panel. FIRMS se actualiza de forma incremental (últimos días) si hay MAP_KEY.
"""
import os, sys, subprocess, csv, math, json, time, datetime as dt, urllib.request
import _env; _env.load_env()   # credenciales/keys desde .env (FIRMS, SMTP para el paso de mail)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(BASE, "data", "processed")
FDIR = os.path.join(BASE, "data", "raw", "firms")
PY = os.path.join(BASE, ".venv", "bin", "python")
TODAY = dt.date.today()

def run(cmd, env=None):
    subprocess.run(cmd, check=True, cwd=BASE, env=env)

def firms_incremental(days=12):
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    path = os.path.join(PROC, "firms_daily.csv")
    if not key:
        print("   (FIRMS: sin MAP_KEY → se mantiene lo existente)"); return
    if not os.path.exists(path):
        print("   (FIRMS: no hay base previa → saltado)"); return
    BBOX = "-61,-35,-57.5,-32"; CABA = (-34.6037, -58.3816)
    def hav(lat, lon):
        R=6371.0; p1,p2=math.radians(lat),math.radians(CABA[0])
        dphi=math.radians(CABA[0]-lat); dl=math.radians(CABA[1]-lon)
        a=math.sin(dphi/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
        return R*2*math.asin(math.sqrt(a))
    start = TODAY - dt.timedelta(days=days)
    rows = {}
    d = start
    while d <= TODAY:
        span = min(5, (TODAY - d).days + 1)
        for src in ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_SNPP_SP", "VIIRS_NOAA20_SP"):
            url = (f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/"
                   f"{src}/{BBOX}/{span}/{d.isoformat()}")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "AireAbierto/1.0"})
                txt = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")
            except Exception as e:
                print(f"   aviso FIRMS {src} {d}: {e}"); continue
            lines = txt.strip().splitlines()
            if not lines or "latitude" not in lines[0].lower(): continue
            for rec in csv.DictReader(lines):
                day = rec.get("acq_date")
                if not day: continue
                try: frp = float(rec.get("frp") or 0)
                except ValueError: frp = 0.0
                try: dist = hav(float(rec["latitude"]), float(rec["longitude"]))
                except Exception: dist = 9999
                k = (day, rec.get("acq_time"), rec.get("latitude"), rec.get("longitude"), rec.get("satellite"))
                a = rows.setdefault(day, {"fecha": day, "n_focos": 0, "n_focos_150km": 0,
                                          "frp_sum": 0.0, "frp_max": 0.0, "_seen": set()})
                if k in a["_seen"]: continue
                a["_seen"].add(k)
                a["n_focos"] += 1; a["frp_sum"] += frp; a["frp_max"] = max(a["frp_max"], frp)
                if dist <= 150: a["n_focos_150km"] += 1
            time.sleep(0.25)
        d += dt.timedelta(days=span)
    # upsert
    existing = {}
    with open(path) as f:
        for r in csv.DictReader(f): existing[r["fecha"]] = r
    for day, a in rows.items():
        existing[day] = {"fecha": day, "n_focos": a["n_focos"], "n_focos_150km": a["n_focos_150km"],
                         "frp_sum": round(a["frp_sum"], 1), "frp_max": round(a["frp_max"], 1)}
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["fecha","n_focos","n_focos_150km","frp_sum","frp_max"])
        w.writeheader()
        for day in sorted(existing): w.writerow(existing[day])
    print(f"   FIRMS: {len(rows)} días recientes actualizados.")

def main():
    env = os.environ.copy(); env["AIRE_END"] = TODAY.isoformat()
    env["AIRE_AQ_END"] = (TODAY + dt.timedelta(days=2)).isoformat()   # incluye pronóstico (hoy + 2 días)
    print(f"== Actualización AireAbierto · corte {TODAY} ==")
    print("1/7 · Descargando aire + meteo (Open-Meteo hasta hoy)…")
    try: run([PY, "scripts/download_data.py"], env=env)
    except subprocess.CalledProcessError: print("   (Open-Meteo no respondió → se mantiene lo existente)")
    print("2/7 · Descargando estaciones oficiales de CABA…")
    try: run(["bash", "scripts/download_caba_oficial.sh"])
    except subprocess.CalledProcessError: print("   (CABA no respondió → se mantiene lo existente)")
    print("3/7 · Actualizando focos de fuego (FIRMS)…")
    try: firms_incremental()
    except Exception as e: print(f"   (FIRMS falló → se mantiene lo existente: {e})")
    print("4/7 · Reconstruyendo el dataset de modelado…");             run([PY, "scripts/build_dataset_modelo.py"])
    print("5/7 · Recalculando el Índice de Calidad del Aire…")
    run([PY, "scripts/ica.py"])
    print("6/7 · Actualizando el panel (mapa + alertas)…")
    run([PY, "scripts/patch_panel.py"])
    print("   Reentrenando pronóstico por estación (La Boca, Centenario, Córdoba)…")
    try: run([PY, "scripts/export_pollutants.py"])
    except subprocess.CalledProcessError: print("   (pronóstico: se mantiene el anterior)")
    print("7/7 · Revisando alerta por email…")
    try: run([PY, "scripts/alerta_mail.py"])
    except subprocess.CalledProcessError as e: print(f"   (alerta mail: {e})")
    # pronóstico resultante
    try:
        js = open(os.path.join(BASE, "dashboard", "pollutants_data.js")).read()
        pol = json.loads(js[js.index("{"):js.index("};")+1])
        nx = (pol.get("laboca", {}).get("pm10", {}) or {}).get("next", {}) or {}
        print(f"\n✓ LISTO. Pronóstico del modelo (La Boca): PM10 {nx.get('val')} µg/m³ para {nx.get('fecha')}")
        print("  Para verlo en el panel publicado, pedile a tu asistente que vuelva a publicar el dashboard.")
    except Exception:
        print("\n✓ LISTO. Datos del panel regenerados.")

if __name__ == "__main__":
    main()
