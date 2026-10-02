#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="${SCOUT_OUT_DIR:-$HERE/out}"
export SCOUT_OUT_DIR="$DIR"
mkdir -p "$DIR"
python3 "$HERE/fetch_onchain_public.py"
# Opcional: enriquecer com um agente LLM CLI (ex.: Hermes Agent `hermes -z "<prompt>"`).
# Defina LLM_CLI com o comando; falha é ignorada (o esqueleto latest.md já existe).
if [ -n "${LLM_CLI:-}" ]; then
  timeout 90 $LLM_CLI "Leia $DIR/snapshot.json e atualize $DIR/latest.md com resumo PT-BR: 3 frases decisão, score /10, sinal entrada/saída. Não invente métricas; use Dado atual não confirmado. ≤25 linhas." >>"$DIR/llm-enrich.log" 2>&1 || true
fi
