#!/usr/bin/env python3
"""Uniswap V3 LP exit (Arbitrum first). decreaseLiquidity → collect → burn.

Hard rules: assert_live_to (bytecode + DENYLIST), dry-run default, never Unlimited.
Default: remove 100% liquidity. Use --pct to partial.
"""
from __future__ import annotations
import argparse, json, sys, time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_caps import (  # noqa: E402
    CHAIN_IDS, DRY_RUN, RPC, SLIPPAGE_BPS, assert_live_to, load_address, load_key,
)
from tokens import DENYLIST  # noqa: E402

NPM = {
    "arbitrum": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
    "ethereum": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
    "base": "0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1",
}
FACTORY = {
    "arbitrum": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    "ethereum": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    "base": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
}
MAX_UINT128 = (1 << 128) - 1

NPM_ABI = [
    {"name": "ownerOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "tokenId", "type": "uint256"}],
     "outputs": [{"type": "address"}]},
    {"name": "positions", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "tokenId", "type": "uint256"}],
     "outputs": [
         {"name": "nonce", "type": "uint96"}, {"name": "operator", "type": "address"},
         {"name": "token0", "type": "address"}, {"name": "token1", "type": "address"},
         {"name": "fee", "type": "uint24"}, {"name": "tickLower", "type": "int24"},
         {"name": "tickUpper", "type": "int24"}, {"name": "liquidity", "type": "uint128"},
         {"name": "feeGrowthInside0LastX128", "type": "uint256"},
         {"name": "feeGrowthInside1LastX128", "type": "uint256"},
         {"name": "tokensOwed0", "type": "uint128"}, {"name": "tokensOwed1", "type": "uint128"},
     ]},
    {"name": "decreaseLiquidity", "type": "function", "stateMutability": "payable",
     "inputs": [{"components": [
         {"name": "tokenId", "type": "uint256"}, {"name": "liquidity", "type": "uint128"},
         {"name": "amount0Min", "type": "uint256"}, {"name": "amount1Min", "type": "uint256"},
         {"name": "deadline", "type": "uint256"},
     ], "name": "params", "type": "tuple"}],
     "outputs": [{"name": "amount0", "type": "uint256"}, {"name": "amount1", "type": "uint256"}]},
    {"name": "collect", "type": "function", "stateMutability": "payable",
     "inputs": [{"components": [
         {"name": "tokenId", "type": "uint256"}, {"name": "recipient", "type": "address"},
         {"name": "amount0Max", "type": "uint128"}, {"name": "amount1Max", "type": "uint128"},
     ], "name": "params", "type": "tuple"}],
     "outputs": [{"name": "amount0", "type": "uint256"}, {"name": "amount1", "type": "uint256"}]},
    {"name": "burn", "type": "function", "stateMutability": "payable",
     "inputs": [{"name": "tokenId", "type": "uint256"}], "outputs": []},
    {"name": "multicall", "type": "function", "stateMutability": "payable",
     "inputs": [{"name": "data", "type": "bytes[]"}],
     "outputs": [{"name": "results", "type": "bytes[]"}]},
]
FACTORY_ABI = [{
    "inputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"},
               {"name": "fee", "type": "uint24"}],
    "name": "getPool", "outputs": [{"type": "address"}],
    "stateMutability": "view", "type": "function",
}]
POOL_ABI = [{
    "inputs": [], "name": "slot0",
    "outputs": [{"type": "uint160"}, {"type": "int24"}, {"type": "uint16"},
                {"type": "uint16"}, {"type": "uint16"}, {"type": "uint8"}, {"type": "bool"}],
    "stateMutability": "view", "type": "function",
}]


def _send(w3, acct, chain: str, tx: dict) -> str:
    assert_live_to(w3, chain, tx["to"])
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h = w3.eth.send_raw_transaction(raw)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=180)
    if r["status"] != 1:
        raise SystemExit(f"tx falhou: {h.hex()}")
    return h.hex()


