#!/usr/bin/env python3
"""
Servidor local del panel AireAbierto.
Sirve dashboard/ y expone POST /actualizar, que corre update_daily.py
(descarga datos del día + reentrena + regenera el panel). El botón
'Actualizar datos' de la interfaz llama a ese endpoint.
Uso:  ./.venv/bin/python scripts/servidor.py    (o doble clic en panel.command)
"""
import http.server, socketserver, subprocess, os, json, functools
import _env; _env.load_env()   # carga .env (MAIL_* / FIRMS) a os.environ; los subprocesos lo heredan

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASH = os.path.join(PROJECT, "dashboard")
PY = os.path.join(PROJECT, ".venv", "bin", "python")
PORT = 8777

class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")   # siempre datos frescos
        super().end_headers()

    def guess_type(self, path):                          # charset UTF-8 (acentos y µg/m³)
        if path.endswith(".html"): return "text/html; charset=utf-8"
        if path.endswith(".js"):   return "text/javascript; charset=utf-8"
        if path.endswith(".json"): return "application/json; charset=utf-8"
        return super().guess_type(path)

    def log_message(self, *a):  # silencioso
        pass

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        p = self.path.rstrip("/")
        if p == "/actualizar":
            env = os.environ.copy()   # hereda FIRMS_MAP_KEY / SMTP ya cargados de .env
            try:
                print(">> Actualizando datos (puede tardar 1–2 min)…")
                subprocess.run([PY, "scripts/update_daily.py"], cwd=PROJECT, env=env, check=True)
                payload = {"ok": True}; print(">> Listo.")
            except subprocess.CalledProcessError as e:
                payload = {"ok": False, "error": str(e)}; print(">> Falló:", e)
            self._json(payload)
        elif p == "/suscribir":
            import re
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                email = (body.get("email") or "").strip()
                if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                    raise ValueError("correo inválido")
                loc = body.get("loc") or {"id": "laboca", "name": "La Boca", "lat": -34.6253, "lon": -58.3664}
                cfgp = os.path.join(PROJECT, "scripts", "config_mail.json")
                # solo datos NO secretos; las credenciales SMTP viven en .env
                cfg = json.load(open(cfgp)) if os.path.exists(cfgp) else {"destinatarios": [], "umbral": 50}
                dests = cfg.setdefault("destinatarios", [])
                _em = lambda d: d if isinstance(d, str) else d.get("email")
                dests[:] = [d for d in dests if _em(d) != email]          # saca duplicados del mismo correo
                dests.append({"email": email, "loc": loc})                 # guarda correo + zona
                json.dump(cfg, open(cfgp, "w"), ensure_ascii=False, indent=2)
                print(f">> Suscripto: {email} · {loc.get('name')}")
                # mail de bienvenida con el pronóstico de mañana en su zona (best-effort)
                bienvenida_ok = False
                try:
                    import datetime as _dt
                    manana = (_dt.date.today() + _dt.timedelta(days=1)).isoformat()
                    out = subprocess.run(
                        [PY, "scripts/alerta_mail.py", "--fecha", manana, "--forzar", "--bienvenida", "--solo", email,
                         "--lat", str(loc["lat"]), "--lon", str(loc["lon"]), "--zona", str(loc.get("name", ""))],
                        cwd=PROJECT, capture_output=True, text=True, timeout=60)
                    bienvenida_ok = "enviado" in ((out.stdout or "") + (out.stderr or ""))
                    print(">> Bienvenida", "enviada." if bienvenida_ok else "no enviada (¿SMTP sin configurar?).")
                except Exception as _e:
                    print(">> Bienvenida no enviada:", _e)
                payload = {"ok": True, "bienvenida": bienvenida_ok}
            except Exception as e:
                payload = {"ok": False, "error": str(e)}
            self._json(payload)
        elif p == "/enviar":
            import re
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                fecha = (body.get("fecha") or "").strip()
                cmd = [PY, "scripts/alerta_mail.py", "--forzar"]
                if re.match(r"^\d{4}-\d{2}-\d{2}$", fecha):
                    cmd += ["--fecha", fecha]
                print(f">> Enviando alerta por mail ({fecha or 'hoy/mañana'})…")
                out = subprocess.run(cmd, cwd=PROJECT, capture_output=True, text=True)
                log = ((out.stdout or "") + (out.stderr or "")).strip()
                ok = ("✓ Mail" in log) or ("enviado" in log)
                payload = {"ok": ok, "log": log[-500:]}
                print(">>", "Enviado." if ok else "No se envió (ver log).")
            except Exception as e:
                payload = {"ok": False, "error": str(e)}
            self._json(payload)
        else:
            self.send_error(404)

class Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = True   # evita el "Address already in use" por sockets en TIME_WAIT

if __name__ == "__main__":
    os.chdir(DASH)
    handler = functools.partial(Handler, directory=DASH)
    try:
        httpd = Servidor(("127.0.0.1", PORT), handler)
    except OSError as e:
        if getattr(e, "errno", None) == 48:
            print(f"El puerto {PORT} ya está en uso: probablemente el panel YA está corriendo.")
            print(f"  → Abrí http://localhost:{PORT}/index.html")
            print(f"  → O reiniciá con:  lsof -ti tcp:{PORT} | xargs kill")
            raise SystemExit(1)
        raise
    with httpd:
        print(f"Panel AireAbierto en  http://localhost:{PORT}/index.html")
        print("Dejá esta ventana abierta mientras usás el panel. Ctrl+C para cerrar.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor detenido.")
