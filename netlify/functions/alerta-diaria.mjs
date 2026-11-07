// Función PROGRAMADA (11:00 UTC ≈ 08:00 ART). Por cada suscriptor estima el PM10 del
// modelo en SU zona (IDW) para hoy y mañana; si supera el umbral, le manda el aviso.
import { getSubs, cargarModelo, estimaciones, construirMail, enviarMail, nivel, hoyISO, mananaISO } from "./_lib.mjs";

export default async () => {
  const subs = await getSubs();
  if (!subs.length) return;

  let mapa;
  try { mapa = await cargarModelo(); } catch (e) { console.error("alerta-diaria: no se pudo cargar el modelo:", e); return; }

  const fechas = [[hoyISO(), "hoy"], [mananaISO(), "mañana"]];
  for (const s of subs) {
    const loc = s.loc || {};
    const est = estimaciones(mapa, loc.lat, loc.lon, fechas);
    if (!est.length) { console.warn(`alerta-diaria: sin pronóstico para ${hoyISO()}/${mananaISO()}`); continue; }
    if (!est.some(([, , v]) => nivel(v) !== "Normal")) continue;   // todo Normal → no se envía
    const { asunto, cuerpo } = construirMail(loc.name || "tu zona", est, {});
    try { await enviarMail([s.email], asunto, cuerpo); } catch (e) { console.error(`alerta-diaria: falló el envío a ${s.email}:`, e); }
  }
};

export const config = { schedule: "0 11 * * *" };   // 11:00 UTC = 08:00 Argentina
