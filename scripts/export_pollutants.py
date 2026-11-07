#!/usr/bin/env python3
"""
Pronóstico a +1 día de PM10 en las 3 estaciones reales de CABA (La Boca, Centenario, Córdoba).
Dos modelos por estación:
  - Validado: usa el PM10 medido reciente (más preciso; queda ~1 semana atrás por el rezago del sensor).
  - Operativo: SIN el sensor (solo CAMS + meteo de pronóstico + fuego) → predice MAÑANA en vivo.
Features reducidas: se sacaron las que metían ruido (análisis drop-one / permutación).
  · validado saca: valor-ayer (self_l1), presión, estacionalidad (doy_sin/doy_cos).
  · operativo saca: CAMS-ayer (cams_l1), doy_sin.
Escribe dashboard/pollutants_data.js -> window.POLLUTANTS[estacion].pm10 (+ .op).
"""
import os, math, json, datetime as dt
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from estaciones import STATIONS, load_real, get_openmeteo, daily_features, firms_daily, live_daily

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "dashboard")
UNIT = "µg/m³"

# Único modelo: OPERATIVO (basado en CAMS, sin el sensor) → corre en vivo. Features sin ruido.
FEATS_OP = ["cams", "temp", "rh", "prec", "wind", "wdir_sin", "wdir_cos", "pres", "cloud", "focos", "frp", "dow", "doy_cos"]
FEAT_ES = {"self": "PM10 hoy", "cams": "CAMS PM10", "temp": "temperatura", "rh": "humedad", "prec": "lluvia",
    "wind": "viento", "wdir_sin": "dir. viento E-O", "wdir_cos": "dir. viento N-S", "pres": "presión",
    "cloud": "nubosidad", "focos": "focos fuego", "frp": "intensidad fuego", "dow": "día semana", "doy_cos": "estación"}

REAL = load_real(); FIRMS = firms_daily()


def met(a, b):
    a, b = np.array(a), np.array(b)
    return (round(float(np.mean(np.abs(a-b))), 2), round(float(np.sqrt(np.mean((a-b)**2))), 2),
            round(float(1 - np.sum((a-b)**2)/np.sum((a-np.mean(a))**2)), 3))


def build_records(station):
    feats = daily_features(get_openmeteo(station)); rl = REAL[station]["pm10"]; rec = []
    for d in sorted(feats):
        ff = feats[d]; dd = dt.date.fromisoformat(d); doy = dd.timetuple().tm_yday; fr = FIRMS.get(d, {})
        rec.append({"date": dd, "pm10": rl.get(d, np.nan), "cams": ff["cpm10"],
            "temp": ff["temp"], "rh": ff["rh"], "prec": ff["prec"], "wind": ff["wind"],
            "pres": ff["pres"], "cloud": ff["cloud"], "wdir_sin": ff["wdir_sin"], "wdir_cos": ff["wdir_cos"],
            "focos": int(fr.get("n_focos_150km", 0) or 0), "frp": float(fr.get("frp_sum", 0) or 0),
            "dow": dd.weekday(), "doy_cos": math.cos(2*math.pi*doy/365)})
    return rec


def vecf(r):
    f = dict(r); f["self"] = r["pm10"]; return f


def importancia(rf, FE):
    return sorted([{"feat": FEAT_ES.get(k, k), "imp": round(float(i), 3)} for k, i in zip(FE, rf.feature_importances_)],
                  key=lambda x: -x["imp"])[:8]


