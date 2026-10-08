# Scouts (alerta only)

Scripts HTTP públicos — **sem wallet, sem chave, sem trade**. Cada um escreve em `scouts/<nome>/out/`
(override: `SCOUT_OUT_DIR`). Um agente LLM lê o `latest.md` depois e decide se avisa (ver `agents/`).

| Pasta | Fonte | Entrada | Saída |
|---|---|---|---|
| `defi/` | DefiLlama yields + Uni v3 slot0 | `run-scout.sh` → `defi_scout.py --no-alert` (Arb/Base/OP/BNB; Eth só benchmark) · `defillama_lending_scout.py` (lending stablecoin blue-chip) | `latest.md`, `pools.json`, `lending-latest.{md,json}` |
| `meme/` | DexScreener | `run-meme-scout.sh` (Sol/Base/Arb/Eth/BSC; confirmação por 2º pool ≥US$100k, pool de execução ≥US$100k, filtro de máxima 1h p/ long; `--replay`) | `latest.md`, `history/` |
| `polymarket/` | Gamma API | `run-polymarket-scout.sh` | `latest.md`, `markets.json` |
| `pumpfun-paper/` | pump.fun, DexScreener, RugCheck, Jupiter quote | `run-pumpfun.sh` (1 ciclo, cron 15 min; `--positions-only` a cada 5 min 24h) · `pumpfun_daily.py` | `pumpfun-*.md/jsonl`, `logs/` — **paper trading (simulação)** |
| `auditoria-rotinas/` | inventário local de rotinas | `run-auditoria.sh` (segunda 09:00) | `latest.md`, `proposed-last-week.json` — só proposta |
| `onchain-btc/` | CoinGecko, Alternative.me, DefiLlama, mempool.space | `run-onchain.sh` | `snapshot.json`, `latest.md` |

Dependências: `bash`, `curl`, `jq`, `python3` (stdlib). O arquivo `AGENTS.md` em cada pasta é o prompt
curto para um agente que roda no mesmo host (ex.: Hermes Agent) enriquecer o digest.
