#!/bin/bash
# Auditoria semanal de rotinas -> proposta de migração para script/API/MCP (nunca aplica nada).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="${SCOUT_OUT_DIR:-$HERE/out}"
export SCOUT_OUT_DIR="$DIR"
mkdir -p "$DIR"
# O inventário é exportado pelo orquestrador (ex.: scp) antes da rodada de segunda; usa o último se existir.
if [ ! -f "$DIR/routines-inventory.json" ]; then
  echo "Sem inventário — o orquestrador precisa exportar routines-inventory.json para $DIR" > "$DIR/latest.md"
  exit 0
fi
python3 "$HERE/make_auditoria_digest.py"
