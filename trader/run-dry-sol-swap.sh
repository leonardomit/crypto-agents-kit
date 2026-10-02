#!/usr/bin/env bash
# Dry-run: cotação SOL → USDC via Jupiter (sem broadcast).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export DRY_RUN="${DRY_RUN:-1}"
PY="${PYTHON:-python3}"
exec "$PY" "$HERE/sol_swap.py" \
  --input-mint SOL \
  --output-mint USDC \
  --amount-usd "${AMOUNT_USD:-1}" \
  --slippage-bps "${SLIPPAGE_BPS:-100}" \
  "$@"
