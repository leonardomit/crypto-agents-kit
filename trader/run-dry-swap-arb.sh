#!/usr/bin/env bash
# Dry-run: cotação Uniswap v3 ETH → USDC na Arbitrum (sem broadcast).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export DRY_RUN=1
PY="${PYTHON:-python3}"
: "${DEFI_WALLET_ADDRESS:?defina DEFI_WALLET_ADDRESS (ver .env.example)}"
exec "$PY" "$HERE/swap.py" --chain arbitrum --amount-usd "${AMOUNT_USD:-3}" --src eth --dst usdc "$@"
