#!/usr/bin/env python3
"""
RF3 - Indice de Calidad del Aire (ICA) a partir del PM10 (µg/m³, prom. 24h).
Usa los tramos del AQI (EPA) con etiquetas en español.
Salidas: data/processed/ica_diario_laboca.csv  y  reports/06_ica.png
"""
import csv, os, datetime as dt, statistics as st
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(BASE, "data", "processed"); REP = os.path.join(BASE, "reports")
os.makedirs(REP, exist_ok=True)

# tramos AQI para PM10 24h: (C_lo, C_hi, I_lo, I_hi, categoria, color)
BP = [(0,54,0,50,"Buena","#16a34a"),(55,154,51,100,"Aceptable","#eab308"),
      (155,254,101,150,"Dañina (grupos sensibles)","#f97316"),
      (255,354,151,200,"Dañina","#dc2626"),(355,424,201,300,"Muy dañina","#7c3aed"),
      (425,604,301,500,"Peligrosa","#7f1d1d")]

def ica(pm10):
    for clo,chi,ilo,ihi,cat,col in BP:
        if pm10 <= chi:
            val = (ihi-ilo)/(chi-clo)*(pm10-clo)+ilo
            return round(val), cat, col
    return 500, "Peligrosa", "#7f1d1d"

# PM10 real diario (promedio del dia)
daily = {}
with open(os.path.join(PROC, "dataset_modelo_laboca.csv")) as f:
    for r in csv.DictReader(f):
        v = r["pm10_real"]
        if v not in ("", "None"):
            daily.setdefault(r["time"][:10], []).append(float(v))

rows = []
for d in sorted(daily):
    pm = st.mean(daily[d]); val, cat, col = ica(pm)
    rows.append({"fecha": d, "pm10": round(pm,1), "ica": val, "categoria": cat})

with open(os.path.join(PROC, "ica_diario_laboca.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["fecha","pm10","ica","categoria"]); w.writeheader(); w.writerows(rows)

# distribucion por categoria
from collections import Counter
c = Counter(r["categoria"] for r in rows); n = len(rows)
print("RF3 - ICA diario La Boca (", n, "dias )")
cats = [b[4] for b in BP]; cols = {b[4]: b[5] for b in BP}
for cat in cats:
    if c[cat]: print(f"  {cat:28s} {c[cat]:5d} dias ({100*c[cat]/n:.1f}%)")

fig, ax = plt.subplots(figsize=(8,4))
present = [cat for cat in cats if c[cat]]
ax.bar(present, [100*c[cat]/n for cat in present], color=[cols[cat] for cat in present])
ax.set_ylabel("% de días"); ax.set_title("RF3 — Distribución del ICA (PM10) en La Boca")
plt.xticks(rotation=20, ha="right"); fig.tight_layout()
fig.savefig(os.path.join(REP, "06_ica.png")); plt.close(fig)
print("OK -> data/processed/ica_diario_laboca.csv , reports/06_ica.png")
