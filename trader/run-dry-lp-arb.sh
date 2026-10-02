#!/usr/bin/env bash
# Dry-run: mint de LP Uniswap v3 WETH/USDC 0.05% na Arbitrum (sem broadcast).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export DRY_RUN=1
PY="${PYTHON:-python3}"
: "${DEFI_WALLET_ADDRESS:?defina DEFI_WALLET_ADDRESS (ver .env.example)}"
exec "$PY" "$HERE/lp_enter.py" --chain arbitrum --amount-usd "${AMOUNT_USD:-5}" --fee 500 "$@"
