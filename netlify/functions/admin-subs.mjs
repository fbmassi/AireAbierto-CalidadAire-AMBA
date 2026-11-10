// Endpoint de administración de suscriptos, protegido por token.
// Requiere la variable de entorno ADMIN_TOKEN en Netlify. Sin ella, responde 401 (falla cerrado).
//   ver cuántos hay:  /.netlify/functions/admin-subs?token=TUCLAVE&action=count
//   resetear a cero:  /.netlify/functions/admin-subs?token=TUCLAVE&action=reset
// El token puede ir como ?token= o en el header x-admin-token.
import { getSubs, clearSubs } from "./_lib.mjs";

export default async (req) => {
  const url = new URL(req.url);
  const token = url.searchParams.get("token") || req.headers.get("x-admin-token") || "";
  const expected = process.env.ADMIN_TOKEN || "";
  if (!expected || token !== expected)
    return new Response("No autorizado (falta ADMIN_TOKEN o token incorrecto).", { status: 401 });

  const subs = await getSubs();
  const action = (url.searchParams.get("action") || "count").toLowerCase();

  if (action === "reset") {
    await clearSubs();
    return Response.json({ ok: true, action: "reset", antes: subs.length, ahora: 0 });
  }
  return Response.json({ ok: true, action: "count", suscriptos: subs.length });
};
