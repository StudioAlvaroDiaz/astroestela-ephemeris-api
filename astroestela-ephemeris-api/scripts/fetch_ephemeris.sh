#!/usr/bin/env bash
# Descarga los archivos de Swiss Ephemeris (1800–2399) y verifica su SHA-256.
# Uso: ./scripts/fetch_ephemeris.sh [carpeta_destino]   (por defecto ./data)
set -euo pipefail

DEST="${1:-./data}"
# Commit fijo del repositorio oficial: los archivos no cambian sin que lo sepamos.
BASE="https://raw.githubusercontent.com/aloistr/swisseph/509f93351117fc9e9d1c3cf1f1862556d773b180/ephe"

declare -A SHA256=(
  [sepl_18.se1]=ca1393ceab3a44fbc895887cf789c68819ae6a1cbc9b22225872dbe4ccd99a66
  [semo_18.se1]=1ca07bd67c24374d77226180c20a4f9996cba013697894810518e7eb582ca4f7
  [seas_18.se1]=a2cd8fc33807c78ca9a700c91c2e042258b12fc4796519e00781440b5ad8b2e2
)

mkdir -p "$DEST"
for file in "${!SHA256[@]}"; do
  echo "Descargando $file…"
  curl -fsSL --retry 3 -o "$DEST/$file.tmp" "$BASE/$file"
  actual="$(sha256sum "$DEST/$file.tmp" | cut -d' ' -f1)"
  if [[ "$actual" != "${SHA256[$file]}" ]]; then
    rm -f "$DEST/$file.tmp"
    echo "ERROR: checksum incorrecto en $file" >&2
    exit 1
  fi
  mv "$DEST/$file.tmp" "$DEST/$file"
done
chmod 644 "$DEST"/*.se1
echo "Archivos verificados en $DEST"
