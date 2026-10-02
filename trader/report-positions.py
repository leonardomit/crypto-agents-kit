#!/usr/bin/env python3
"""Relatório read-only de posições Uniswap v3 (Arbitrum) + saldos. Imprime JSON.

Config via env:
  DEFI_WALLET_ADDRESS  carteira EVM (pública) — obrigatório
  LP_TOKEN_IDS         ids das posições NFT separados por vírgula (opcional;
                       se vazio, enumera via NonfungiblePositionManager.tokenOfOwnerByIndex)
  RPC_ARBITRUM         RPC (default público)
  LP_POOL_ADDRESS      pool Uni v3 (default WETH/USDC 0.05% Arbitrum)
  DEFILLAMA_POOL_ID    id do pool no yields.llama.fi (default WETH-USDC 0.05% Arb)
"""
from __future__ import annotations
import json
import os
import urllib.request
from web3 import Web3

RPC = os.environ.get("RPC_ARBITRUM", "https://arb1.arbitrum.io/rpc")
NPM = "0xC36442b4a4522E871399CD717aBDD847Ab11FE88"
POOL = os.environ.get("LP_POOL_ADDRESS", "0xC6962004f452bE9203591991D15f6b388e09E8D0")  # Uni v3 WETH/USDC 0.05% Arb (público)
WALLET = os.environ.get("DEFI_WALLET_ADDRESS", "").strip()
WETH = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
TOKEN_IDS = [int(x) for x in os.environ.get("LP_TOKEN_IDS", "").split(",") if x.strip()]
LLAMA_POOL = os.environ.get("DEFILLAMA_POOL_ID", "a14bd201-764c-40a5-86b8-2928b2461232")

