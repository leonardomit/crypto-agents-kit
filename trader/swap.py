#!/usr/bin/env python3
"""Swap Uniswap V3 (quote + opcional exec).

Hard rules (pós-incidente: tx enviada a endereço sem bytecode na Arbitrum):
- Antes de live: eth_getCode(to); abortar se vazio
- Nunca 0x68b346... na Arbitrum (DENYLIST)
- Sem approve Unlimited (script nao faz approve ERC20; ETH nativo so)

Caps 6% / US$3. Default DRY_RUN=1.

Uso:
  python trader/swap.py \\
    --chain base --amount-usd 3 --src eth --dst usdc

Live: DRY_RUN=0 ... --execute
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_caps import (  # noqa: E402
    CHAIN_IDS, DRY_RUN, RPC, SLIPPAGE_BPS, assert_live_to, assert_size_ok,
    load_address, load_key, max_usd,
)
from tokens import DECIMALS, FEE_TIERS, QUOTER_V2, ROUTER, ROUTER_KIND, TOKENS  # noqa: E402

QUOTER_ABI = [{
    "inputs": [{"components": [
        {"name": "tokenIn", "type": "address"},
        {"name": "tokenOut", "type": "address"},
        {"name": "amountIn", "type": "uint256"},
        {"name": "fee", "type": "uint24"},
        {"name": "sqrtPriceLimitX96", "type": "uint160"},
    ], "name": "params", "type": "tuple"}],
    "name": "quoteExactInputSingle",
    "outputs": [
        {"name": "amountOut", "type": "uint256"},
        {"name": "sqrtPriceX96After", "type": "uint160"},
        {"name": "initializedTicksCrossed", "type": "uint32"},
        {"name": "gasEstimate", "type": "uint256"},
    ],
    "stateMutability": "nonpayable",
    "type": "function",
}]
ROUTER_ABI_SR02 = [{
    "inputs": [{"components": [
        {"name": "tokenIn", "type": "address"},
        {"name": "tokenOut", "type": "address"},
        {"name": "fee", "type": "uint24"},
        {"name": "recipient", "type": "address"},
        {"name": "amountIn", "type": "uint256"},
        {"name": "amountOutMinimum", "type": "uint256"},
        {"name": "sqrtPriceLimitX96", "type": "uint160"},
    ], "name": "params", "type": "tuple"}],
    "name": "exactInputSingle",
    "outputs": [{"name": "amountOut", "type": "uint256"}],
    "stateMutability": "payable",
    "type": "function",
}]
ROUTER_ABI_SR01 = [{
    "inputs": [{"components": [
        {"name": "tokenIn", "type": "address"},
        {"name": "tokenOut", "type": "address"},
        {"name": "fee", "type": "uint24"},
        {"name": "recipient", "type": "address"},
        {"name": "deadline", "type": "uint256"},
        {"name": "amountIn", "type": "uint256"},
        {"name": "amountOutMinimum", "type": "uint256"},
        {"name": "sqrtPriceLimitX96", "type": "uint160"},
    ], "name": "params", "type": "tuple"}],
    "name": "exactInputSingle",
    "outputs": [{"name": "amountOut", "type": "uint256"}],
    "stateMutability": "payable",
    "type": "function",
}]

def resolve_token(chain: str, sym: str) -> str:
    m = TOKENS.get(chain, {})
    s = sym.lower()
    if s in m:
        return m[s]
    if sym.startswith("0x") and len(sym) == 42:
        return sym
    raise SystemExit(f"token desconhecido: {sym} em {chain}")

def best_quote(w3, chain: str, token_in: str, token_out: str, amount_in: int):
    quoter = w3.eth.contract(address=w3.to_checksum_address(QUOTER_V2[chain]), abi=QUOTER_ABI)
    best = None
    for fee in FEE_TIERS:
        try:
            out = quoter.functions.quoteExactInputSingle(
                (w3.to_checksum_address(token_in), w3.to_checksum_address(token_out), amount_in, fee, 0)
            ).call()
            cand = {"fee": fee, "amount_out": int(out[0]), "gas_est": int(out[3])}
            if best is None or cand["amount_out"] > best["amount_out"]:
                best = cand
        except Exception:
            continue
    if not best:
        raise SystemExit("sem quote Uniswap V3 (todos fee tiers falharam)")
    return best

def main() -> None:
    p = argparse.ArgumentParser(description="Uniswap V3 swap com teto MAX_POSITION_USD (lib_caps)")
    p.add_argument("--chain", default="base", choices=[c for c in CHAIN_IDS if c in QUOTER_V2])
    p.add_argument("--amount-usd", type=Decimal, required=True)
    p.add_argument("--src", default="eth")
    p.add_argument("--dst", default="usdc")
    p.add_argument("--eth-price-usd", type=Decimal, default=Decimal("2500"),
                   help="só pra converter amount-usd → wei quando src=eth/weth")
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    assert_size_ok(args.amount_usd)
    from eth_account import Account
    from web3 import Web3

    key = load_key()
    addr_env = load_address()
    acct = Account.from_key(key)
    if acct.address.lower() != addr_env.lower():
        raise SystemExit(f"chave ≠ DEFI_WALLET_ADDRESS ({addr_env} vs {acct.address})")

    w3 = Web3(Web3.HTTPProvider(RPC[args.chain]))
    if not w3.is_connected():
        raise SystemExit("RPC offline")

    token_in = resolve_token(args.chain, args.src)
    token_out = resolve_token(args.chain, args.dst)
    src_dec = DECIMALS.get(args.src.lower(), 18)
    dst_dec = DECIMALS.get(args.dst.lower(), 18)

    if args.src.lower() in ("eth", "weth"):
        amount_in = int(args.amount_usd / args.eth_price_usd * (Decimal(10) ** 18))
    else:
        amount_in = int(args.amount_usd * (Decimal(10) ** src_dec))

    q = best_quote(w3, args.chain, token_in, token_out, amount_in)
    min_out = q["amount_out"] * (10_000 - SLIPPAGE_BPS) // 10_000

    plan = {
        "dry_run": DRY_RUN or not args.execute,
        "router": f"uniswap-v3-{ROUTER_KIND[args.chain]}",
        "chain": args.chain,
        "chain_id": CHAIN_IDS[args.chain],
        "from": acct.address,
        "token_in": token_in,
        "token_out": token_out,
        "fee": q["fee"],
        "amount_in": str(amount_in),
        "amount_out_quoted": str(q["amount_out"]),
        "amount_out_human": str(Decimal(q["amount_out"]) / (Decimal(10) ** dst_dec)),
        "amount_out_min": str(min_out),
        "slippage_bps": SLIPPAGE_BPS,
        "amount_usd": str(args.amount_usd),
        "max_usd": str(max_usd()),
        "native_balance_wei": str(w3.eth.get_balance(acct.address)),
    }

    kind = ROUTER_KIND[args.chain]
    abi = ROUTER_ABI_SR01 if kind == "sr01" else ROUTER_ABI_SR02
    router = w3.eth.contract(address=w3.to_checksum_address(ROUTER[args.chain]), abi=abi)
    value = amount_in if args.src.lower() == "eth" else 0
    if kind == "sr01":
        params = (
            w3.to_checksum_address(token_in),
            w3.to_checksum_address(token_out),
            q["fee"],
            acct.address,
            int(time.time()) + 600,
            amount_in,
            min_out,
            0,
        )
    else:
        params = (
            w3.to_checksum_address(token_in),
            w3.to_checksum_address(token_out),
            q["fee"],
            acct.address,
            amount_in,
            min_out,
            0,
        )
    # Hard rule: denylist + eth_getCode before building live-capable tx
    assert_live_to(w3, args.chain, ROUTER[args.chain])
    tx_data = router.functions.exactInputSingle(params).build_transaction({
        "from": acct.address,
        "value": value,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": CHAIN_IDS[args.chain],
        "gas": 350000,
    })
    try:
        tx_data["maxFeePerGas"] = w3.eth.gas_price * 2
        tx_data["maxPriorityFeePerGas"] = w3.to_wei(0.01, "gwei")
    except Exception:
        tx_data["gasPrice"] = w3.eth.gas_price

    plan["tx_to"] = tx_data["to"]
    plan["tx_value"] = str(tx_data.get("value", 0))
    plan["tx_data_len"] = len(tx_data.get("data", "0x"))

    print(json.dumps(plan, indent=2))

    if plan["dry_run"]:
        print("# dry-run: nenhuma tx enviada", file=sys.stderr)
        return

    # Re-check immediately before sign/send (dry-run != live)
    assert_live_to(w3, args.chain, tx_data["to"])
    bal = w3.eth.get_balance(acct.address)
    if value and bal < value:
        raise SystemExit(f"saldo nativo insuficiente: {bal} < {value}")

    signed = acct.sign_transaction(tx_data)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h = w3.eth.send_raw_transaction(raw)
    print(json.dumps({"submitted": h.hex(), "at": int(time.time())}, indent=2))

if __name__ == "__main__":
    main()
