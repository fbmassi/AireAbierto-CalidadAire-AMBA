#!/usr/bin/env python3
"""
AireAbierto - Descarga de focos de quema (NASA FIRMS) para Delta del Parana + AMBA.
Fuente: NASA FIRMS Area API (gratuita, requiere MAP_KEY por email, SIN pago).
  Conseguir key: https://firms.modaps.eosdis.nasa.gov/api/map_key/

Uso:
  FIRMS_MAP_KEY=xxxxxxxx python3 scripts/download_firms.py
  (o)  python3 scripts/download_firms.py <MAP_KEY>

Genera:
  data/raw/firms/firms_amba_delta_raw.csv   (deteccion por deteccion)
  data/processed/firms_daily.csv            (agregado diario, listo para unir por fecha)
"""
import urllib.request, os, sys, csv, time, math, datetime as dt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "data", "raw", "firms")
PROC = os.path.join(BASE, "data", "processed")
os.makedirs(RAW, exist_ok=True); os.makedirs(PROC, exist_ok=True)

MAP_KEY = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FIRMS_MAP_KEY", "")).strip()
if not MAP_KEY:
    sys.exit("FALTA MAP_KEY. Conseguila gratis en "
             "https://firms.modaps.eosdis.nasa.gov/api/map_key/ y pasala como "
             "FIRMS_MAP_KEY=... o como primer argumento.")

START = dt.date(2022, 8, 1)
END = dt.date(2026, 9, 30)
BBOX = "-61,-35,-57.5,-32"          # oeste,sur,este,norte (Delta + AMBA)
CABA = (-34.6037, -58.3816)         # referencia para distancias
ARCHIVE_SOURCES = ["VIIRS_SNPP_SP", "VIIRS_NOAA20_SP"]
NRT_SOURCES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"]
STEP = 5                            # max permitido por request


def haversine(lat, lon, lat0=CABA[0], lon0=CABA[1]):
    R = 6371.0
    p1, p2 = math.radians(lat), math.radians(lat0)
    dphi = math.radians(lat0 - lat); dl = math.radians(lon0 - lon)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def fetch(source, start_date, days):
    url = (f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/"
           f"{source}/{BBOX}/{days}/{start_date.isoformat()}")
    req = urllib.request.Request(url, headers={"User-Agent": "AireAbierto/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", "replace")


def parse(text):
    lines = text.strip().splitlines()
    if not lines or "latitude" not in lines[0].lower():
        if lines and "Invalid" in lines[0]:
            sys.exit(f"MAP_KEY rechazada por la API: {lines[0]}")
        return []
    return list(csv.DictReader(lines))


today = dt.date.today()
seen = set()
rows = []
d = START
while d <= END:
    days = min(STEP, (END - d).days + 1)
    sources = list(ARCHIVE_SOURCES)
    if (today - d).days < 70:       # para fechas recientes, agregar NRT
        sources += NRT_SOURCES
    for src in sources:
        try:
            for rec in parse(fetch(src, d, days)):
                key = (rec.get("latitude"), rec.get("longitude"),
                       rec.get("acq_date"), rec.get("acq_time"), rec.get("satellite"))
                if key in seen:
                    continue
                seen.add(key)
                try:
                    rec["dist_caba_km"] = round(
                        haversine(float(rec["latitude"]), float(rec["longitude"])), 1)
                except Exception:
                    rec["dist_caba_km"] = ""
                rows.append(rec)
            time.sleep(0.3)
        except Exception as e:
            print(f"  aviso {src} {d}: {e}")
    if d.day == 1 or days < STEP:
        print(f"  ... {d}  (acum {len(rows)} focos)")
    d += dt.timedelta(days=days)

# --- guardar crudo ---
fields = ["latitude", "longitude", "acq_date", "acq_time", "satellite",
          "instrument", "confidence", "frp", "bright_ti4", "bright_ti5",
          "daynight", "dist_caba_km"]
raw_path = os.path.join(RAW, "firms_amba_delta_raw.csv")
with open(raw_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
print(f"\nCrudo: {raw_path}  ({len(rows)} detecciones)")

# --- agregado diario (para unir al dataset por fecha) ---
daily = {}
for r in rows:
    day = r.get("acq_date")
    if not day:
        continue
    try:
        frp = float(r.get("frp") or 0)
    except ValueError:
        frp = 0.0
    try:
        dist = float(r.get("dist_caba_km") or 9999)
    except ValueError:
        dist = 9999
    a = daily.setdefault(day, {"fecha": day, "n_focos": 0, "frp_sum": 0.0,
                               "frp_max": 0.0, "n_focos_150km": 0})
    a["n_focos"] += 1
    a["frp_sum"] += frp
    a["frp_max"] = max(a["frp_max"], frp)
    if dist <= 150:
        a["n_focos_150km"] += 1

daily_path = os.path.join(PROC, "firms_daily.csv")
with open(daily_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["fecha", "n_focos", "n_focos_150km",
                                      "frp_sum", "frp_max"])
    w.writeheader()
    for day in sorted(daily):
        row = daily[day]
        row["frp_sum"] = round(row["frp_sum"], 1)
        row["frp_max"] = round(row["frp_max"], 1)
        w.writerow(row)
print(f"Diario: {daily_path}  ({len(daily)} dias con focos)")