def operativo(rec, by, station):
    X, y, ds = [], [], []
    for r in rec:
        dn = r["date"] + dt.timedelta(1)
        if dn not in by or np.isnan(by[dn]["pm10"]): continue
        f = vecf(r)
        if any(isinstance(f[k], float) and np.isnan(f[k]) for k in FEATS_OP): continue
        X.append([f[k] for k in FEATS_OP]); y.append(by[dn]["pm10"]); ds.append(dn)
    X, y = np.array(X), np.array(y); n = len(y)
    if n < 80: return None
    cut = int(n*0.8)
    rf = RandomForestRegressor(300, min_samples_leaf=2, random_state=42, n_jobs=-1).fit(X[:cut], y[:cut])
    mae, rmse, r2 = met(y[cut:], rf.predict(X[cut:])); persist = met(y[cut:], X[cut:, 0])[0]
    pred_full = rf.predict(X)
    rf_all = RandomForestRegressor(300, min_samples_leaf=2, random_state=42, n_jobs=-1).fit(X, y)
    series = []   # cola EN VIVO (hasta mañana) desde el pronóstico satelital/meteo
    try:
        hoy = dt.date.today().isoformat(); live = live_daily(station)
        for d in [x for x in sorted(live) if x <= hoy]:
            ff = live[d]; dd = dt.date.fromisoformat(d); doy = dd.timetuple().tm_yday; fr = FIRMS.get(d, {})
            row = {"cams": ff["cpm10"], "temp": ff["temp"], "rh": ff["rh"], "prec": ff["prec"], "wind": ff["wind"],
                   "wdir_sin": ff["wdir_sin"], "wdir_cos": ff["wdir_cos"], "pres": ff["pres"], "cloud": ff["cloud"],
                   "focos": int(fr.get("n_focos_150km", 0) or 0), "frp": float(fr.get("frp_sum", 0) or 0),
                   "dow": dd.weekday(), "doy_cos": math.cos(2*math.pi*doy/365)}
            if any((v is None) or (isinstance(v, float) and np.isnan(v)) for v in (row[k] for k in FEATS_OP)): continue
            series.append({"fecha": str(dd + dt.timedelta(1)), "val": round(float(rf_all.predict([[row[k] for k in FEATS_OP]])[0]), 2)})
    except Exception as e:
        print(f"   (operativo {station}: pronóstico en vivo no disponible: {e})")
    last_hist = ds[-1]
    tail = [s for s in series if dt.date.fromisoformat(s["fecha"]) > last_hist]
    dates = [str(x) for x in ds] + [s["fecha"] for s in tail]
    real = [round(float(v), 2) for v in y] + [None for _ in tail]
    pred = [round(float(v), 2) for v in pred_full] + [s["val"] for s in tail]
    manana = str(dt.date.today() + dt.timedelta(1))
    nxt = next((s for s in series if s["fecha"] == manana), (series[-1] if series else None))
    return {"metrics": {"mae": mae, "rmse": rmse, "r2": r2, "persist_mae": persist},
            "importance": importancia(rf, FEATS_OP), "next": nxt,
            "forecast_full": {"dates": dates, "real": real, "pred": pred, "cut": str(ds[cut])}}


out = {}
print(f"{'Estación':12}{'MAE':>8}{'R2':>8}{'persist.CAMS':>14}")
for st, meta in STATIONS.items():
    rec = build_records(st); by = {r["date"]: r for r in rec}
    op = operativo(rec, by, st)
    if not op:
        out[st] = {"label": meta["label"], "pm10": {"label": "PM10", "unit": UNIT, "insufficient": True}}; continue
    out[st] = {"label": meta["label"], "pm10": {"label": "PM10", "unit": UNIT, **op}}
    nf = (op.get("next") or {}).get("fecha", "—")
    print(f"{meta['label']:12}{op['metrics']['mae']:>8}{op['metrics']['r2']:>8}{op['metrics']['persist_mae']:>14}   → mañana {nf}")

# mapa del MODELO: PM10 predicho en las 3 estaciones (para interpolar IDW sobre el AMBA)
pts = [{"nombre": meta["label"], "lat": meta["lat"], "lon": meta["lon"]} for st, meta in STATIONS.items()]
serie = {st: dict(zip(out[st]["pm10"]["forecast_full"]["dates"], out[st]["pm10"]["forecast_full"]["pred"]))
         for st in STATIONS if "forecast_full" in out[st]["pm10"]}
alldates = sorted(set().union(*[set(s) for s in serie.values()])) if serie else []
model_map = {"puntos": pts, "dates": alldates,
             "pm10": [[serie.get(st, {}).get(d) for st in STATIONS] for d in alldates]}

with open(os.path.join(OUT, "pollutants_data.js"), "w") as f:
    f.write("window.POLLUTANTS = " + json.dumps(out, ensure_ascii=False) + ";\n")
    f.write("window.MODEL_MAP = " + json.dumps(model_map, ensure_ascii=False) + ";\n")
print("\nOK -> dashboard/pollutants_data.js  (PM10 · estaciones:", ", ".join(STATIONS), ")")
