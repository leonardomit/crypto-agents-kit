#!/bin/bash
# Wrapper do scanner pump.fun PAPER TRADING (simulação; nenhuma ordem real).
# Lock via mkdir (macOS não tem flock) para evitar ciclos sobrepostos.
# v3 (2026-10-03): modo --positions-only (cron */5): só gerencia posições abertas.
#   - pula os minutos da varredura completa (:00/:15/:30/:45 das 9h-22h e 23:00) — ela já atualiza as posições;
#   - se o lock estiver ocupado, sai calado (a varredura completa está rodando);
#   - sem posição aberta, o python sai na hora (sem rede, sem log).
#   A varredura completa espera até 90s se um ciclo de posições estiver segurando o lock.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="${SCOUT_OUT_DIR:-$HERE/out}"
export SCOUT_OUT_DIR="$DIR"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
mkdir -p "$DIR/logs"
LOG="$DIR/logs/pumpfun-$(date +%Y%m%d).log"
LOCK="$DIR/.pumpfun.lock"
MODE=full
for a in "$@"; do [ "$a" = "--positions-only" ] && MODE=pos; done
if [ "$MODE" = pos ]; then
  H=$((10#$(date +%H))); M=$((10#$(date +%M)))
  if { [ $H -ge 9 ] && [ $H -le 22 ] && [ $((M % 15)) -eq 0 ]; } || { [ $H -eq 23 ] && [ $M -eq 0 ]; }; then
    exit 0
  fi
fi
take_lock() {
  if mkdir "$LOCK" 2>/dev/null; then return 0; fi
  pid=$(cat "$LOCK/pid" 2>/dev/null || echo "")
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then return 1; fi
  echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] lock órfão removido (pid ${pid:-?})" >>"$LOG"
  rm -rf "$LOCK"; mkdir "$LOCK" 2>/dev/null
}
if ! take_lock; then
  if [ "$MODE" = pos ]; then exit 0; fi
  ok=0
  for i in $(seq 1 18); do sleep 5; if take_lock; then ok=1; break; fi; done
  if [ $ok -ne 1 ]; then
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] outro ciclo em andamento (pid $(cat "$LOCK/pid" 2>/dev/null)); pulando" >>"$LOG"; exit 0
  fi
fi
echo $$ >"$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT
# timeout de segurança: o próprio python aborta (12 min varredura / 4 min posições), cron é a cada 15/5
python3 "$HERE/pumpfun_paper.py" "$@" >>"$LOG" 2>&1
rc=$?
# mantém só 15 dias de logs diários
find "$DIR/logs" -name 'pumpfun-2*.log' -mtime +15 -delete 2>/dev/null
exit $rc
