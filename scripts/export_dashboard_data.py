#!/usr/bin/env python3
"""
Exporta TODOS los resultados reales del proyecto a dashboard/data.js
(window.DASHBOARD_DATA) para alimentar el panel HTML (RF7).
"""
import csv, os, math, json, datetime as dt
import numpy as np
from sklearn.ensemble import RandomForestRegressor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(BASE, "data", "processed")
OUT = os.path.join(BASE, "dashboard"); os.makedirs(OUT, exist_ok=True)
UMBRAL = 50.0

def fl(v):
    try: return float(v)
    except (TypeError, ValueError): return None

# ---------- agregacion diaria ----------
days = {}
with open(os.path.join(PROC, "dataset_modelo_laboca.csv")) as f:
    for r in csv.DictReader(f):
        d = r["time"][:10]
        a = days.setdefault(d, {k: [] for k in ["pm10","temp","rh","prec","wind","pres","cloud","cpm10","u","v"]})
        for key,col in [("pm10","pm10_real"),("temp","temperature_2m"),("rh","relative_humidity_2m"),
                        ("prec","precipitation"),("wind","wind_speed_10m"),("pres","surface_pressure"),
                        ("cloud","cloud_cover"),("cpm10","cams_pm10")]:
            v = fl(r[col]);  a[key].append(v) if v is not None else None
        spd,dr = fl(r["wind_speed_10m"]), fl(r["wind_direction_10m"])
        if spd is not None and dr is not None:
            rad=math.radians(dr); a["u"].append(spd*math.sin(rad)); a["v"].append(spd*math.cos(rad))
        a["focos"]=int(r["fire_n_focos_150km"] or 0); a["frp"]=fl(r["fire_frp_sum"]) or 0.0

rec=[]
for d in sorted(days):
    a=days[d]
    if not a["pm10"]: continue
    g=lambda k:(sum(a[k])/len(a[k])) if a[k] else np.nan
    mu,mv=(np.mean(a["u"]) if a["u"] else 0.0),(np.mean(a["v"]) if a["v"] else 0.0); nm=math.hypot(mu,mv)
    rec.append({"date":dt.date.fromisoformat(d),"pm10":g("pm10"),"temp":g("temp"),"rh":g("rh"),
        "prec":sum(a["prec"]) if a["prec"] else 0.0,"wind":g("wind"),"pres":g("pres"),"cloud":g("cloud"),
        "cpm10":g("cpm10"),"wdir_sin":(mu/nm if nm else 0.0),"wdir_cos":(mv/nm if nm else 0.0),
        "focos":a["focos"],"frp":a["frp"]})
by={r["date"]:r for r in rec}
# Modelo OPERATIVO: solo datos disponibles en vivo (CAMS + meteo + fuego), sin el sensor del propio día.
FEATS=["cpm10","temp","rh","prec","wind","wdir_sin","wdir_cos","pres","cloud",
       "focos","frp","dow","doy_cos"]
FEAT_ES={"temp":"temperatura","rh":"humedad","prec":"lluvia",
         "wind":"viento","wdir_sin":"dir. viento (E-O)","wdir_cos":"dir. viento (N-S)","pres":"presión",
         "cloud":"nubosidad","cpm10":"CAMS PM10","focos":"focos fuego","frp":"intensidad fuego",
         "dow":"día semana","doy_cos":"estación (cos)"}

def build(h):
    X,y,ds=[],[],[]
    for r in rec:
        d=r["date"]; d1=d-dt.timedelta(1); dn=d+dt.timedelta(h)
        if d1 not in by or dn not in by: continue
        tgt=by[dn]["pm10"]
        if np.isnan(tgt): continue
        doy=d.timetuple().tm_yday
        feat={**r,"pm10_l1":by[d1]["pm10"],"dow":d.weekday(),
              "doy_sin":math.sin(2*math.pi*doy/365),"doy_cos":math.cos(2*math.pi*doy/365)}
        if any(isinstance(feat[k],float) and np.isnan(feat[k]) for k in FEATS): continue
        X.append([feat[k] for k in FEATS]); y.append(tgt); ds.append(dn)
    return np.array(X),np.array(y),ds

