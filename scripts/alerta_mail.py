#!/usr/bin/env python3
"""
AireAbierto — alerta de PM10 por EMAIL, por ZONA del suscriptor.
Estima el PM10 pronosticado por el MODELO en la ubicación de cada suscriptor
(interpolación IDW desde las 3 estaciones con medición) para HOY y MAÑANA;
si supera el umbral, le manda un aviso personalizado.
Credenciales SMTP: en .env (MAIL_USER / MAIL_PASS). Suscriptos: scripts/config_mail.json.
Uso:  ./.venv/bin/python scripts/alerta_mail.py
"""
import os, json, smtplib, datetime as dt
from email.mime.text import MIMEText
from email.utils import formataddr
import _env

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(BASE, "dashboard")
CFG  = os.path.join(BASE, "scripts", "config_mail.json")

# Umbrales de aviso (µg/m³) aplicados sobre la PREDICCIÓN del modelo.
# Arrancamos en Precaución=40 / Alerta=50 (los niveles "reales" de salud), pero
# el modelo subestima los picos (en los días altos lee ~10 menos que el valor real),
# así que con esos cortes casi nunca disparaba. Como ordena bien los días malos
# (correlación ~0,71), bajamos los cortes ~10 para compensar el sesgo: así el aviso
# dispara a tiempo (capta 7/7 de los días reales >50 y ~3/4 de los >40), a costa de
# alguna falsa alarma — un canje razonable para una alerta de salud.
PREC, ALERT = 30.0, 40.0
ADV = {"ALERTA": "nivel alto: evitá la actividad al aire libre y la exposición en zonas de tránsito.",
       "Precaución": "grupos sensibles (asma, niños, mayores): precaución al aire libre.",
       "Normal": "sin restricciones."}
ORDER = {"Normal": 0, "Precaución": 1, "ALERTA": 2}
DEFAULT_LOC = {"id": "laboca", "name": "La Boca", "lat": -34.6253, "lon": -58.3664}


def niv(v, alert=ALERT):
    return "ALERTA" if v > alert else ("Precaución" if v > PREC else "Normal")


def cargar_modelo():
    """MODEL_MAP de pollutants_data.js: {puntos:[{lat,lon}], dates, pm10:[[val x estación]]}."""
    s = open(os.path.join(DASH, "pollutants_data.js")).read()
    i = s.rindex("window.MODEL_MAP")
    return json.loads(s[s.index("{", i):s.rindex("}") + 1])


def estimar(mapa, lat, lon, fecha):
    """PM10 del modelo en (lat,lon) para la fecha: IDW desde las estaciones."""
    try: j = mapa["dates"].index(fecha)
    except ValueError: return None
    num = den = 0.0
    for p, v in zip(mapa["puntos"], mapa["pm10"][j]):
        if v is None: continue
        d = max(((lat - p["lat"])**2 + (lon - p["lon"])**2) ** 0.5, 1e-4)
        w = 1.0 / d**2
        num += w * v; den += w
    return (num / den) if den else None


def estimaciones(mapa, lat, lon, fechas):
    out = []
    for d, et in fechas:
        v = estimar(mapa, lat, lon, d)
        if v is not None: out.append((d, et, round(v, 1)))
    return out


def construir(zona, est, alert, bienvenida=False):
    peor = "Normal"; lineas = []
    for d, et, v in est:
        n = niv(v, alert); peor = n if ORDER[n] > ORDER[peor] else peor
        lineas.append(f"  {et} ({d}): PM10 {v:.0f} µg/m³ — {n}: {ADV[n]}")
    cab = (f"¡Gracias por suscribirte a AireAbierto!\nVas a recibir un aviso cuando el PM10 supere el umbral en {zona}.\nPronóstico del modelo:\n"
           if bienvenida else f"AireAbierto — PM10 pronosticado en {zona}\n")
    cuerpo = "\n".join([cab] + lineas + ["", f"Nivel máximo: {peor}.",
        "Estimación del modelo (interpolada desde las estaciones de CABA). Prototipo — Seminario 2."])
    asunto = (f"[AireAbierto] Suscripción confirmada — {zona}" if bienvenida
              else f"[AireAbierto] PM10 en {zona}: nivel {peor}")
    return asunto, cuerpo, peor


