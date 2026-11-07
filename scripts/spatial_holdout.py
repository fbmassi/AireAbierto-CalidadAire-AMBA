#!/usr/bin/env python3
"""
Holdout ESPACIAL: estimar la calidad del aire en una estacion SIN sensor.
- 3 estaciones reales de CABA: Centenario, Cordoba, La Boca.
- Leave-one-station-out: entreno con 2, predigo la 3ra usando SOLO meteo+CAMS+fuego
  (NO se usa el PM historico de la estacion oculta: se asume que no tiene sensor).
- Tarea: ESTIMACION del PM10 medio del dia (nowcast espacial), no pronostico.
- Baselines: CAMS crudo y media de las estaciones de entrenamiento.
Salida: reports/holdout_metrics.txt y reports/05_holdout_espacial.png
"""
import csv, os, math, datetime as dt, urllib.request, urllib.parse, json, time
import numpy as np
from sklearn.ensemble import RandomForestRegressor
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(BASE, "data", "processed")
RAWC = os.path.join(BASE, "data", "raw", "caba_oficial")
RAWE = os.path.join(BASE, "data", "raw", "estaciones_holdout"); os.makedirs(RAWE, exist_ok=True)
REP  = os.path.join(BASE, "reports"); os.makedirs(REP, exist_ok=True)
START, END, TZ = "2022-08-01", "2026-09-30", "America/Argentina/Buenos_Aires"
MES = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}

# nombre_en_csv -> (col_historico, col_anio, lat, lon)
STATIONS = {
    "centenario": ("PM10_CENTENARIO", "pm10_centenario", -34.6066080998154, -58.4320717652753),
    "cordoba":    ("PM10_CORDOBA",    "pm10_cordoba",    -34.5995643433432, -58.3915528934620),
    "laboca":     ("PM10_LA_BOCA",    "pm10_la_boca",    -34.6252584813295, -58.3663735070165),
}

def fl(v):
    try: return float(v)
    except (TypeError, ValueError): return None

# ---------- 1) descargar/cachear features Open-Meteo por estacion ----------
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "AireAbierto/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r: return json.load(r)

def get_openmeteo(name, lat, lon):
    pj = os.path.join(RAWE, f"{name}.json")
    if os.path.exists(pj):
        return json.load(open(pj))
    aq = fetch("https://air-quality-api.open-meteo.com/v1/air-quality?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "hourly": "pm10",
        "start_date": START, "end_date": END, "timezone": TZ})); time.sleep(1)
    wx = fetch("https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_direction_10m,surface_pressure,cloud_cover",
        "start_date": START, "end_date": END, "timezone": TZ})); time.sleep(1)
    obj = {"aq": aq["hourly"], "wx": wx["hourly"]}
    json.dump(obj, open(pj, "w")); return obj

def daily_features(om):
    aq, wx = om["aq"], om["wx"]
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
        cp = fl(aq["pm10"][i])
        if cp is not None: a["cpm10"].append(cp)
    out = {}
    for d, a in days.items():
        if not a["temp"]: continue
        mu, mv = (np.mean(a["u"]) if a["u"] else 0.0), (np.mean(a["v"]) if a["v"] else 0.0)
        norm = math.hypot(mu, mv)
        out[d] = {"temp": np.mean(a["temp"]), "rh": np.mean(a["rh"]),
                  "prec": sum(a["prec"]) if a["prec"] else 0.0, "wind": np.mean(a["wind"]) if a["wind"] else 0.0,
                  "pres": np.mean(a["pres"]), "cloud": np.mean(a["cloud"]),
                  "cpm10": np.mean(a["cpm10"]) if a["cpm10"] else np.nan,
                  "wdir_sin": (mu/norm if norm else 0.0), "wdir_cos": (mv/norm if norm else 0.0)}
    return out

