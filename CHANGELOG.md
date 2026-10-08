# Changelog

## 2026-10-08

Tudo que mudou nos crons do Hermes e nos scripts dos agentes desde o commit inicial (02/10/2026).

### Hermes / crons
- **Novo `hermes/`**: `crontab.hermes.example` (linhas cripto como rodam no Hermes), `jobs.crypto.example.json`
  (extrato **redigido** dos jobs DeFi Scout, On-Chain BTC Report, Polymarket Scout Enrich e Auditoria de Rotinas Enrich:
  só agenda e prompt) e `README.md` explicando a divisão cron (script, custo zero) + job do Hermes (LLM/alerta).
- **Novo `hermes/vault-sync/sync_vault.py`**: espelha os resultados dos scouts no Obsidian (nota diária por cron,
  `latest`, resumos e relatório final do pump.fun), com dedupe por hash e máscara de segredos. Cron `3,18,33,48 8-23 * * *`.
  Configurável por env (`OBSIDIAN_VAULT`, `VAULT_FOLDER`, `VAULT_SYNC_LAYOUT=kit|hermes`).
- Agendas novas: DeFi e Polymarket a cada 45 min (9–17h + 18h, todo dia); pump.fun com checagem de posições a cada 5 min.

### DeFi Scout
- **Novo `scouts/defi/defi_scout.py`**: script compartilhado entre o job do Hermes (alerta via stdout só com 2–3 setups
  A/B novos, por fingerprint) e o cron (`--no-alert`, não consome o alerta). Redes de setup Arbitrum, Base, OP e BNB
  Chain (Ethereum só benchmark); universo extra Base/BNB (Aave, Venus, Aerodrome, PancakeSwap) com TVL ≥ US$5M;
  slot0 Uni v3, tendência ETH/SOL e ΔTVL por rede.
- `run-scout.sh` passa a chamar `defi_scout.py --no-alert` (fallback: `make_digest.py`).

### Meme Scout
- Confirmação cruzada mais rígida (versão c, 02/10): pool confirmador com liquidez ≥ US$100k, ≥ metade da força e preço
  a ≤ 3%; pool de execução (o mais líquido do token) ≥ US$100k e o link aponta para ele.
- Filtro de máxima 1h só para long (rejeita se o preço já está > 5% abaixo da máxima estimada); fade/short ganha rótulo
  informativo "Short disponível" (perp líquido na Hyperliquid), sem mudar ACTIONABLE.
- `meme-scan.sh` grava `change5m`, `change6h`, `volume1h`, `txns1h`; raw salvo por execução em `out/history/raw-*.json`;
  `make_meme_digest.py --replay <raw>` reprocessa sem gravar.

### pump.fun (paper trading)
- **Regras v3 (03/10)**: modo `--positions-only` (cron a cada 5 min, 24h; sai sem rede se não há posição; pula os minutos da
  varredura completa e respeita o lock) e exigência de LP ≥ 90% travado/queimado no pool de execução (RugCheck).
- Mantidos da v2: entrada paper de US$4, mín. 2 observações, veto de entrada e saída imediata por queda de liquidez ≥ 20%.
- `pumpfun_daily.py` (resumo 23:05) compara v1/v2/v3 por versão vigente na entrada e conta as checagens de 5 min.

### Polymarket
- **Novo `skills/polymarket-scout/SKILL.md`** (skill do enrich no Hermes): fontes que funcionam em cron, armadilhas
  da Gamma API e regras de edge.
- Regras de push documentadas em `agents/scout-push-routines.md`: push só com |edge| ≥ 8 pp; mercado novo também precisa
  de edge estimado ≥ 8 pp; a data da fonte tem que cair dentro da janela do mercado.

### On-chain / auditoria
- Job Hermes "On-Chain BTC Report" (`32 8,18 * * 1-5`) documentado em `hermes/` (não inventa MVRV/NUPL/SOPR).
- **Novo `scouts/auditoria-rotinas/`**: `make_auditoria_digest.py` + `run-auditoria.sh` + `AGENTS.md` — classifica rotinas
  e propõe migração para script/API/MCP (só proposta; dedupe semanal). Inventário real fica fora do git.

### Trader
- **Novo `trader/bridge_exec.py`** + `trader/relay_verify/`: bridge via Relay (Ethereum→Arbitrum ETH, POL de gas na Polygon,
  Polygon USDT→Arbitrum USDC). Dry-run por padrão; contrato e spender numa allowlist fixa no código + bytecode; destino
  42161, recebedor = sua carteira e mínimo de saída conferidos; orderId recomputado com o SDK oficial; approve exato;
  só 1 passo de depósito; teto de custo por rota; trava se o monitor de LP disparou há < 15 min. Usado em produção em
  08/10 com teste de ~US$2 por rota antes do valor cheio.
- **Novo `trader/lp_oor_watch.py`**: monitor de LP fora da faixa (leitura a cada 1 min; 2 leituras seguidas OOR → `lp_exit.py`
  100% com mínimo de 98% do esperado, sem swap). Sem `--execute` só alerta.
- **ARB cadastrado** em `tokens.py` e `swap_v3_path.py` (bytecode/symbol/decimals conferidos; pool WETH/ARB 0,05%).
- **Multichain Base/BNB**: `lib_chains.py`, `chains.json` (registro verificado com fonte por endereço),
  `build_chains_registry.py`, `swap_multi.py` (Uniswap/Aerodrome/PancakeSwap), `aave_supply_multi.py` (Aave Base/BNB, Venus),
  `run-dry-multichain.sh`.
- `trader/bridge_quotes.py`: cotações Relay/Across/LI.FI das pernas Arb→Base/BNB e de gas (read-only).
- `RULES.md`: regras de bridge, saída OOR e multichain.

### Docs
- README, `scouts/README.md`, `trader/README.md`, `skills/README.md`, `crontab.example`, `.env.example` e o prompt do Trader
  atualizados. `.gitignore` passa a barrar journal de posições, `reports/`, snapshots `*.json`, arquivos de carteira,
  segredos, `node_modules/`.
