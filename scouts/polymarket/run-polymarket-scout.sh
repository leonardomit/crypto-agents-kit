#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="${SCOUT_OUT_DIR:-$HERE/out}"
export SCOUT_OUT_DIR="$DIR"
mkdir -p "$DIR"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
bash "$HERE/polymarket-scout-markets.sh" 50 > "$DIR/markets.json" 2>"$DIR/markets.err" || true
python3 "$HERE/make_polymarket_digest.py"
