#!/usr/bin/env python3
"""
Config y utilidades compartidas de las estaciones REALES de CABA (APrA) con
medición propia y cobertura Open-Meteo en ventana: La Boca, Centenario, Córdoba.
(Palermo se excluye: sin datos recientes. San Isidro/Moreno/La Plata NO tienen
sensor: no se modelan acá — solo aparecen como estimación satelital en el mapa.)
"""
import csv, os, math, json, time, datetime as dt, urllib.request, urllib.parse
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAWC = os.path.join(BASE, "data", "raw", "caba_oficial")
RAWE = os.path.join(BASE, "data", "raw", "estaciones_holdout")
PROC = os.path.join(BASE, "data", "processed")
MES = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}

# name -> label, lat, lon, columnas reales por contaminante (histórico MAYÚS, anio minús)
STATIONS = {
    "laboca": {"label": "La Boca", "lat": -34.6252584813295, "lon": -58.3663735070165,
        "cols": {"pm10": ("PM10_LA_BOCA", "pm10_la_boca")}},
    "centenario": {"label": "Centenario", "lat": -34.6066080998154, "lon": -58.4320717652753,
        "cols": {"pm10": ("PM10_CENTENARIO", "pm10_centenario")}},
    "cordoba": {"label": "Córdoba", "lat": -34.5995643433432, "lon": -58.3915528934620,
        "cols": {"pm10": ("PM10_CORDOBA", "pm10_cordoba")}},
}
POLS = ("pm10",)


def to_float(v):
    """Igual criterio que build_dataset_modelo: '<LD' -> mitad, 's/d' -> None, coma decimal."""
    if v is None: return None
    v = v.strip()
    if v in ("", "s/d", "S/D"): return None
    if v.startswith("<"):
        try: return float(v[1:].replace(",", ".")) / 2
        except ValueError: return None
    try: return float(v.replace(",", "."))
    except ValueError: return None


def load_real():
    """real[station][pol][fecha_iso] = promedio diario medido."""
    acc = {s: {p: {} for p in POLS} for s in STATIONS}
    # histórico (FECHA = 16NOV2010:00:00:00, columnas MAYÚS)
    with open(os.path.join(RAWC, "historico_desde2009.csv"), encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            s = (row.get("FECHA") or "").split(":")[0]
            try: d = dt.date(int(s[5:9]), MES[s[2:5]], int(s[0:2])).isoformat()
            except Exception: continue
            for st, meta in STATIONS.items():
                for p in POLS:
                    val = to_float(row.get(meta["cols"][p][0]))
                    if val is not None: acc[st][p].setdefault(d, []).append(val)
    # años 2025/2026 (fecha = 2026-01-01, columnas minús)
    for fn in ("anio2025.csv", "anio2026.csv"):
        path = os.path.join(RAWC, fn)
        if not os.path.exists(path): continue
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                d = (row.get("fecha") or "").strip()
                if not d: continue
                for st, meta in STATIONS.items():
                    for p in POLS:
                        val = to_float(row.get(meta["cols"][p][1]))
                        if val is not None: acc[st][p].setdefault(d, []).append(val)
    return {st: {p: {d: float(np.mean(vs)) for d, vs in dd.items()} for p, dd in pols.items()}
            for st, pols in acc.items()}


START = "2022-08-01"
END = os.environ.get("AIRE_END") or dt.date.today().isoformat()   # corte dinámico (hoy, o AIRE_END)
TZ = "America/Argentina/Buenos_Aires"
CACHE_MAX_DIAS = 3   # re-descarga si el cache quedó viejo (para que el calendario avance)

def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "AireAbierto/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)

def get_openmeteo(name):
    """Lee la caché de features Open-Meteo (meteo + CAMS pm10/no2/co); la descarga si falta,
    si no tiene CO, o si quedó vieja (para que el pronóstico avance con los días)."""
    os.makedirs(RAWE, exist_ok=True)
    pj = os.path.join(RAWE, f"{name}.json")
    if os.path.exists(pj):
        edad_dias = (dt.datetime.now() - dt.datetime.fromtimestamp(os.path.getmtime(pj))).days
        d = json.load(open(pj))
        if "pm10" in d.get("aq", {}) and edad_dias <= CACHE_MAX_DIAS:
            return d
    lat, lon = STATIONS[name]["lat"], STATIONS[name]["lon"]
    aq = _fetch("https://air-quality-api.open-meteo.com/v1/air-quality?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "hourly": "pm10",
        "start_date": START, "end_date": END, "timezone": TZ})); time.sleep(1)
    wx = _fetch("https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_direction_10m,surface_pressure,cloud_cover",
        "start_date": START, "end_date": END, "timezone": TZ})); time.sleep(1)
    obj = {"aq": aq["hourly"], "wx": wx["hourly"]}
    json.dump(obj, open(pj, "w"))
    return obj


