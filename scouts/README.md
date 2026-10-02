# Scouts (alerta only)

Scripts HTTP públicos — **sem wallet, sem chave, sem trade**. Cada um escreve em `scouts/<nome>/out/`
(override: `SCOUT_OUT_DIR`). Um agente LLM lê o `latest.md` depois e decide se avisa (ver `agents/`).

| Pasta | Fonte | Entrada | Saída |
|---|---|---|---|
| `defi/` | DefiLlama yields | `run-scout.sh` (top yields Arb/Base/OP/Eth) · `defillama_lending_scout.py` (lending stablecoin blue-chip) | `latest.md`, `pools.json`, `lending-latest.{md,json}` |
| `meme/` | DexScreener | `run-meme-scout.sh` (Sol/Base/Arb/Eth/BSC, confirmação por 2º pool) | `latest.md`, `history/` |
| `polymarket/` | Gamma API | `run-polymarket-scout.sh` | `latest.md`, `markets.json` |
| `pumpfun-paper/` | pump.fun, DexScreener, RugCheck, Jupiter quote | `run-pumpfun.sh` (1 ciclo, cron 15 min) · `pumpfun_daily.py` | `pumpfun-*.md/jsonl`, `logs/` — **paper trading (simulação)** |
| `onchain-btc/` | CoinGecko, Alternative.me, DefiLlama, mempool.space | `run-onchain.sh` | `snapshot.json`, `latest.md` |

Dependências: `bash`, `curl`, `jq`, `python3` (stdlib). O arquivo `AGENTS.md` em cada pasta é o prompt
curto para um agente que roda no mesmo host (ex.: Hermes Agent) enriquecer o digest.
