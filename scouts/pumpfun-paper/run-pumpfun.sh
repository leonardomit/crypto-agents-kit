#!/bin/bash
# Wrapper do scanner pump.fun PAPER TRADING (simulação; nenhuma ordem real).
# Lock via mkdir (macOS não tem flock) para evitar ciclos sobrepostos.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="${SCOUT_OUT_DIR:-$HERE/out}"
export SCOUT_OUT_DIR="$DIR"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
mkdir -p "$DIR/logs"
LOG="$DIR/logs/pumpfun-$(date +%Y%m%d).log"
LOCK="$DIR/.pumpfun.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  pid=$(cat "$LOCK/pid" 2>/dev/null || echo "")
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] outro ciclo em andamento (pid $pid); pulando" >>"$LOG"; exit 0
  fi
  echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] lock órfão removido (pid ${pid:-?})" >>"$LOG"
  rm -rf "$LOCK"; mkdir "$LOCK" || exit 1
fi
echo $$ >"$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT
# timeout de segurança: o próprio python aborta em 12 min (signal.alarm), cron é a cada 15
python3 "$HERE/pumpfun_paper.py" "$@" >>"$LOG" 2>&1
rc=$?
# mantém só 15 dias de logs diários
find "$DIR/logs" -name 'pumpfun-2*.log' -mtime +15 -delete 2>/dev/null
exit $rc
