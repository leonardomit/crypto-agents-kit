#!/usr/bin/env python3
"""Uniswap V3 multi-hop swap (SwapRouter01 exactInput) — Arbitrum. Dry-run default.

Hard rules:
- assert_live_to(router) + assert_live_to(token_in) antes de qualquer tx (denylist + eth_getCode)
- Nunca 0x68b346... (SwapRouter02 vazio na Arb) — router fixo = 0xE592427A0AEce92De3Edee1F18E0157C05861564
- Approve EXATO do amount_in (nunca unlimited); reset p/ 0 se allowance atual > amount
- minOut = quote * (1 - SLIPPAGE_BPS) (default 100 bps = 1%)
- Simulação completa (eth_call com state-override de allowance + estimateGas) antes de enviar
- Cap US$25 (lib_caps) aplicado quando token_in é USDC (entrada). Saídas (venda) não são bloqueadas pelo cap.

Uso:
  # entrada (dry-run)
  python swap_v3_path.py --path usdc:500:weth:3000:magic --amount-in 15
  # saída de todo MAGIC (dry-run)
  python swap_v3_path.py --path magic:3000:weth:500:usdc --amount-in all
  # live: DRY_RUN=0 ... --execute
"""
from __future__ import annotations
import argparse, json, sys, time
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_caps import CHAIN_IDS, DRY_RUN, RPC, SLIPPAGE_BPS, assert_live_to, assert_size_ok, load_address, load_key

