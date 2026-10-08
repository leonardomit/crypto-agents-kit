#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="${SCOUT_OUT_DIR:-$HERE/out}"
export SCOUT_OUT_DIR="$DIR"
mkdir -p "$DIR"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
bash "$HERE/defi-trader-scan-pools.sh" 15 1000000 > "$DIR/pools.json" 2>"$DIR/pools.err" || true
# 2026-10-02: usa o MESMO script do job "DeFi Scout" (defi_scout.py) p/ latest.md ficar consistente.
# --no-alert: grava latest.md/history, mas não mexe em state.json nem imprime alerta (o alerta é do job).
# Fallback: digest antigo se o script compartilhado falhar.
DEFI_SCOUT_OUT_DIR="$DIR" python3 "$HERE/defi_scout.py" --no-alert || python3 "$HERE/make_digest.py"
