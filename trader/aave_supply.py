#!/usr/bin/env python3
"""Aave V3 supply (Arbitrum USDC). Default DRY_RUN=1.

Hard rules:
- Resolve Pool via AddressesProvider.getPool() — NEVER trust hardcoded Pool addrs
  (incidente: 0x794a…aE4 tem bytecode vazio; getPool retorna …4814aD)
- assert_live_to (bytecode + DENYLIST) before any live tx
- approve exact amount only (nunca Unlimited)
"""
from __future__ import annotations
import argparse, json, sys, time
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_caps import CHAIN_IDS, DRY_RUN, RPC, assert_live_to, assert_size_ok, load_address, load_key, max_usd
from tokens import TOKENS

AAVE_PROVIDER = {
    "arbitrum": "0xa97684ead0e402dC232d5A977953DF7ECBaB3CDb",
}
# Known BAD addresses (empty code / typo) — also add to runtime checks
AAVE_POOL_DENY = {
    "arbitrum": {"0x794a61358d6845594f94dc1db446a818166be8e4"},  # docs typo / empty
}
PROVIDER_ABI = [{"inputs":[],"name":"getPool","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]
POOL_ABI = [{
  "inputs":[{"name":"asset","type":"address"},{"name":"amount","type":"uint256"},
            {"name":"onBehalfOf","type":"address"},{"name":"referralCode","type":"uint16"}],
  "name":"supply","outputs":[],"stateMutability":"nonpayable","type":"function"
}]
ERC20_ABI = [
  {"name":"approve","type":"function","stateMutability":"nonpayable","inputs":[{"name":"s","type":"address"},{"name":"a","type":"uint256"}],"outputs":[{"type":"bool"}]},
  {"name":"allowance","type":"function","stateMutability":"view","inputs":[{"name":"o","type":"address"},{"name":"s","type":"address"}],"outputs":[{"type":"uint256"}]},
  {"name":"balanceOf","type":"function","stateMutability":"view","inputs":[{"name":"a","type":"address"}],"outputs":[{"type":"uint256"}]},
  {"name":"decimals","type":"function","stateMutability":"view","inputs":[],"outputs":[{"type":"uint8"}]},
]

def resolve_pool(w3, chain: str) -> str:
    from web3 import Web3
    prov = AAVE_PROVIDER[chain]
    assert_live_to(w3, chain, prov)
    c = w3.eth.contract(address=Web3.to_checksum_address(prov), abi=PROVIDER_ABI)
    pool = c.functions.getPool().call()
    if pool.lower() in AAVE_POOL_DENY.get(chain, set()):
        raise SystemExit(f"bloqueado: getPool retornou denylist {pool}")
    assert_live_to(w3, chain, pool)
    return pool

def main() -> None:
    p = argparse.ArgumentParser(description="Aave V3 supply USDC Arb")
    p.add_argument("--chain", default="arbitrum", choices=list(AAVE_PROVIDER))
    p.add_argument("--amount-usd", type=Decimal, required=True)
    p.add_argument("--asset", default="usdc")
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()
    assert_size_ok(args.amount_usd)
    from eth_account import Account
    from web3 import Web3
    key = load_key(); addr = load_address()
    acct = Account.from_key(key)
    if acct.address.lower() != addr.lower():
        raise SystemExit("chave != endereco")
    w3 = Web3(Web3.HTTPProvider(RPC[args.chain]))
    if not w3.is_connected():
        raise SystemExit("RPC offline")
    pool_addr = resolve_pool(w3, args.chain)
    asset = Web3.to_checksum_address(TOKENS[args.chain][args.asset.lower()])
    assert_live_to(w3, args.chain, asset)
    token = w3.eth.contract(address=asset, abi=ERC20_ABI)
    dec = token.functions.decimals().call()
    amount = int(args.amount_usd * (Decimal(10) ** dec))
    bal = token.functions.balanceOf(acct.address).call()
    plan = {
        "action": "aave_supply", "dry_run": DRY_RUN or not args.execute,
        "chain": args.chain, "pool": pool_addr, "asset": asset,
        "amount": str(amount), "amount_usd": str(args.amount_usd),
        "max_usd": str(max_usd()), "wallet_balance": str(bal),
        "from": acct.address, "approve": "exact_amount_not_unlimited",
        "pool_resolved_via": "AddressesProvider.getPool",
    }
    print(json.dumps(plan, indent=2))
    if bal < amount:
        print(f"# aviso: saldo {bal} < amount {amount} — live falharia", file=sys.stderr)
    if plan["dry_run"]:
        print("# dry-run: nenhuma tx", file=sys.stderr); return
    if bal < amount:
        raise SystemExit("saldo insuficiente")
    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_addr), abi=POOL_ABI)
    allow = token.functions.allowance(acct.address, pool_addr).call()
    if allow < amount:
        tx = token.functions.approve(pool_addr, amount).build_transaction({
            "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address),
            "chainId": CHAIN_IDS[args.chain], "gas": 100000,
            "maxFeePerGas": w3.eth.gas_price * 2, "maxPriorityFeePerGas": w3.to_wei(0.01, "gwei"),
        })
        assert_live_to(w3, args.chain, tx["to"])
        signed = acct.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        h = w3.eth.send_raw_transaction(raw)
        print(json.dumps({"approve_tx": h.hex(), "amount": str(amount)}))
        w3.eth.wait_for_transaction_receipt(h, timeout=120)
    tx = pool.functions.supply(asset, amount, acct.address, 0).build_transaction({
        "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": CHAIN_IDS[args.chain], "gas": 400000,
        "maxFeePerGas": w3.eth.gas_price * 2, "maxPriorityFeePerGas": w3.to_wei(0.01, "gwei"),
    })
    assert_live_to(w3, args.chain, tx["to"])
    if tx["to"].lower() in AAVE_POOL_DENY.get(args.chain, set()):
        raise SystemExit("bloqueado: pool denylist")
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h = w3.eth.send_raw_transaction(raw)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=180)
    print(json.dumps({"supply_tx": h.hex(), "status": r["status"], "gasUsed": r["gasUsed"], "logs": len(r["logs"])}, indent=2))

if __name__ == "__main__":
    main()