# ---------- 2) PM10 real diario por estacion ----------
def load_real():
    real = {k: {} for k in STATIONS}
    def add(d_iso, rowget):
        for name,(ch,ca,_,_) in STATIONS.items():
            pass
    # historico
    with open(os.path.join(RAWC, "historico_desde2009.csv"), encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            s = (row.get("FECHA") or "").split(":")[0]
            try: d = dt.date(int(s[5:9]), MES[s[2:5]], int(s[0:2])).isoformat()
            except Exception: continue
            for name,(ch,ca,_,_) in STATIONS.items():
                v = fl(row.get(ch))
                if v is not None: real[name].setdefault(d, []).append(v)
    for fn in ("anio2025.csv", "anio2026.csv"):
        p = os.path.join(RAWC, fn)
        if not os.path.exists(p): continue
        with open(p, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                d = (row.get("fecha") or "").strip()
                if not d: continue
                for name,(ch,ca,_,_) in STATIONS.items():
                    v = fl(row.get(ca))
                    if v is not None: real[name].setdefault(d, []).append(v)
    return {n: {d: float(np.mean(vs)) for d, vs in dd.items()} for n, dd in real.items()}

# ---------- 3) FIRMS diario (ciudad) ----------
firms = {}
with open(os.path.join(PROC, "firms_daily.csv")) as f:
    for r in csv.DictReader(f): firms[r["fecha"]] = r

real = load_real()
FEATS = ["temp","rh","prec","wind","wdir_sin","wdir_cos","pres","cloud","cpm10",
         "focos","frp","lat","lon","doy_cos","dow"]

rows = []   # (station, date, x[], y, cams_pm10)
for name,(ch,ca,lat,lon) in STATIONS.items():
    feats = daily_features(get_openmeteo(name, lat, lon))
    for d, y in real[name].items():
        ff = feats.get(d)
        if ff is None or (isinstance(ff["cpm10"],float) and np.isnan(ff["cpm10"])): continue
        fr = firms.get(d, {})
        dd = dt.date.fromisoformat(d); doy = dd.timetuple().tm_yday
        feat = {**ff, "focos": int(fr.get("n_focos_150km",0) or 0), "frp": fl(fr.get("frp_sum")) or 0.0,
                "lat": lat, "lon": lon, "doy_sin": math.sin(2*math.pi*doy/365),
                "doy_cos": math.cos(2*math.pi*doy/365), "dow": dd.weekday()}
        rows.append((name, d, [feat[k] for k in FEATS], y, ff["cpm10"]))

def met(a,b):
    a,b=np.array(a),np.array(b)
    mae=float(np.mean(np.abs(a-b))); rmse=float(np.sqrt(np.mean((a-b)**2)))
    r2=float(1-np.sum((a-b)**2)/np.sum((a-np.mean(a))**2)); return mae,rmse,r2

L=[f"Holdout espacial (leave-one-station-out) | {len(rows)} dias-estacion"]
L.append(f"Estaciones: {', '.join(STATIONS)}")
L.append("")
fig, axes = plt.subplots(1, 3, figsize=(15,4), sharey=True)
agg_rf, agg_y = [], []
for ax, held in zip(axes, STATIONS):
    tr = [r for r in rows if r[0]!=held]; te = [r for r in rows if r[0]==held]
    Xtr=np.array([r[2] for r in tr]); ytr=np.array([r[3] for r in tr])
    Xte=np.array([r[2] for r in te]); yte=np.array([r[3] for r in te])
    cams_te=np.array([r[4] for r in te])
    # baseline media de estaciones de entrenamiento por dia
    tr_by_day={}
    for r in tr: tr_by_day.setdefault(r[1],[]).append(r[3])
    mean_te=np.array([np.mean(tr_by_day.get(r[1],[np.mean(ytr)])) for r in te])
    rf=RandomForestRegressor(n_estimators=300,min_samples_leaf=2,random_state=42,n_jobs=-1).fit(Xtr,ytr)
    pred=rf.predict(Xte)
    agg_rf+=list(pred); agg_y+=list(yte)
    L.append(f"[{held}]  n_test={len(te)}")
    L.append(f"   {'CAMS crudo':22s} MAE {met(yte,cams_te)[0]:5.2f}  RMSE {met(yte,cams_te)[1]:5.2f}  R2 {met(yte,cams_te)[2]:+.2f}")
    L.append(f"   {'Media estac. entren.':22s} MAE {met(yte,mean_te)[0]:5.2f}  RMSE {met(yte,mean_te)[1]:5.2f}  R2 {met(yte,mean_te)[2]:+.2f}")
    L.append(f"   {'Random Forest (fusion)':22s} MAE {met(yte,pred)[0]:5.2f}  RMSE {met(yte,pred)[1]:5.2f}  R2 {met(yte,pred)[2]:+.2f}")
    L.append("")
    ax.scatter(yte,pred,s=7,alpha=.3,color="#2563eb")
    lim=[0,max(yte.max(),pred.max())]; ax.plot(lim,lim,color="#111827",lw=1)
    ax.set_title(f"{held}  (R²={met(yte,pred)[2]:.2f})"); ax.set_xlabel("PM10 real")
axes[0].set_ylabel("PM10 estimado")
fig.suptitle("Holdout espacial: estimar una estación sin sensor (solo meteo+CAMS+fuego)")
fig.tight_layout(); fig.savefig(os.path.join(REP,"05_holdout_espacial.png")); plt.close(fig)

L.append(f"GLOBAL (las 3 ocultas juntas): MAE {met(agg_y,agg_rf)[0]:.2f}  RMSE {met(agg_y,agg_rf)[1]:.2f}  R2 {met(agg_y,agg_rf)[2]:+.2f}")
rep="\n".join(L); print(rep); open(os.path.join(REP,"holdout_metrics.txt"),"w").write(rep+"\n")
