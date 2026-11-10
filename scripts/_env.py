"""Cargador mínimo de .env (sin dependencias). Lee BASE/.env y puebla os.environ
sin pisar variables ya definidas en el entorno (útil en CI/Netlify donde van por secrets)."""
import os

def load_env(path=None):
    if path is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
