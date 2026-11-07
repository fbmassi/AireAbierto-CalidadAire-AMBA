#!/usr/bin/env python3
"""
Refresco RÁPIDO del panel SIN reentrenar el modelo.
Actualiza en dashboard/data.js lo que depende solo de los DATOS (no del modelo):
  - ICA diario (todos los días)        -> panel ICA + alertas por fecha
  - map_series (todos los días)        -> mapa hiperlocal por fecha
  - KPIs de hoy y fecha de generación
Deja intactos forecast / importancia / holdout (salen del modelo, se reentrena aparte).
"""
import csv, os, json, statistics as st, datetime as dt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(BASE, "data", "processed")
DASH = os.path.join(BASE, "dashboard")

# --- ICA diario (desde el PM10 real de La Boca) ---
ica_dates, ica_pm, ica_val = [], [], []
with open(os.path.join(PROC, "ica_diario_laboca.csv")) as f:
    for r in csv.DictReader(f):
        ica_dates.append(r["fecha"]); ica_pm.append(round(float(r["pm10"]),1)); ica_val.append(int(r["ica"]))
BP = [("Buena","#16a34a",0,50),("Aceptable","#eab308",51,100),("Dañina (sensibles)","#f97316",101,150),
      ("Dañina","#dc2626",151,200),("Muy dañina","#7c3aed",201,300)]
dist = []
for cat,col,lo,hi in BP:
    c = sum(1 for v in ica_val if lo<=v<=hi)
    if c: dist.append({"cat":cat,"color":col,"pct":round(100*c/len(ica_val),1),"dias":c})

# --- map_series (5 puntos, todos los días, 3 contaminantes CAMS) ---
PUNTOS = [("CABA centro","dataset_caba_centro.csv"),("La Boca","dataset_caba_laboca.csv"),
          ("San Isidro","dataset_sanisidro_n.csv"),("La Plata","dataset_laplata.csv"),("Moreno","dataset_moreno_oeste.csv")]
COLS = {"pm10":"pm10"}
_pp = {pol: {} for pol in COLS}
for nombre, fn in PUNTOS:
    acc = {pol: {} for pol in COLS}
    with open(os.path.join(PROC, fn)) as f:
        for r in csv.DictReader(f):
            day = r["time"][:10]
            for pol, col in COLS.items():
                v = r.get(col, "")
                if v not in ("", "None", None):
                    a = acc[pol].setdefault(day, [0.0, 0]); a[0] += float(v); a[1] += 1
    for pol in COLS:
        _pp[pol][nombre] = {day: round(x[0]/x[1], 1) for day, x in acc[pol].items()}
mdates = sorted(set().union(*[set(_pp["pm10"][n]) for n, _ in PUNTOS]))
map_series = {"dates": mdates}
for pol in COLS:
    map_series[pol] = [[_pp[pol][n].get(d) for n, _ in PUNTOS] for d in mdates]

# --- parchear data.js sin tocar lo del modelo ---
p = os.path.join(DASH, "data.js")
s = open(p).read()
DATA = json.loads(s[s.index("{"):s.rindex("}")+1])
DATA["ica"] = {"dates": ica_dates, "pm10": ica_pm, "ica": ica_val, "dist": dist}
DATA["map_series"] = map_series
# serie diaria de contaminantes REALES (medidos) + focos, para el gráfico por rango de fechas
_firms = {}
_fp = os.path.join(PROC, "firms_daily.csv")
if os.path.exists(_fp):
    with open(_fp) as f:
        for r in csv.DictReader(f):
            _firms[r["fecha"]] = int(r.get("n_focos_150km", 0) or 0)
_rd = {}
with open(os.path.join(PROC, "dataset_modelo_laboca.csv")) as f:
    for r in csv.DictReader(f):
        d = r["time"][:10]; a = _rd.setdefault(d, {"pm10": []})
        for k, col in (("pm10", "pm10_real"),):
            v = r.get(col, "")
            if v not in ("", "None", None):
                try: a[k].append(float(v))
                except ValueError: pass
_fd = sorted(_rd)
def _dm(d, k): xs = _rd[d][k]; return round(sum(xs)/len(xs), 1) if xs else None
DATA["fire_series"] = {"dates": _fd, "pm10": [_dm(d, "pm10") for d in _fd], "focos": [_firms.get(d, 0) for d in _fd]}
# KPI: días con aire malo (PM10 real > 50 µg/m³) en todo el registro
DATA.setdefault("kpis", {})["dias_alto"] = sum(1 for v in ica_pm if v > 50)
DATA["generado"] = str(dt.date.today())
DATA.setdefault("kpis", {})
DATA["kpis"]["ica_hoy"] = ica_val[-1]
DATA["kpis"]["pm10_hoy"] = ica_pm[-1]
open(p, "w").write("window.DASHBOARD_DATA = " + json.dumps(DATA, ensure_ascii=False) + ";\n")
print(f"Panel actualizado SIN reentrenar: ICA {len(ica_dates)} días, mapa {len(mdates)} días, al {DATA['generado']}.")