NPM_ABI = [
  {"inputs":[{"name":"tokenId","type":"uint256"}],"name":"positions","outputs":[
    {"name":"nonce","type":"uint96"},{"name":"operator","type":"address"},
    {"name":"token0","type":"address"},{"name":"token1","type":"address"},
    {"name":"fee","type":"uint24"},{"name":"tickLower","type":"int24"},
    {"name":"tickUpper","type":"int24"},{"name":"liquidity","type":"uint128"},
    {"name":"feeGrowthInside0LastX128","type":"uint256"},
    {"name":"feeGrowthInside1LastX128","type":"uint256"},
    {"name":"tokensOwed0","type":"uint128"},{"name":"tokensOwed1","type":"uint128"}
  ],"stateMutability":"view","type":"function"},
  {"inputs":[{"name":"tokenId","type":"uint256"}],"name":"ownerOf",
   "outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
  {"inputs":[{"name":"owner","type":"address"}],"name":"balanceOf",
   "outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
  {"inputs":[{"name":"owner","type":"address"},{"name":"index","type":"uint256"}],"name":"tokenOfOwnerByIndex",
   "outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
]
POOL_ABI = [
  {"inputs":[],"name":"slot0","outputs":[
    {"name":"sqrtPriceX96","type":"uint160"},{"name":"tick","type":"int24"},
    {"name":"observationIndex","type":"uint16"},{"name":"observationCardinality","type":"uint16"},
    {"name":"observationCardinalityNext","type":"uint16"},{"name":"feeProtocol","type":"uint8"},
    {"name":"unlocked","type":"bool"}],"stateMutability":"view","type":"function"},
  {"inputs":[],"name":"liquidity","outputs":[{"name":"","type":"uint128"}],
   "stateMutability":"view","type":"function"},
  {"inputs":[],"name":"token0","outputs":[{"name":"","type":"address"}],
   "stateMutability":"view","type":"function"},
  {"inputs":[],"name":"token1","outputs":[{"name":"","type":"address"}],
   "stateMutability":"view","type":"function"},
  {"inputs":[],"name":"fee","outputs":[{"name":"","type":"uint24"}],
   "stateMutability":"view","type":"function"},
]
ERC20_ABI = [
  {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
  {"inputs":[],"name":"decimals","outputs":[{"type":"uint8"}],"stateMutability":"view","type":"function"},
  {"inputs":[],"name":"symbol","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
]

def amounts_from_liquidity(liquidity, sqrt_price_x96, tick_lower, tick_upper, tick_current, dec0, dec1):
    if liquidity == 0:
        return 0.0, 0.0
    L = float(liquidity)
    sqrtP = float(sqrt_price_x96) / (2 ** 96)
    sqrtA = 1.0001 ** (tick_lower / 2.0)
    sqrtB = 1.0001 ** (tick_upper / 2.0)
    if tick_current < tick_lower:
        a0 = L * (sqrtB - sqrtA) / (sqrtA * sqrtB); a1 = 0.0
    elif tick_current >= tick_upper:
        a0 = 0.0; a1 = L * (sqrtB - sqrtA)
    else:
        a0 = L * (sqrtB - sqrtP) / (sqrtP * sqrtB); a1 = L * (sqrtP - sqrtA)
    return a0 / (10 ** dec0), a1 / (10 ** dec1)

def fetch_llama():
    url = "https://yields.llama.fi/pools"
    with urllib.request.urlopen(url, timeout=90) as r:
        data = json.loads(r.read().decode())
    matches = []
    for p in data.get("data", []):
        if (p.get("chain") or "").lower() != "arbitrum":
            continue
        if (p.get("project") or "").lower() != "uniswap-v3":
            continue
        sym = (p.get("symbol") or "").upper().replace(" ", "")
        if "WETH" not in sym or "USDC" not in sym:
            continue
        matches.append({
            "pool": p.get("pool"), "symbol": p.get("symbol"),
            "poolMeta": p.get("poolMeta"), "project": p.get("project"),
            "chain": p.get("chain"), "apy": p.get("apy"),
            "apyBase": p.get("apyBase"), "apyMean30d": p.get("apyMean30d"),
            "tvlUsd": p.get("tvlUsd"), "volumeUsd1d": p.get("volumeUsd1d"),
            "volumeUsd7d": p.get("volumeUsd7d"), "ilRisk": p.get("ilRisk"),
            "apyPct7D": p.get("apyPct7D"),
        })
    def prefer_key(m):
        meta = (m.get("poolMeta") or "").strip()
        prefer = 0 if meta in ("0.05%", "0.05") else 1
        return (prefer, -(m.get("tvlUsd") or 0))
    matches.sort(key=prefer_key)
    preferred = matches[0] if matches else None
    return {"preferred": preferred, "all_matches": matches, "count": len(matches)}

def proj(capital, apy):
    if capital <= 0 or apy is None:
        return {"day": 0.0, "week": 0.0, "month": 0.0}
    y = capital * (apy / 100.0)
    return {"day": y / 365.0, "week": y / 52.0, "month": y / 12.0}

def main():
    if not WALLET:
        raise SystemExit("DEFI_WALLET_ADDRESS ausente (ver .env.example)")
    w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
    assert w3.is_connected(), "RPC fail"
    wallet = Web3.to_checksum_address(WALLET)
    block = w3.eth.block_number
    eth_wei = w3.eth.get_balance(wallet)
    eth = float(Web3.from_wei(eth_wei, "ether"))
    weth_c = w3.eth.contract(address=Web3.to_checksum_address(WETH), abi=ERC20_ABI)
    usdc_c = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_ABI)
    weth_raw = weth_c.functions.balanceOf(wallet).call()
    usdc_raw = usdc_c.functions.balanceOf(wallet).call()
    weth = weth_raw / (10 ** weth_c.functions.decimals().call())
    usdc = usdc_raw / (10 ** usdc_c.functions.decimals().call())
    npm = w3.eth.contract(address=Web3.to_checksum_address(NPM), abi=NPM_ABI)
    pool = w3.eth.contract(address=Web3.to_checksum_address(POOL), abi=POOL_ABI)
    slot0 = pool.functions.slot0().call()
    sqrt_price_x96 = slot0[0]
    tick_current = slot0[1]
    pool_liq = pool.functions.liquidity().call()
    t0a = pool.functions.token0().call()
    t1a = pool.functions.token1().call()
    fee = pool.functions.fee().call()
    t0 = w3.eth.contract(address=t0a, abi=ERC20_ABI)
    t1 = w3.eth.contract(address=t1a, abi=ERC20_ABI)
    dec0, dec1 = t0.functions.decimals().call(), t1.functions.decimals().call()
    sym0, sym1 = t0.functions.symbol().call(), t1.functions.symbol().call()
    price_raw = (float(sqrt_price_x96) / (2 ** 96)) ** 2
    price_t1_per_t0 = price_raw * (10 ** (dec0 - dec1))
    eth_usd = price_t1_per_t0 if sym0 in ("WETH", "ETH") else (1.0 / price_t1_per_t0)

    token_ids = list(TOKEN_IDS)
    if not token_ids:
        n = npm.functions.balanceOf(wallet).call()
        token_ids = [int(npm.functions.tokenOfOwnerByIndex(wallet, i).call()) for i in range(n)]
    positions = []
    for tid in token_ids:
        try:
            owner = npm.functions.ownerOf(tid).call()
        except Exception as e:
            positions.append({"tokenId": tid, "error": str(e)})
            continue
        pos = npm.functions.positions(tid).call()
        tick_lower, tick_upper = pos[5], pos[6]
        liquidity = pos[7]
        owed0, owed1 = pos[10], pos[11]
        in_range = tick_lower <= tick_current < tick_upper
        amt0, amt1 = amounts_from_liquidity(
            liquidity, sqrt_price_x96, tick_lower, tick_upper, tick_current, dec0, dec1
        )
        owed0_h = owed0 / (10 ** dec0)
        owed1_h = owed1 / (10 ** dec1)
        usd = amt0 * eth_usd + amt1 + owed0_h * eth_usd + owed1_h
        pl = (1.0001 ** tick_lower) * (10 ** (dec0 - dec1))
        pu = (1.0001 ** tick_upper) * (10 ** (dec0 - dec1))
        share = (liquidity / pool_liq * 100.0) if pool_liq and liquidity else 0.0
        positions.append({
            "tokenId": tid, "owner": owner, "nonce": int(pos[0]), "operator": pos[1], "token0": pos[2], "token1": pos[3],
            "owner_match": owner.lower() == WALLET.lower(),
            "fee": pos[4], "tickLower": tick_lower, "tickUpper": tick_upper,
            "width_ticks": tick_upper - tick_lower, "liquidity": int(liquidity),
            "feeGrowthInside0LastX128": int(pos[8]), "feeGrowthInside1LastX128": int(pos[9]), "tokensOwed0": int(owed0), "tokensOwed1": int(owed1),
            "in_range": in_range, "has_liquidity": int(liquidity) > 0, "amount0": amt0, "amount1": amt1,
            "owed0_human": owed0_h, "owed1_human": owed1_h,
            "usd_estimate": usd,
            "price_lower_eth_usd": pl, "price_upper_eth_usd": pu,
            "pool_liq_share_pct": share,
        })


    llama = fetch_llama()
    out = {
        "wallet": WALLET,
        "chain": "arbitrum",
        "rpc": RPC,
        "block": block,
        "balances": {
            "eth": eth,
            "eth_wei": int(eth_wei),
            "weth": weth,
            "weth_raw": int(weth_raw),
            "usdc": usdc,
            "usdc_raw": int(usdc_raw),
        },
        "pool": {
            "address": POOL,
            "pair": "WETH-USDC",
            "fee": int(fee),
            "sqrtPriceX96": int(sqrt_price_x96),
            "tick": int(tick_current),
            "eth_usd": eth_usd,
            "liquidity": int(pool_liq),
        },
        "npm_addr": NPM,
        "tokenIds": token_ids,
        "positions": positions,
        "defillama": llama,
    }
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
