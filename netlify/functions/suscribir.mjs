// POST /suscribir  { email, loc:{id,name,lat,lon} }
// Guarda el correo + zona (Netlify Blobs) y manda bienvenida con el pronóstico de su zona.
import { addSub, cargarModelo, estimaciones, construirMail, enviarMail, mananaISO, DEFAULT_LOC } from "./_lib.mjs";

export default async (req) => {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });
  let email = "", loc = null;
  try { ({ email, loc } = await req.json()); } catch { /* body vacío */ }
  email = (email || "").trim();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email))
    return Response.json({ ok: false, error: "correo inválido" }, { status: 400 });
  loc = loc || DEFAULT_LOC;

  await addSub(email, loc);

  let bienvenida = false;
  try {
    const mapa = await cargarModelo();
    const est = estimaciones(mapa, loc.lat, loc.lon, [[mananaISO(), "mañana"]]);
    if (est.length) {
      const { asunto, cuerpo } = construirMail(loc.name, est, { bienvenida: true });
      await enviarMail([email], asunto, cuerpo);
      bienvenida = true;
    }
  } catch (e) { /* best-effort */ }

  return Response.json({ ok: true, bienvenida });
};