def enviar(cfg, destinatarios, asunto, cuerpo):
    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"] = asunto
    msg["From"] = formataddr(("AireAbierto", cfg["remitente"]))
    msg["To"] = ", ".join(destinatarios)
    with smtplib.SMTP(cfg.get("smtp_host", "smtp.gmail.com"), int(cfg.get("smtp_port", 587))) as s:
        s.starttls(); s.login(cfg["remitente"], cfg["clave_app"])
        s.sendmail(cfg["remitente"], destinatarios, msg.as_string())


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Alerta de PM10 por email, por zona.")
    ap.add_argument("--fecha", help="YYYY-MM-DD a evaluar (por defecto: hoy y mañana)")
    ap.add_argument("--forzar", action="store_true", help="enviar aunque el nivel sea Normal")
    ap.add_argument("--solo", help="enviar solo a este correo (p. ej. bienvenida)")
    ap.add_argument("--bienvenida", action="store_true", help="mail de confirmación de suscripción")
    ap.add_argument("--lat", type=float); ap.add_argument("--lon", type=float); ap.add_argument("--zona", default="La Boca")
    args = ap.parse_args()

    _env.load_env()
    try: mapa = cargar_modelo()
    except Exception as e:
        print(f"No se pudo leer el modelo (pollutants_data.js): {e}"); return

    hoy = dt.date.today()
    fechas = ([(args.fecha, "fecha")] if args.fecha
              else [((hoy + dt.timedelta(days=o)).isoformat(), et) for o, et in [(0, "hoy"), (1, "mañana")]])

    file_cfg = json.load(open(CFG)) if os.path.exists(CFG) else {}
    cfg = {"smtp_host": os.environ.get("MAIL_HOST", "smtp.gmail.com"),
           "smtp_port": int(os.environ.get("MAIL_PORT", "587")),
           "remitente": os.environ.get("MAIL_USER", ""), "clave_app": os.environ.get("MAIL_PASS", "")}
    alert = float(file_cfg.get("umbral", ALERT))   # el umbral del config pisa el de PM10 (para probar)

    # destino(s): lista de {email, loc}
    if args.solo:
        subs = [{"email": args.solo, "loc": {"name": args.zona, "lat": args.lat if args.lat is not None else DEFAULT_LOC["lat"],
                                             "lon": args.lon if args.lon is not None else DEFAULT_LOC["lon"]}}]
    else:
        subs = []
        for d in file_cfg.get("destinatarios", []):
            if isinstance(d, str): subs.append({"email": d, "loc": DEFAULT_LOC})
            elif d.get("email"):   subs.append({"email": d["email"], "loc": d.get("loc") or DEFAULT_LOC})

    if not subs:
        print("No hay suscriptos."); return

    tiene_cred = bool(cfg["remitente"] and cfg["clave_app"])
    enviados = 0
    for s in subs:
        loc = s["loc"]; est = estimaciones(mapa, loc["lat"], loc["lon"], fechas)
        if not est:
            print(f"  {s['email']} · {loc['name']}: sin pronóstico para esas fechas."); continue
        hay = any(niv(v, alert) != "Normal" for _, _, v in est)
        linea = " · ".join(f"{et} {v:.0f}" for _, et, v in est)
        print(f"  {s['email']:28s} · {loc['name']:22s} PM10 {linea}  →  {'ALERTA' if hay else 'Normal'}")
        if not (hay or args.forzar): continue
        if not tiene_cred:
            print("     (faltan credenciales en .env — MAIL_USER/MAIL_PASS; no se envía)"); continue
        asunto, cuerpo, _ = construir(loc["name"], est, alert, bienvenida=args.bienvenida)
        try:
            enviar(cfg, [s["email"]], asunto, cuerpo); enviados += 1
            print(f"     ✓ Mail enviado a {s['email']}")
        except Exception as e:
            print(f"     ✗ No se pudo enviar a {s['email']}: {e}")
    print(f"\nListo. {enviados} mail(s) enviado(s).")


if __name__ == "__main__":
    main()