def daily_features(om):
    """Agrega las series horarias Open-Meteo a diario: meteo + CAMS PM10 (cpm10) + viento vectorial."""
    aq, wx = om["aq"], om["wx"]
    fl = to_float if False else (lambda v: (float(v) if v is not None else None))
    days = {}
    for i, t in enumerate(wx["time"]):
        d = t[:10]
        a = days.setdefault(d, {k: [] for k in ["temp","rh","prec","wind","pres","cloud","cpm10","u","v"]})
        for key, arr in [("temp","temperature_2m"),("rh","relative_humidity_2m"),("prec","precipitation"),
                         ("wind","wind_speed_10m"),("pres","surface_pressure"),("cloud","cloud_cover")]:
            v = fl(wx[arr][i])
            if v is not None: a[key].append(v)
        spd, dr = fl(wx["wind_speed_10m"][i]), fl(wx["wind_direction_10m"][i])
        if spd is not None and dr is not None:
            r = math.radians(dr); a["u"].append(spd*math.sin(r)); a["v"].append(spd*math.cos(r))
        for ck, src in [("cpm10","pm10")]:
            v = fl(aq.get(src, [None]*len(aq["time"]))[i])
            if v is not None: a[ck].append(v)
    out = {}
    for d, a in days.items():
        if not a["temp"]: continue
        mu, mv = (np.mean(a["u"]) if a["u"] else 0.0), (np.mean(a["v"]) if a["v"] else 0.0)
        norm = math.hypot(mu, mv)
        g = lambda k: (np.mean(a[k]) if a[k] else np.nan)
        out[d] = {"temp": np.mean(a["temp"]), "rh": np.mean(a["rh"]),
                  "prec": sum(a["prec"]) if a["prec"] else 0.0, "wind": np.mean(a["wind"]) if a["wind"] else 0.0,
                  "pres": np.mean(a["pres"]), "cloud": np.mean(a["cloud"]),
                  "cpm10": g("cpm10"),
                  "wdir_sin": (mu/norm if norm else 0.0), "wdir_cos": (mv/norm if norm else 0.0)}
    return out


def live_daily(name, past_days=16, forecast_days=3):
    """Features diarios RECIENTES + PRONÓSTICO (hoy y próximos días) para el modelo operativo:
    meteo de la API forecast (no ERA5) + CAMS near-real-time. Para predecir mañana en vivo."""
    lat, lon = STATIONS[name]["lat"], STATIONS[name]["lon"]
    aq = _fetch("https://air-quality-api.open-meteo.com/v1/air-quality?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "hourly": "pm10",
        "past_days": past_days, "forecast_days": forecast_days, "timezone": TZ})); time.sleep(1)
    wx = _fetch("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_direction_10m,surface_pressure,cloud_cover",
        "past_days": past_days, "forecast_days": forecast_days, "timezone": TZ})); time.sleep(1)
    # alinear AQ al eje temporal de WX (por si difieren)
    aqh, wxh = aq["hourly"], wx["hourly"]
    idx = {t: i for i, t in enumerate(aqh["time"])}
    aligned = {"time": wxh["time"]}
    for k in ("pm10",):
        aligned[k] = [aqh[k][idx[t]] if t in idx else None for t in wxh["time"]]
    return daily_features({"aq": aligned, "wx": wxh})


def firms_daily():
    """{fecha: {n_focos_150km, frp_sum, ...}} city-wide."""
    firms = {}
    p = os.path.join(PROC, "firms_daily.csv")
    if os.path.exists(p):
        with open(p) as f:
            for r in csv.DictReader(f): firms[r["fecha"]] = r
    return firms