def met(a,b):
    return (float(np.mean(np.abs(a-b))),float(np.sqrt(np.mean((a-b)**2))),
            float(1-np.sum((a-b)**2)/np.sum((a-np.mean(a))**2)))

# modelo +1 (principal) y +2
temporal=[]; fc=None; importance=[]
for h in (1,2):
    X,y,ds=build(h); n=len(y); cut=int(n*0.8)
    rf=RandomForestRegressor(n_estimators=300,min_samples_leaf=2,random_state=42,n_jobs=-1).fit(X[:cut],y[:cut])
    pred=rf.predict(X[cut:]); yte=y[cut:]; dte=ds[cut:]
    mae,rmse,r2=met(yte,pred); pm=met(yte,X[cut:,FEATS.index("cpm10")])  # baseline = CAMS crudo
    temporal.append({"h":h,"mae":round(mae,2),"rmse":round(rmse,2),"r2":round(r2,2),"persist_mae":round(pm[0],2)})
    if h==1:
        fc={"dates":[str(d) for d in dte],"real":[round(float(v),1) for v in yte],
            "pred":[round(float(v),1) for v in pred]}
        # El aviso se evalúa como lo que de verdad hace: ¿avisó en los días realmente
        # elevados? Día real elevado = >40 µg/m³; disparador del modelo = pred>=30
        # (bajado respecto del nivel de salud porque el RF subestima los picos).
        NIV_REAL, TRIGGER = 40.0, 30.0
        real_ex=yte>NIV_REAL; pred_ex=pred>=TRIGGER
        hits=int(np.sum(real_ex&pred_ex)); fa=int(np.sum(~real_ex&pred_ex)); miss=int(np.sum(real_ex&~pred_ex))
        alert={"nivel_real":NIV_REAL,"trigger":TRIGGER,"eventos":int(hits+miss),"detectados":hits,
               "pod":round(hits/(hits+miss),2) if hits+miss else None,
               "far":round(fa/(hits+fa),2) if hits+fa else None}
        importance=sorted([{"feat":FEAT_ES[f_],"imp":round(float(i_),3)} for f_,i_ in zip(FEATS,rf.feature_importances_)],
                          key=lambda x:-x["imp"])[:10]

# proximo pronostico = ultimo dia del dataset -> +1
last=rec[-1]; d=last["date"]; d1=d-dt.timedelta(1); doy=d.timetuple().tm_yday
if d1 in by:
    feat={**last,"pm10_l1":by[d1]["pm10"],"dow":d.weekday(),
          "doy_sin":math.sin(2*math.pi*doy/365),"doy_cos":math.cos(2*math.pi*doy/365)}
    X,y,_=build(1); rf=RandomForestRegressor(n_estimators=300,min_samples_leaf=2,random_state=42,n_jobs=-1).fit(X,y)
    pv=float(rf.predict([[feat[k] for k in FEATS]])[0])
    nivel="ALERTA" if pv>UMBRAL else ("Precaución" if pv>40 else "Bueno")
    nextfc={"fecha":str(d+dt.timedelta(1)),"pm10":round(pv,1),"nivel":nivel}

# ---------- ICA ----------
ica_dates=[]; ica_pm=[]; ica_val=[]
with open(os.path.join(PROC,"ica_diario_laboca.csv")) as f:
    for r in csv.DictReader(f):
        ica_dates.append(r["fecha"]); ica_pm.append(float(r["pm10"])); ica_val.append(int(r["ica"]))
BP=[("Buena","#16a34a",0,50),("Aceptable","#eab308",51,100),("Dañina (sensibles)","#f97316",101,150),
    ("Dañina","#dc2626",151,200),("Muy dañina","#7c3aed",201,300)]
dist=[]
for cat,col,lo,hi in BP:
    c=sum(1 for v in ica_val if lo<=v<=hi)
    if c: dist.append({"cat":cat,"color":col,"pct":round(100*c/len(ica_val),1),"dias":c})

# ---------- episodio humo 2022 ----------
f2022={"dates":[],"pm10":[],"focos":[]}
for r in rec:
    if dt.date(2022,8,1)<=r["date"]<=dt.date(2022,9,15):
        f2022["dates"].append(str(r["date"])); f2022["pm10"].append(round(r["pm10"],1)); f2022["focos"].append(r["focos"])

