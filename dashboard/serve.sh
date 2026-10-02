#!/usr/bin/env bash
# Painel BTC on-chain (somente dados públicos). Gera market.json e serve em 127.0.0.1.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8765}"
cd "$DIR"
python3 "$DIR/fetch_market.py" || true
echo "abra http://127.0.0.1:$PORT/btc-onchain.html"
exec python3 -m http.server "$PORT" --bind 127.0.0.1
