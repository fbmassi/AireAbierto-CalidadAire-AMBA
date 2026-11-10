#!/bin/bash
# AireAbierto — abre el panel con el botón "Actualizar datos".
# Doble clic en Finder. Se abre en tu navegador; dejá esta ventana abierta.
cd "$(dirname "$0")"
( sleep 1.5; open "http://localhost:8777/index.html" ) &
./.venv/bin/python scripts/servidor.py
