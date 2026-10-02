#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="${SCOUT_OUT_DIR:-$HERE/out}"
export SCOUT_OUT_DIR="$DIR"
mkdir -p "$DIR/history"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
bash "$HERE/meme-scan.sh" > "$DIR/raw.json" 2>"$DIR/scan.err" || true
python3 "$HERE/make_meme_digest.py"