# ---------- mapa (5 puntos, varios dias) ----------
PUNTOS=[{"nombre":"CABA centro","lat":-34.6037,"lon":-58.3816,"f":"dataset_caba_centro.csv"},
        {"nombre":"La Boca","lat":-34.6345,"lon":-58.3631,"f":"dataset_caba_laboca.csv"},
        {"nombre":"San Isidro","lat":-34.4708,"lon":-58.5126,"f":"dataset_sanisidro_n.csv"},
        {"nombre":"La Plata","lat":-34.9205,"lon":-57.9536,"f":"dataset_laplata.csv"},
        {"nombre":"Moreno","lat":-34.6534,"lon":-58.7920,"f":"dataset_moreno_oeste.csv"}]
def pm_dia(fn,fecha):
    vals=[]
    with open(os.path.join(PROC,fn)) as f:
        for r in csv.DictReader(f):
            if r["time"][:10]==fecha and r["pm10"] not in ("","None"): vals.append(float(r["pm10"]))
    return round(sum(vals)/len(vals),1) if vals else None
DIAS=[("2022-08-19","Humo del Delta (19-ago-2022)"),("2022-10-12","Quemas (12-oct-2022)"),
      ("2023-05-15","Día normal (15-may-2023)"),("2024-01-01","Verano (1-ene-2024)")]
mapa={"puntos":[{"nombre":p["nombre"],"lat":p["lat"],"lon":p["lon"]} for p in PUNTOS],"dias":[]}
for fecha,etiq in DIAS:
    mapa["dias"].append({"fecha":fecha,"etiqueta":etiq,"valores":[pm_dia(p["f"],fecha) for p in PUNTOS]})

# serie diaria COMPLETA (todos los días) para el selector de fecha preciso del mapa
_pp={}
for p in PUNTOS:
    dd={}
    with open(os.path.join(PROC,p["f"])) as f:
        for r in csv.DictReader(f):
            v=r["pm10"]
            if v not in ("","None"):
                day=r["time"][:10]; a=dd.setdefault(day,[0.0,0]); a[0]+=float(v); a[1]+=1
    _pp[p["nombre"]]={day:round(a[0]/a[1],1) for day,a in dd.items()}
_mdates=sorted(set().union(*[set(_pp[p["nombre"]]) for p in PUNTOS]))
map_series={"dates":_mdates,"vals":[[_pp[p["nombre"]].get(d) for p in PUNTOS] for d in _mdates]}

# ---------- alertas demo ----------
alertas=json.load(open(os.path.join(PROC,"alertas_demo.json")))

# ---------- holdout (resumen del experimento) ----------
holdout={"global":{"mae":5.17,"rmse":7.64,"r2":0.52},
         "estaciones":[{"nombre":"Centenario","mae":5.67,"r2":0.46},
                       {"nombre":"Córdoba","mae":4.02,"r2":0.63},
                       {"nombre":"La Boca","mae":5.63,"r2":0.48}],
         "cams_crudo_r2":"negativo (inservible solo)"}

DATA={"generado":str(dt.date.today()),
      "kpis":{"ica_hoy":ica_val[-1],"pm10_hoy":round(ica_pm[-1],1),
              "mae_1d":temporal[0]["mae"],"r2_1d":temporal[0]["r2"],
              "alertas_test":alert["eventos"]},
      "forecast":fc,"next":nextfc,"temporal":temporal,"alert":alert,"holdout":holdout,
      "importance":importance,
      "ica":{"dates":ica_dates,"pm10":[round(v,1) for v in ica_pm],"ica":ica_val,"dist":dist},
      "fire2022":f2022,"mapa":mapa,"map_series":map_series,"alertas":alertas}

with open(os.path.join(OUT,"data.js"),"w") as f:
    f.write("window.DASHBOARD_DATA = "+json.dumps(DATA,ensure_ascii=False)+";\n")
print("OK -> dashboard/data.js")
print(f"  forecast test: {len(fc['dates'])} dias | ICA: {len(ica_dates)} dias | mapa: {len(mapa['dias'])} dias")
print(f"  KPIs: ICA_hoy={ica_val[-1]} PM10_hoy={ica_pm[-1]:.1f} MAE={temporal[0]['mae']} R2={temporal[0]['r2']}")
print(f"  proximo pronostico: {nextfc}")
