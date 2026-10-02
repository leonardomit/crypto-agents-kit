# pumpfun-paper — scanner pump.fun (PAPER TRADING)

**Simulação apenas.** Sem carteira, sem chaves, sem ordens reais. Só HTTP público.

## Arquivos
- `pumpfun_paper.py` — 1 ciclo: atualiza posições abertas (preço DexScreener) → aplica saídas → procura entradas.
- `run-pumpfun.sh` — wrapper do cron (lock via `mkdir .pumpfun.lock`, log em `logs/pumpfun-YYYYMMDD.log`, timeout 12 min no python).
- `pumpfun_daily.py` — resumo diário (`pumpfun-daily-YYYYMMDD.md` + `pumpfun-daily-latest.md`); `--final` gera `pumpfun-final-report.md`.
- `pumpfun-state.json` (estado), `pumpfun-paper.jsonl` (eventos: signal/entry/partial_exit/exit), `pumpfun-candidates.jsonl` (rejeitados/aprovados do dia; rotação diária para `logs/candidates-archive/`, guarda 10 dias), `logs/runs.jsonl` (1 linha por ciclo com saúde das fontes).

## Fontes
pump.fun `frontend-api-v3.pump.fun/coins` (complete=true, sort=created_timestamp; + sort=last_trade_timestamp), DexScreener (`tokens/v1/solana/<até 30>`, token-profiles/latest, token-boosts/latest), RugCheck `/v1/tokens/<mint>/report`, Jupiter `lite-api.jup.ag/swap/v1/quote`, Solana RPC público (fallback de authorities / maiores holders — `getTokenLargestAccounts` costuma dar 429).
Endpoints que NÃO funcionaram em 01/10/2026: `/coins/king-of-the-hill` (404), `advanced-api-v2.pump.fun/coins/graduated` (530).

## Filtros (todos obrigatórios)
1. Idade < 6h (created_timestamp pump.fun; senão pairCreatedAt).
2. Graduado (par pumpswap/raydium/meteora/orca na DexScreener) ou curva >= 85%.
3. Liquidez do par mais líquido >= US$20k.
4. Volume e txns subindo — **v2 (desde o evento `rules_change` de 02/10/2026)**: a 1ª observação de um token NUNCA entra; o snapshot é gravado e o token precisa passar num ciclo posterior (mín. 2 observações) com: h1 vol e h1 txns >= +10% vs snapshot de 15–30 min atrás (ou o mais próximo dentro de 10–40 min) **e** ritmo m5 >= 1,0× a média de 5 min da última hora (vol e txns) com >= 10 txns em m5.
   _(v1, 01/10/2026: sem snapshot bastava ritmo m5 >= 1,2× — removido.)_
4b. **Veto de liquidez (v2):** rejeita se a liquidez caiu >= 20% vs o mesmo snapshot (15–30 min, ou 10–40 min).
5. RugCheck: mintAuthority e freezeAuthority nulos; `rugged=false`; nenhum risco nível `danger` (inclui histórico de rug do criador, alta concentração etc.); `score_normalised <= 60`.
6. Top10 holders < 30% excluindo pool/curva/burn/AMM/locker (topHolders do RugCheck; criador conta).
Máx. 10 consultas RugCheck por ciclo (mais líquidos primeiro). Mint já operada não reentra.

## Regras paper
Entrada US$4 no preço DexScreener do sinal; slippage = max(priceImpact Jupiter USDC→token US$4, 0,5%) — quantidade = 4×(1−slip)/preço. Máx. 2 abertas.
Saídas (checadas a cada ciclo, no preço atual): 50% em >= +50%; restante em >= +100%; stop: preço <= −30% vende todo o restante; time stop 4h. Saída aplica slippage = max(priceImpact Jupiter token→USDC p/ a quantidade, 0,5%) (fallback: slippage da entrada).
**Saída por liquidez (v2):** posição aberta cuja liquidez (par mais líquido, DexScreener) cair >= 20% entre um ciclo e o seguinte é vendida inteira na hora (`liq_drop`) no preço atual, com slippage cotado na Jupiter.
Snapshots: histórico por mint dos últimos 60 min (não grava se o último tem < 8 min).
Sem novas entradas a partir de `PUMPFUN_CUTOFF_NEW` (opcional; continua fechando abertas).

## Histórico de regras
- v1 — 01/10/2026 18:55 BRT (início).
- v2 — evento `rules_change` em `pumpfun-paper.jsonl` (≈02/10/2026 00:0x BRT): mín. 2 observações, ritmo m5 >= 1,0× como requisito adicional, veto de entrada e saída imediata por queda de liquidez >= 20%. Relatórios mostram "Antes vs depois".
