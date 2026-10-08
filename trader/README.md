# Trader — Uniswap v3 (EVM) + Jupiter (Solana)

Scripts que **executam** trades. Leia [`RULES.md`](RULES.md) antes. Default `DRY_RUN=1`.

| Script | O quê |
|---|---|
| `lib_caps.py` | Caps de risco, RPCs, carregamento de chave (env / `SECRETS_FILE`), `assert_live_to` |
| `tokens.py` | Endereços públicos (WETH/USDC, QuoterV2, SwapRouter) por chain + denylist |
| `validate-wallet.py` | Deriva o endereço da chave e checa saldo (não imprime a chave) |
| `swap.py` | Swap single-hop Uniswap v3 (quote + exec opcional) |
| `swap_v3_path.py` | Swap multi-hop Uniswap v3 na Arbitrum (`--path usdc:500:weth:3000:<token>`) com simulação e approve exato. **ARB cadastrado** (08/10) |
| `lp_enter.py` | Mint de LP concentrada Uni v3 (WETH/USDC) com range em ticks |
| `lp_exit.py` | Remove liquidez (parcial/total), collect e burn opcional |
| `aave_supply.py` | Supply USDC na Aave v3 (Pool via AddressesProvider) |
| `report-positions.py` | Relatório read-only: saldos + LPs (in-range, ticks, USD) + APY DefiLlama |
| `sol_swap.py` | Swap SOL↔SPL via Jupiter com allowlist de programas |
| `lp_oor_watch.py` | **Novo.** Monitor de LP fora da faixa: lê a pool a cada 1 min; após 2 leituras seguidas OOR sai 100% via `lp_exit.py` (mín. 98% do esperado, sem swap). Sem `--execute` só alerta |
| `bridge_exec.py` | **Novo.** Bridge via Relay (Ethereum→Arbitrum ETH, POL de gas na Polygon, Polygon USDT→Arbitrum USDC). Dry-run default; allowlist fixa de contrato/spender + bytecode, destino/recebedor/mín. de saída, orderId recomputado (`relay_verify/`), approve exato, só 1 passo, teto de custo por rota |
| `relay_verify/` | **Novo.** `order_id.js` (SDK oficial `@relay-protocol/settlement-sdk`) usado pelo `bridge_exec.py`. `cd relay_verify && npm install` |
| `bridge_quotes.py` | **Novo (versão Trader).** Cotações Relay/Across/LI.FI para as pernas Arb→Base/BNB e gas; read-only, usa `DEFI_WALLET_ADDRESS`/`SOLANA_WALLET_ADDRESS` só como destinatário da cotação |
| `lib_chains.py` · `chains.json` · `build_chains_registry.py` | **Novo.** Registro multichain verificado (Base/BNB/Arbitrum: tokens, Uniswap/Aerodrome/PancakeSwap, Aave, Venus) com fonte por endereço, RPC com failover, `assert_live_to_reg`, approve exato |
| `swap_multi.py` · `aave_supply_multi.py` · `run-dry-multichain.sh` | **Novo.** Swap (Base Uniswap/Aerodrome, BNB PancakeSwap) e supply (Aave Base/BNB, Venus) com simulação por state override |
| `run-dry-*.sh` | Wrappers de dry-run |

## Uso rápido

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r ../requirements.txt
set -a; . ../.env; set +a

python validate-wallet.py
python report-positions.py
./run-dry-swap-arb.sh                    # cotação ETH→USDC, sem broadcast
./run-dry-lp-arb.sh --tick-range 200     # simula mint de LP
./run-dry-sol-swap.sh                    # cotação Jupiter SOL→USDC

# live (somente depois de revisar o dry-run):
DRY_RUN=0 python swap.py --chain arbitrum --amount-usd 5 --src eth --dst usdc --execute
DRY_RUN=0 python lp_exit.py --token-id <ID> --pct 100 --execute

# novos (08/10/2026)
python lp_oor_watch.py --token-id <ID>                       # só alerta se sair da faixa
python lp_oor_watch.py --token-id <ID> --execute             # saída OOR automática
python bridge_exec.py --route eth_to_arb --amount <wei>      # dry-run (simula e calcula custo)
python swap_v3_path.py --path usdc:500:weth:500:arb --amount-in 5   # dry-run USDC→WETH→ARB
bash run-dry-multichain.sh                                   # Base/BNB dry-runs
```

Estado local (`wallet.address`, `wallet.status.json`, journal) fica em `$DEFI_STATE_DIR` (default `trader/state/`, gitignored).
