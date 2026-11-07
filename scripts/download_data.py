#!/usr/bin/env python3
"""
AireAbierto - Descarga de datos de calidad del aire + meteorologia (AMBA).
Fuentes publicas, abiertas y GRATUITAS (sin API key, sin pago):
  - Open-Meteo Air Quality API (modelo CAMS)  -> contaminantes
  - Open-Meteo Historical Weather API (ERA5)  -> meteorologia
Genera:
  data/raw/<loc>_air_quality.json / .csv
  data/raw/<loc>_weather.json / .csv
  data/processed/dataset_<loc>.csv        (AQ + WX unidos por hora)
  data/processed/dataset_amba_full.csv    (todos los puntos concatenados)
"""
import urllib.request, urllib.parse, json, csv, os, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "data", "raw")
PROC = os.path.join(BASE, "data", "processed")
os.makedirs(RAW, exist_ok=True)
os.makedirs(PROC, exist_ok=True)

START = "2022-08-01"
END = os.environ.get("AIRE_END", "2026-09-30")   # corte meteo/archivo (el updater lo pone en hoy)
AQ_END = os.environ.get("AIRE_AQ_END", END)       # corte aire: admite PRONÓSTICO (hoy + algunos días)
TZ = "America/Argentina/Buenos_Aires"

# Puntos representativos del Area Metropolitana de Buenos Aires
LOCATIONS = [
    ("caba_centro",   -34.6037, -58.3816),
    ("caba_laboca",   -34.6345, -58.3631),
    ("sanisidro_n",   -34.4708, -58.5126),
    ("laplata",       -34.9205, -57.9536),
    ("moreno_oeste",  -34.6534, -58.7920),
]

AQ_VARS = ["pm2_5", "pm10", "carbon_monoxide", "nitrogen_dioxide",
           "sulphur_dioxide", "ozone", "aerosol_optical_depth", "dust", "uv_index"]
WX_VARS = ["temperature_2m", "relative_humidity_2m", "dew_point_2m",
           "precipitation", "wind_speed_10m", "wind_direction_10m",
           "wind_gusts_10m", "surface_pressure", "cloud_cover"]


def fetch(url):
    last = None
    for intento in range(4):                       # reintentos ante timeouts/cortes de red
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AireAbierto/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:
            last = e
            if intento < 3:
                print(f"   (reintento {intento+1}/3 tras {type(e).__name__})"); time.sleep(4 * (intento + 1))
    raise last


def aq_url(lat, lon):
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "hourly": ",".join(AQ_VARS),
        "start_date": START, "end_date": AQ_END, "timezone": TZ})
    return "https://air-quality-api.open-meteo.com/v1/air-quality?" + q


def wx_url(lat, lon):
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "hourly": ",".join(WX_VARS),
        "start_date": START, "end_date": END, "timezone": TZ})
    return "https://archive-api.open-meteo.com/v1/archive?" + q


def save_json(obj, path):
    with open(path, "w") as f:
        json.dump(obj, f)


def hourly_to_rows(h, variables):
    """dict de listas -> lista de dicts por hora."""
    times = h["time"]
    rows = []
    for i, t in enumerate(times):
        row = {"time": t}
        for v in variables:
            row[v] = h.get(v, [None] * len(times))[i]
        rows.append(row)
    return rows


def write_csv(rows, cols, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


full_rows = []
full_cols = ["location", "latitude", "longitude", "time"] + AQ_VARS + WX_VARS

for name, lat, lon in LOCATIONS:
    print(f"== {name} ({lat},{lon}) ==")

    aq = fetch(aq_url(lat, lon)); time.sleep(1)
    save_json(aq, os.path.join(RAW, f"{name}_air_quality.json"))
    aq_rows = hourly_to_rows(aq["hourly"], AQ_VARS)
    write_csv(aq_rows, ["time"] + AQ_VARS, os.path.join(RAW, f"{name}_air_quality.csv"))
    print(f"   AQ filas: {len(aq_rows)}")

    wx = fetch(wx_url(lat, lon)); time.sleep(1)
    save_json(wx, os.path.join(RAW, f"{name}_weather.json"))
    wx_rows = hourly_to_rows(wx["hourly"], WX_VARS)
    write_csv(wx_rows, ["time"] + WX_VARS, os.path.join(RAW, f"{name}_weather.csv"))
    print(f"   WX filas: {len(wx_rows)}")

    # merge por time
    wx_by_time = {r["time"]: r for r in wx_rows}
    merged = []
    for r in aq_rows:
        m = {"location": name, "latitude": lat, "longitude": lon, "time": r["time"]}
        for v in AQ_VARS:
            m[v] = r.get(v)
        w = wx_by_time.get(r["time"], {})
        for v in WX_VARS:
            m[v] = w.get(v)
        merged.append(m)
    write_csv(merged, full_cols, os.path.join(PROC, f"dataset_{name}.csv"))
    full_rows.extend(merged)
    print(f"   merged filas: {len(merged)}")

write_csv(full_rows, full_cols, os.path.join(PROC, "dataset_amba_full.csv"))
print(f"\nTOTAL dataset_amba_full.csv: {len(full_rows)} filas, {len(full_cols)} columnas")
