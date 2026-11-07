#!/usr/bin/env python3
"""
Construye el dataset de modelado para La Boca (CABA).
Base: linea de tiempo horaria continua de Open-Meteo (caba_laboca) 2022-08..2026-09
  + target REAL de la estacion APrA La Boca (PM10, NO2, CO)   [historico + 2025 + 2026]
  + focos NASA FIRMS agregados por dia.
Salida: data/processed/dataset_modelo_laboca.csv
"""
import csv, os, datetime as dt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(BASE, "data", "processed")
RAWC = os.path.join(BASE, "data", "raw", "caba_oficial")
MES = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}


def to_float(v):
    if v is None:
        return None
    v = v.strip()
    if v in ("", "s/d", "S/D"):
        return None
    if v.startswith("<"):
        try: return float(v[1:].replace(",", ".")) / 2
        except ValueError: return None
    try: return float(v.replace(",", "."))
    except ValueError: return None


def ts(date_iso, hour):
    return f"{date_iso}T{int(hour):02d}:00"


# ---- cargar target real La Boca (3 archivos, 2 formatos) ----
real = {}   # ts -> {pm10_real, no2_real, co_real}

def add_real(fecha_iso, hora, pm10):
    try: h = int(hora)
    except (TypeError, ValueError): return
    if h == 24: h = 0
    if not (0 <= h <= 23): return
    key = ts(fecha_iso, h)
    d = real.setdefault(key, {"pm10": []})
    for name, val in (("pm10", pm10),):
        f = to_float(val)
        if f is not None: d[name].append(f)

# historico (FECHA = 16NOV2010:00:00:00, cols MAYUS)
with open(os.path.join(RAWC, "historico_desde2009.csv"), encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        s = (row.get("FECHA") or "").split(":")[0]
        try: d = dt.date(int(s[5:9]), MES[s[2:5]], int(s[0:2]))
        except Exception: continue
        add_real(d.isoformat(), row.get("HORA"), row.get("PM10_LA_BOCA"))

# anios 2025/2026 (fecha = 2026-01-01, cols minus)
for fn in ("anio2025.csv", "anio2026.csv"):
    p = os.path.join(RAWC, fn)
    if not os.path.exists(p): continue
    with open(p, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            fecha = (row.get("fecha") or "").strip()
            if not fecha: continue
            add_real(fecha, row.get("hora"), row.get("pm10_la_boca"))

# promediar duplicados
for k, d in real.items():
    for name in ("pm10",):
        d[name] = round(sum(d[name])/len(d[name]), 2) if d[name] else None

# ---- focos FIRMS por dia ----
firms = {}
with open(os.path.join(PROC, "firms_daily.csv")) as f:
    for r in csv.DictReader(f):
        firms[r["fecha"]] = r

# ---- base Open-Meteo La Boca ----
meteo_cols = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation",
              "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "surface_pressure", "cloud_cover"]
cams_cols = ["pm10"]

out_cols = (["time", "pm10_real"] + meteo_cols +
            ["cams_" + c for c in cams_cols] +
            ["fire_n_focos", "fire_n_focos_150km", "fire_frp_sum", "fire_frp_max"])

rows = []
with open(os.path.join(PROC, "dataset_caba_laboca.csv")) as f:
    for r in csv.DictReader(f):
        t = r["time"]; day = t[:10]
        rr = real.get(t, {})
        fr = firms.get(day, {})
        row = {"time": t, "pm10_real": rr.get("pm10")}
        for c in meteo_cols: row[c] = r.get(c)
        for c in cams_cols: row["cams_" + c] = r.get(c)
        row["fire_n_focos"] = fr.get("n_focos", 0)
        row["fire_n_focos_150km"] = fr.get("n_focos_150km", 0)
        row["fire_frp_sum"] = fr.get("frp_sum", 0)
        row["fire_frp_max"] = fr.get("frp_max", 0)
        rows.append(row)

out = os.path.join(PROC, "dataset_modelo_laboca.csv")
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=out_cols)
    w.writeheader(); w.writerows(rows)

n = len(rows)
with_t = sum(1 for r in rows if r["pm10_real"] not in (None, ""))
print(f"OK {out}")
print(f"filas: {n} | columnas: {len(out_cols)}")
print(f"con target PM10 real: {with_t} ({100*with_t/n:.0f}%)")
print(f"rango: {rows[0]['time']} .. {rows[-1]['time']}")
