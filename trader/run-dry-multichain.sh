#!/usr/bin/env bash
# Dry-runs Base/BNB (read-only: eth_call/estimateGas com state override; nada assinado)
set -euo pipefail
cd "$(dirname "$0")"; P="${PYTHON:-python3}"; R="${DEFI_STATE_DIR:-state}/reports/multichain-$(date +%Y%m%d-%H%M)"; mkdir -p "$R"
export DRY_RUN=1
$P build_chains_registry.py > "$R/registry-verify.txt"
$P swap_multi.py --chain base --dex uniswap   --src usdc --dst weth --amount-in 10 > "$R/base-uniswap.json"
$P swap_multi.py --chain base --dex aerodrome --src usdc --dst weth --amount-in 10 > "$R/base-aerodrome.json"
$P swap_multi.py --chain bnb  --dex pancake   --src usdt --dst wbnb --amount-in 10 > "$R/bnb-pancake.json"
$P aave_supply_multi.py --chain base --asset usdc --amount 10 > "$R/base-aave.json"
$P aave_supply_multi.py --chain bnb  --asset usdt --amount 10 > "$R/bnb-aave.json"
$P aave_supply_multi.py --chain bnb  --asset usdt --amount 10 --protocol venus > "$R/bnb-venus.json"
$P bridge_quotes.py "$R/bridge-quotes.json"
echo "ok -> $R"
