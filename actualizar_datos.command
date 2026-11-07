#!/bin/bash
# AireAbierto — botón de actualización diaria.
# Doble clic en Finder para actualizar los datos y reentrenar el modelo.
cd "$(dirname "$0")"

# Las credenciales (FIRMS_MAP_KEY, SMTP) las lee el pipeline desde .env — no van acá.
echo "============================================"
echo "   AireAbierto · Actualización de datos"
echo "============================================"
./.venv/bin/python scripts/update_daily.py
echo ""
echo "Podés cerrar esta ventana."
read -n 1 -s
