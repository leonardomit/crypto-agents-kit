#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="${SCOUT_OUT_DIR:-$HERE/out}"
export SCOUT_OUT_DIR="$DIR"
mkdir -p "$DIR"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
bash "$HERE/defi-trader-scan-pools.sh" 15 1000000 > "$DIR/pools.json" 2>"$DIR/pools.err" || true
python3 "$HERE/make_digest.py"