CHAIN = "arbitrum"
ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"   # Uniswap SwapRouter (01) — known good
QUOTER_V2 = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"
TOK = {
    "usdc": ("0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6),
    "weth": ("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", 18),
    "magic": ("0x539bdE0d7Dbd336b79148AA742883198BBF60342", 18),
}
UNLIMITED_THRESHOLD = 1 << 200
ERC20 = [
    {"inputs": [{"name": "a", "type": "address"}], "name": "balanceOf", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}], "name": "approve", "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}], "name": "allowance", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]
QUOTER_ABI = [{"inputs": [{"name": "path", "type": "bytes"}, {"name": "amountIn", "type": "uint256"}], "name": "quoteExactInput",
               "outputs": [{"type": "uint256"}, {"type": "uint160[]"}, {"type": "uint32[]"}, {"type": "uint256"}], "stateMutability": "nonpayable", "type": "function"}]
ROUTER_ABI = [{"inputs": [{"components": [
    {"name": "path", "type": "bytes"}, {"name": "recipient", "type": "address"}, {"name": "deadline", "type": "uint256"},
    {"name": "amountIn", "type": "uint256"}, {"name": "amountOutMinimum", "type": "uint256"}], "name": "params", "type": "tuple"}],
    "name": "exactInput", "outputs": [{"name": "amountOut", "type": "uint256"}], "stateMutability": "payable", "type": "function"}]


def parse_path(s):
    parts = s.lower().split(":")
    toks = parts[0::2]; fees = [int(x) for x in parts[1::2]]
    if len(toks) != len(fees) + 1 or any(t not in TOK for t in toks):
        raise SystemExit(f"path inválido: {s}")
    b = b""
    for i, t in enumerate(toks):
        b += bytes.fromhex(TOK[t][0][2:])
        if i < len(fees):
            b += fees[i].to_bytes(3, "big")
    return toks, fees, b


def fees_tx(w3):
    base = w3.eth.gas_price
    return {"maxFeePerGas": base * 2, "maxPriorityFeePerGas": 0}


def find_allowance_slot(w3, token, owner, spender):
    """Brute-force mapping slot p/ state-override (só simulação)."""
    from eth_abi import encode
    c = w3.eth.contract(address=token, abi=ERC20)
    probe = 123456789
    for k in range(0, 60):
        inner = w3.keccak(encode(["address", "uint256"], [owner, k]))
        slot = w3.keccak(encode(["address"], [spender]) + inner)
        ov = {token: {"stateDiff": {"0x" + slot.hex().removeprefix("0x"): "0x" + probe.to_bytes(32, "big").hex()}}}
        try:
            v = c.functions.allowance(owner, spender).call(state_override=ov)
        except Exception:
            continue
        if v == probe:
            return slot
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="ex: usdc:500:weth:3000:magic")
    ap.add_argument("--amount-in", required=True, help="unidades humanas do token_in, ou 'all'")
    ap.add_argument("--slippage-bps", type=int, default=SLIPPAGE_BPS)
    ap.add_argument("--execute", action="store_true")
    a = ap.parse_args()

    from eth_account import Account
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(RPC[CHAIN]))
    C = Web3.to_checksum_address
    key = load_key(); acct = Account.from_key(key); del key
    if acct.address.lower() != load_address().lower():
        raise SystemExit("chave ≠ wallet.address")
    toks, fees, pbytes = parse_path(a.path)
    tin, din = C(TOK[toks[0]][0]), TOK[toks[0]][1]
    tout, dout = C(TOK[toks[-1]][0]), TOK[toks[-1]][1]
    tin_c = w3.eth.contract(address=tin, abi=ERC20); tout_c = w3.eth.contract(address=tout, abi=ERC20)
    bal_in = tin_c.functions.balanceOf(acct.address).call()
    amount_in = bal_in if a.amount_in == "all" else int(Decimal(a.amount_in) * Decimal(10) ** din)
    if amount_in <= 0 or amount_in > bal_in:
        raise SystemExit(f"saldo insuficiente: {bal_in} < {amount_in}")
    if toks[0] == "usdc":
        assert_size_ok(Decimal(amount_in) / Decimal(10) ** din)
    router = C(ROUTER)
    assert_live_to(w3, CHAIN, router)
    assert_live_to(w3, CHAIN, tin)
    quoter = w3.eth.contract(address=C(QUOTER_V2), abi=QUOTER_ABI)
    qo = quoter.functions.quoteExactInput(pbytes, amount_in).call()
    quoted = int(qo[0]); min_out = quoted * (10_000 - a.slippage_bps) // 10_000
    rc = w3.eth.contract(address=router, abi=ROUTER_ABI)
    deadline = int(time.time()) + 600
    params = (pbytes, acct.address, deadline, amount_in, min_out)
    cur_allow = tin_c.functions.allowance(acct.address, router).call()
    plan = {"dry_run": DRY_RUN or not a.execute, "router": router, "path": a.path, "token_in": tin, "token_out": tout,
            "amount_in": str(amount_in), "amount_in_human": str(Decimal(amount_in) / Decimal(10) ** din),
            "quoted_out": str(quoted), "quoted_out_human": str(Decimal(quoted) / Decimal(10) ** dout),
            "min_out": str(min_out), "min_out_human": str(Decimal(min_out) / Decimal(10) ** dout), "slippage_bps": a.slippage_bps,
            "allowance_current": str(cur_allow), "approve_needed": cur_allow < amount_in, "approve_amount": str(amount_in),
            "eth_balance": str(w3.eth.get_balance(acct.address) / 1e18)}
    # simulate swap with allowance state-override (no tx)
    slot = find_allowance_slot(w3, tin, acct.address, router)
    ov = None
    if slot is not None:
        ov = {tin: {"stateDiff": {"0x" + slot.hex().removeprefix("0x"): "0x" + amount_in.to_bytes(32, "big").hex()}}}
    try:
        sim_out = rc.functions.exactInput(params).call({"from": acct.address}, state_override=ov) if ov else \
                  (rc.functions.exactInput(params).call({"from": acct.address}) if cur_allow >= amount_in else None)
        plan["sim_out"] = str(sim_out) if sim_out is not None else "skipped(no-override)"
        plan["sim_ok"] = sim_out is not None and sim_out >= min_out
    except Exception as e:
        plan["sim_ok"] = False; plan["sim_err"] = str(e)[:300]
    plan["allowance_slot_found"] = slot is not None
    print(json.dumps(plan, indent=1))
    if plan["dry_run"]:
        print("# dry-run: nenhuma tx enviada", file=sys.stderr); return
    if not plan["sim_ok"]:
        raise SystemExit("bloqueado: simulação falhou")
    if amount_in >= UNLIMITED_THRESHOLD:
        raise SystemExit("bloqueado: approve parece unlimited")
    out = {"txs": []}
    nonce = w3.eth.get_transaction_count(acct.address)
    def send(tx):
        assert_live_to(w3, CHAIN, tx["to"])
        signed = acct.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        h = w3.eth.send_raw_transaction(raw)
        r = w3.eth.wait_for_transaction_receipt(h, timeout=180)
        return "0x" + h.hex().removeprefix("0x"), r
    if cur_allow != amount_in:
        if cur_allow > amount_in:
            tx = tin_c.functions.approve(router, 0).build_transaction({"from": acct.address, "nonce": nonce, "chainId": CHAIN_IDS[CHAIN], "gas": 100000, **fees_tx(w3)})
            h, r = send(tx); out["txs"].append({"approve0": h, "status": r.status}); nonce += 1
            if r.status != 1: raise SystemExit(json.dumps(out))
        tx = tin_c.functions.approve(router, amount_in).build_transaction({"from": acct.address, "nonce": nonce, "chainId": CHAIN_IDS[CHAIN], "gas": 100000, **fees_tx(w3)})
        h, r = send(tx); out["txs"].append({"approve": h, "amount": str(amount_in), "status": r.status}); nonce += 1
        if r.status != 1: raise SystemExit(json.dumps(out))
    # re-simulate for real (allowance now set) + estimateGas
    sim2 = rc.functions.exactInput(params).call({"from": acct.address})
    if sim2 < min_out: raise SystemExit(f"bloqueado: sim2 {sim2} < min_out {min_out}")
    gas = rc.functions.exactInput(params).estimate_gas({"from": acct.address})
    before = tout_c.functions.balanceOf(acct.address).call()
    tx = rc.functions.exactInput(params).build_transaction({"from": acct.address, "nonce": nonce, "chainId": CHAIN_IDS[CHAIN], "gas": int(gas * 1.3), "value": 0, **fees_tx(w3)})
    h, r = send(tx)
    after = tout_c.functions.balanceOf(acct.address).call()
    out.update({"swap_tx": h, "status": r.status, "gas_used": r.gasUsed, "block": r.blockNumber,
                "received_raw": str(after - before), "received_human": str(Decimal(after - before) / Decimal(10) ** dout),
                "amount_in_human": plan["amount_in_human"], "at": int(time.time())})
    print(json.dumps(out, indent=1))

if __name__ == "__main__":
    main()
