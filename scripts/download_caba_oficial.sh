#!/usr/bin/env bash
# Descarga datos REALES de estaciones de calidad de aire de CABA (APrA).
# Fuente: Buenos Aires Data (data.buenosaires.gob.ar) - licencia CC-BY-2.5-AR, sin cuenta.
# Resiliente: reintenta y, si un archivo falla, conserva el anterior (no aborta).
set -uo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)/data/raw/caba_oficial"
mkdir -p "$DIR"; cd "$DIR"
BASE="https://data.buenosaires.gob.ar/dataset/calidad-aire/resource"
declare -A R=(
  [historico_desde2009]="juqdkmgo-291-resource"
  [estaciones]="juqdkmgo-295-resource"
  [contaminantes]="juqdkmgo-294-resource"
  [anio2025]="9c50856f-e443-4ccc-a464-95fb6c190535"
  [anio2026]="da9ee5ee-adeb-4323-b034-b283d340554e"
)
for fn in "${!R[@]}"; do
  if curl -fsS -L --retry 4 --retry-delay 2 --retry-all-errors \
       -A "AireAbierto/1.0" -o "${fn}.csv.tmp" "${BASE}/${R[$fn]}/download"; then
    mv "${fn}.csv.tmp" "${fn}.csv"; echo "$fn.csv -> $(wc -c < "${fn}.csv") bytes"
  else
    rm -f "${fn}.csv.tmp"; echo "$fn.csv -> falló la descarga (se mantiene la versión anterior)"
  fi
done
exit 0
