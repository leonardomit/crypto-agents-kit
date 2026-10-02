# Trader — Uniswap v3 (EVM) + Jupiter (Solana)

Scripts que **executam** trades. Leia [`RULES.md`](RULES.md) antes. Default `DRY_RUN=1`.

| Script | O quê |
|---|---|
| `lib_caps.py` | Caps de risco, RPCs, carregamento de chave (env / `SECRETS_FILE`), `assert_live_to` |
| `tokens.py` | Endereços públicos (WETH/USDC, QuoterV2, SwapRouter) por chain + denylist |
| `validate-wallet.py` | Deriva o endereço da chave e checa saldo (não imprime a chave) |
| `swap.py` | Swap single-hop Uniswap v3 (quote + exec opcional) |
| `swap_v3_path.py` | Swap multi-hop Uniswap v3 na Arbitrum (`--path usdc:500:weth:3000:<token>`) com simulação e approve exato |
| `lp_enter.py` | Mint de LP concentrada Uni v3 (WETH/USDC) com range em ticks |
| `lp_exit.py` | Remove liquidez (parcial/total), collect e burn opcional |
| `aave_supply.py` | Supply USDC na Aave v3 (Pool via AddressesProvider) |
| `report-positions.py` | Relatório read-only: saldos + LPs (in-range, ticks, USD) + APY DefiLlama |
| `sol_swap.py` | Swap SOL↔SPL via Jupiter com allowlist de programas |
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
```

Estado local (`wallet.address`, `wallet.status.json`, journal) fica em `$DEFI_STATE_DIR` (default `trader/state/`, gitignored).
