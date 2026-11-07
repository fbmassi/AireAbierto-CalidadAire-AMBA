// Lógica compartida de las funciones de AireAbierto — PM10 por ZONA del suscriptor.
// Estima el PM10 del MODELO en la ubicación de cada suscriptor (IDW desde las 3 estaciones).
import nodemailer from "nodemailer";
import { getStore } from "@netlify/blobs";

// Cortes sobre la PREDICCIÓN del modelo. Originales: Precaución=40 / Alerta=50 (niveles
// de salud). El modelo subestima los picos (~10 menos en días altos) pero los ordena bien,
// así que bajamos los cortes ~10 para que el aviso dispare a tiempo (a costa de alguna
// falsa alarma). Deben coincidir con scripts/alerta_mail.py.
const PREC = 30, ALERT = 40;
const ORDER = { Normal: 0, "Precaución": 1, ALERTA: 2 };
const ADV = {
  ALERTA: "nivel alto: evitá la actividad al aire libre y la exposición en zonas de tránsito.",
  "Precaución": "grupos sensibles (asma, niños, mayores): precaución al aire libre.",
  Normal: "sin restricciones.",
};
export const DEFAULT_LOC = { id: "laboca", name: "La Boca", lat: -34.6253, lon: -58.3664 };

export function nivel(v, alert = ALERT) { return v > alert ? "ALERTA" : (v > PREC ? "Precaución" : "Normal"); }

// MODEL_MAP de pollutants_data.js (PM10 predicho en las 3 estaciones + coords)
export async function cargarModelo() {
  const base = process.env.URL || process.env.DEPLOY_PRIME_URL || process.env.DEPLOY_URL;
  const r = await fetch(`${base}/pollutants_data.js`, { headers: { "cache-control": "no-cache" } });
  const txt = await r.text();
  const i = txt.lastIndexOf("window.MODEL_MAP");
  return JSON.parse(txt.slice(txt.indexOf("{", i), txt.lastIndexOf("}") + 1));
}

export function estimar(mapa, lat, lon, fecha) {   // IDW desde las estaciones
  const j = (mapa.dates || []).indexOf(fecha); if (j < 0) return null;
  let num = 0, den = 0;
  mapa.puntos.forEach((p, k) => {
    const v = mapa.pm10[j][k]; if (v == null) return;
    const d = Math.max(Math.hypot(lat - p.lat, lon - p.lon), 1e-4), w = 1 / (d * d);
    num += w * v; den += w;
  });
  return den ? num / den : null;
}

export function estimaciones(mapa, lat, lon, fechas) {
  const out = [];
  for (const [d, et] of fechas) { const v = estimar(mapa, lat, lon, d); if (v != null) out.push([d, et, Math.round(v * 10) / 10]); }
  return out;
}

export function construirMail(zona, est, { bienvenida = false } = {}) {
  let peor = "Normal"; const lineas = [];
  for (const [d, et, v] of est) { const n = nivel(v); if (ORDER[n] > ORDER[peor]) peor = n;
    lineas.push(`  ${et} (${d}): PM10 ${Math.round(v)} µg/m³ — ${n}: ${ADV[n]}`); }
  const cab = bienvenida
    ? `¡Gracias por suscribirte a AireAbierto!\nVas a recibir un aviso cuando el PM10 supere el umbral en ${zona}.\nPronóstico del modelo:\n`
    : `AireAbierto — PM10 pronosticado en ${zona}\n`;
  const cuerpo = [cab, ...lineas, "", `Nivel máximo: ${peor}.`,
    "Estimación del modelo (interpolada desde las estaciones de CABA). Prototipo — Seminario 2."].join("\n");
  const asunto = bienvenida ? `[AireAbierto] Suscripción confirmada — ${zona}` : `[AireAbierto] PM10 en ${zona}: nivel ${peor}`;
  return { asunto, cuerpo, peor };
}

export async function enviarMail(destinatarios, asunto, cuerpo) {
  const t = nodemailer.createTransport({
    host: process.env.MAIL_HOST || "smtp.gmail.com", port: Number(process.env.MAIL_PORT || 587),
    secure: false, auth: { user: process.env.MAIL_USER, pass: process.env.MAIL_PASS },
  });
  await t.sendMail({ from: `AireAbierto <${process.env.MAIL_FROM || process.env.MAIL_USER}>`,
    to: destinatarios.join(", "), subject: asunto, text: cuerpo });
}

// Suscriptos en Netlify Blobs: lista de {email, loc}
function store() { return getStore("aireabierto"); }
export async function getSubs() {
  const j = await store().get("subscribers", { type: "json" });
  return Array.isArray(j) ? j.map(s => (typeof s === "string" ? { email: s, loc: DEFAULT_LOC } : s)) : [];
}
export async function addSub(email, loc) {
  const subs = (await getSubs()).filter(s => s.email !== email);
  subs.push({ email, loc: loc || DEFAULT_LOC });
  await store().setJSON("subscribers", subs);
  return subs;
}

// Fechas en hora de Argentina (como en local). Netlify corre en UTC: desde las 21:00 ART
// el "hoy" UTC ya es el día siguiente y "mañana" caía fuera de los datos del modelo.
const fechaAR = (ms) => new Intl.DateTimeFormat("en-CA", { timeZone: "America/Argentina/Buenos_Aires" }).format(new Date(ms));
export const hoyISO = () => fechaAR(Date.now());
export const mananaISO = () => fechaAR(Date.now() + 86400000);