def main() -> None:
    p = argparse.ArgumentParser(description="Uniswap V3 LP exit (decrease/collect/burn)")
    p.add_argument("--chain", default="arbitrum", choices=list(NPM))
    p.add_argument("--token-id", type=int, required=True)
    p.add_argument("--pct", type=Decimal, default=Decimal("100"),
                   help="%% liquidez a remover (default 100)")
    p.add_argument("--amount0-min", type=int, default=0)
    p.add_argument("--amount1-min", type=int, default=0)
    p.add_argument("--no-burn", action="store_true", help="não burn NFT após exit total")
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    if args.pct <= 0 or args.pct > 100:
        raise SystemExit("--pct deve estar em (0, 100]")

    from web3 import Web3

    dry = DRY_RUN or not args.execute
    addr = load_address()
    acct = None
    if not dry:
        from eth_account import Account
        key = load_key()
        acct = Account.from_key(key)
        if acct.address.lower() != addr.lower():
            raise SystemExit("chave != endereco")

    w3 = Web3(Web3.HTTPProvider(RPC[args.chain]))
    if not w3.is_connected():
        raise SystemExit("RPC offline")

    npm_addr = NPM[args.chain]
    assert_live_to(w3, args.chain, npm_addr)
    for bad in DENYLIST.get(args.chain, set()):
        if npm_addr.lower() == bad.lower():
            raise SystemExit("NPM na denylist")

    npm = w3.eth.contract(address=Web3.to_checksum_address(npm_addr), abi=NPM_ABI)
    tid = args.token_id
    owner = npm.functions.ownerOf(tid).call()
    if owner.lower() != addr.lower():
        raise SystemExit(f"NFT {tid} owner={owner} != wallet {addr}")

    pos = npm.functions.positions(tid).call()
    token0, token1, fee = pos[2], pos[3], pos[4]
    tick_lower, tick_upper, liquidity = pos[5], pos[6], pos[7]
    owed0, owed1 = pos[10], pos[11]

    fac = w3.eth.contract(address=Web3.to_checksum_address(FACTORY[args.chain]), abi=FACTORY_ABI)
    pool_addr = fac.functions.getPool(token0, token1, fee).call()
    if int(pool_addr, 16) == 0:
        raise SystemExit("pool zero")
    assert_live_to(w3, args.chain, pool_addr)
    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_addr), abi=POOL_ABI)
    cur_tick = pool.functions.slot0().call()[1]
    oor = cur_tick < tick_lower or cur_tick >= tick_upper

    liq_remove = int(Decimal(liquidity) * args.pct / Decimal(100))
    if liquidity > 0 and liq_remove <= 0:
        raise SystemExit("liq_remove=0")
    if liquidity == 0 and owed0 == 0 and owed1 == 0:
        raise SystemExit(f"NFT {tid} já vazio (liq=0, owed=0)")

    do_burn = (not args.no_burn) and args.pct >= 100 and liquidity > 0
    deadline = int(time.time()) + 600

    plan = {
        "action": "lp_exit",
        "dry_run": dry,
        "chain": args.chain,
        "token_id": tid,
        "npm": npm_addr,
        "pool": pool_addr,
        "token0": token0,
        "token1": token1,
        "fee": fee,
        "tick_lower": tick_lower,
        "tick_upper": tick_upper,
        "current_tick": cur_tick,
        "oor": oor,
        "liquidity": str(liquidity),
        "liquidity_remove": str(liq_remove),
        "pct": str(args.pct),
        "tokens_owed0": str(owed0),
        "tokens_owed1": str(owed1),
        "amount0_min": args.amount0_min,
        "amount1_min": args.amount1_min,
        "slippage_bps_note": SLIPPAGE_BPS,
        "burn": do_burn,
        "steps": ["decreaseLiquidity", "collect"] + (["burn"] if do_burn else []),
        "from": addr,
    }
    print(json.dumps(plan, indent=2))

    if dry:
        print("# dry-run: nenhuma tx", file=sys.stderr)
        return

    calls = []
    if liq_remove > 0:
        calls.append(npm.encode_abi(
            abi_element_identifier="decreaseLiquidity",
            args=[(tid, liq_remove, args.amount0_min, args.amount1_min, deadline)],
        ))
    calls.append(npm.encode_abi(
        abi_element_identifier="collect",
        args=[(tid, acct.address, MAX_UINT128, MAX_UINT128)],
    ))
    if do_burn:
        calls.append(npm.encode_abi(abi_element_identifier="burn", args=[tid]))

    tx = npm.functions.multicall(calls).build_transaction({
        "from": addr,
        "value": 0,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": CHAIN_IDS[args.chain],
        "gas": 700000,
        "maxFeePerGas": w3.eth.gas_price * 2,
        "maxPriorityFeePerGas": w3.to_wei(0.01, "gwei"),
    })
    assert_live_to(w3, args.chain, tx["to"])
    hx = _send(w3, acct, args.chain, tx)
    print(json.dumps({"exit_tx": hx, "token_id": tid, "burn": do_burn}, indent=2))


if __name__ == "__main__":
    main()
