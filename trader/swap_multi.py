#!/usr/bin/env python3
"""Multi-chain swap (Base: Uniswap v3 / Aerodrome; BNB: PancakeSwap v3). DRY-RUN DEFAULT.

Hard rules:
- todo endereço vem de chains.json verificado (allowlist por chain) + eth_getCode antes de live
- approve EXATO do amount_in (nunca unlimited)
- cap US$25 (lib_caps.assert_size_ok) quando entrada é stable
- simulação eth_call + estimateGas com state-override (saldo/allowance) — nada assinado em dry-run
- live só com DRY_RUN=0 + --execute + --i-understand-live

Uso:
  python swap_multi.py --chain base --dex uniswap  --src usdc --dst weth --amount-in 10
  python swap_multi.py --chain base --dex aerodrome --src usdc --dst weth --amount-in 10
  python swap_multi.py --chain bnb  --dex pancake  --src usdt --dst wbnb --amount-in 10
"""
from __future__ import annotations
import argparse, json, sys, time
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_caps import SLIPPAGE_BPS, assert_size_ok, load_address, load_key  # noqa
from lib_chains import (CHAIN_IDS, addr, assert_exact_approve, assert_live_to_reg, erc20_slots,
                        gas_cost, live_allowed, make_w3, token)

STABLES = {"usdc", "usdt"}
DEX = {("base", "uniswap"): ("uniswap_v3_quoterv2", "uniswap_v3_swaprouter02"),
       ("bnb", "pancake"): ("pancake_v3_quoterv2", "pancake_smart_router"),
       ("base", "aerodrome"): (None, "aerodrome_router")}
FEE_TIERS = {"uniswap": (100, 500, 3000, 10000), "pancake": (100, 500, 2500, 10000)}
ERC20 = [
 {"name": "balanceOf", "type": "function", "stateMutability": "view", "inputs": [{"name": "a", "type": "address"}], "outputs": [{"type": "uint256"}]},
 {"name": "allowance", "type": "function", "stateMutability": "view", "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}], "outputs": [{"type": "uint256"}]},
 {"name": "approve", "type": "function", "stateMutability": "nonpayable", "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}], "outputs": [{"type": "bool"}]}]
QUOTER = [{"inputs": [{"components": [{"name": "tokenIn", "type": "address"}, {"name": "tokenOut", "type": "address"}, {"name": "amountIn", "type": "uint256"}, {"name": "fee", "type": "uint24"}, {"name": "sqrtPriceLimitX96", "type": "uint160"}], "name": "p", "type": "tuple"}],
           "name": "quoteExactInputSingle", "outputs": [{"name": "amountOut", "type": "uint256"}, {"name": "s", "type": "uint160"}, {"name": "t", "type": "uint32"}, {"name": "gasEstimate", "type": "uint256"}], "stateMutability": "nonpayable", "type": "function"}]
SR02 = [{"inputs": [{"components": [{"name": "tokenIn", "type": "address"}, {"name": "tokenOut", "type": "address"}, {"name": "fee", "type": "uint24"}, {"name": "recipient", "type": "address"}, {"name": "amountIn", "type": "uint256"}, {"name": "amountOutMinimum", "type": "uint256"}, {"name": "sqrtPriceLimitX96", "type": "uint160"}], "name": "p", "type": "tuple"}],
         "name": "exactInputSingle", "outputs": [{"name": "amountOut", "type": "uint256"}], "stateMutability": "payable", "type": "function"}]
ROUTE = {"components": [{"name": "from", "type": "address"}, {"name": "to", "type": "address"}, {"name": "stable", "type": "bool"}, {"name": "factory", "type": "address"}], "name": "routes", "type": "tuple[]"}
AERO = [{"name": "getAmountsOut", "type": "function", "stateMutability": "view", "inputs": [{"name": "amountIn", "type": "uint256"}, ROUTE], "outputs": [{"type": "uint256[]"}]},
        {"name": "swapExactTokensForTokens", "type": "function", "stateMutability": "nonpayable", "inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "amountOutMin", "type": "uint256"}, ROUTE, {"name": "to", "type": "address"}, {"name": "deadline", "type": "uint256"}], "outputs": [{"type": "uint256[]"}]}]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", required=True, choices=["base", "bnb"])
    ap.add_argument("--dex", required=True, choices=["uniswap", "aerodrome", "pancake"])
    ap.add_argument("--src", required=True); ap.add_argument("--dst", required=True)
    ap.add_argument("--amount-in", required=True, type=Decimal, help="unidades humanas do token_in")
    ap.add_argument("--slippage-bps", type=int, default=SLIPPAGE_BPS)
    ap.add_argument("--execute", action="store_true"); ap.add_argument("--i-understand-live", action="store_true")
    a = ap.parse_args()
    if (a.chain, a.dex) not in DEX:
        raise SystemExit(f"dex {a.dex} não suportada em {a.chain}")
    if a.src.lower() in STABLES:
        assert_size_ok(a.amount_in)
    from web3 import Web3
    C = Web3.to_checksum_address
    w3 = make_w3(a.chain)
    me = C(load_address())
    tin, din = token(a.chain, a.src); tout, dout = token(a.chain, a.dst)
    qk, rk = DEX[(a.chain, a.dex)]
    router = addr(a.chain, rk)
    for t in (router, tin, tout):
        assert_live_to_reg(w3, a.chain, t)
    amount_in = int(a.amount_in * Decimal(10) ** din)
    plan = {"chain": a.chain, "chain_id": CHAIN_IDS[a.chain], "dex": a.dex, "router": router, "from": me,
            "token_in": tin, "token_out": tout, "amount_in": str(amount_in), "amount_in_human": str(a.amount_in)}
    deadline = int(time.time()) + 600
    if a.dex == "aerodrome":
        r = w3.eth.contract(address=router, abi=AERO)
        fac = addr("base", "aerodrome_pool_factory"); best = None
        # safety: stable (curve) pools só para par stable/stable — pool stable USDC/WETH é ilíquido e mal precificado
        pools = (True,) if (a.src.lower() in STABLES and a.dst.lower() in STABLES) else (False,)
        for stable in pools:
            try:
                o = r.functions.getAmountsOut(amount_in, [(tin, tout, stable, fac)]).call()[-1]
                if o and (best is None or o > best[1]):
                    best = (stable, o)
            except Exception:
                pass
        if not best:
            raise SystemExit("sem quote Aerodrome")
        quoted = best[1]; min_out = quoted * (10_000 - a.slippage_bps) // 10_000
        fn = r.functions.swapExactTokensForTokens(amount_in, min_out, [(tin, tout, best[0], fac)], me, deadline)
        plan.update({"route": f"{a.src}->{a.dst} {'stable' if best[0] else 'volatile'} pool", "quoter_gas_est": None})
    else:
        q = w3.eth.contract(address=addr(a.chain, qk), abi=QUOTER); best = None
        for fee in FEE_TIERS[a.dex]:
            try:
                o = q.functions.quoteExactInputSingle((tin, tout, amount_in, fee, 0)).call()
                if best is None or o[0] > best[1]:
                    best = (fee, int(o[0]), int(o[3]))
            except Exception:
                pass
        if not best:
            raise SystemExit("sem quote v3")
        quoted = best[1]; min_out = quoted * (10_000 - a.slippage_bps) // 10_000
        r = w3.eth.contract(address=router, abi=SR02)
        fn = r.functions.exactInputSingle((tin, tout, best[0], me, amount_in, min_out, 0))
        plan.update({"fee_tier": best[0], "quoter_gas_est": best[2]})
    plan.update({"quoted_out": str(quoted), "quoted_out_human": str(Decimal(quoted) / Decimal(10) ** dout),
                 "min_out": str(min_out), "min_out_human": str(Decimal(min_out) / Decimal(10) ** dout), "slippage_bps": a.slippage_bps,
                 "price_in_per_out": str((Decimal(amount_in) / Decimal(10) ** din) / (Decimal(quoted) / Decimal(10) ** dout))})
    # simulation with state override (balance + allowance + native for gas)
    bal_slot, allow_slot = erc20_slots(w3, tin, me, router)
    ov = {tin: {"stateDiff": {}}, me: {"balance": hex(10 ** 18)}}
    if bal_slot: ov[tin]["stateDiff"][bal_slot] = "0x" + amount_in.to_bytes(32, "big").hex()
    if allow_slot: ov[tin]["stateDiff"][allow_slot] = "0x" + amount_in.to_bytes(32, "big").hex()
    plan["override_slots_found"] = {"balance": bool(bal_slot), "allowance": bool(allow_slot)}
    data = fn._encode_transaction_data()
    txc = {"from": me, "to": router, "data": data, "value": 0}
    try:
        res = w3.eth.call(txc, "latest", ov)
        sim_out = fn.abi_codec if False else None
        dec = w3.codec.decode(["uint256[]"] if a.dex == "aerodrome" else ["uint256"], res)[0]
        sim_out = dec[-1] if a.dex == "aerodrome" else dec
        plan["sim_out"] = str(sim_out); plan["sim_ok"] = sim_out >= min_out
    except Exception as e:
        plan["sim_ok"] = False; plan["sim_err"] = str(e)[:300]
    try:
        g = w3.eth.estimate_gas(txc, "latest", ov); plan["estimate_gas_swap"] = g
    except Exception as e:
        g = None; plan["estimate_gas_err"] = str(e)[:300]
    tc = w3.eth.contract(address=tin, abi=ERC20)
    ad = tc.functions.approve(router, amount_in)._encode_transaction_data()
    try:
        ga = w3.eth.estimate_gas({"from": me, "to": tin, "data": ad}, "latest", {me: {"balance": hex(10 ** 18)}}); plan["estimate_gas_approve"] = ga
    except Exception as e:
        ga = None; plan["estimate_gas_approve_err"] = str(e)[:200]
    if g:
        plan["gas_cost_swap"] = {k: str(v) for k, v in gas_cost(w3, a.chain, g, bytes.fromhex(data[2:]), router).items()}
    if ga:
        plan["gas_cost_approve"] = {k: str(v) for k, v in gas_cost(w3, a.chain, ga, bytes.fromhex(ad[2:]), tin).items()}
    cur_allow = tc.functions.allowance(me, router).call(); bal = tc.functions.balanceOf(me).call()
    plan.update({"wallet_balance_in": str(bal), "allowance_current": str(cur_allow), "native_balance_wei": str(w3.eth.get_balance(me)),
                 "approve_needed": cur_allow < amount_in, "approve_amount_exact": str(amount_in)})
    live = live_allowed(a.execute, a.i_understand_live); plan["dry_run"] = not live
    print(json.dumps(plan, indent=1))
    if not live:
        print("# dry-run: nenhuma tx assinada/enviada", file=sys.stderr); return
    # ---------------- LIVE (never reached without DRY_RUN=0 --execute --i-understand-live) ----------------
    from eth_account import Account
    acct = Account.from_key(load_key())
    if acct.address.lower() != me.lower(): raise SystemExit("chave ≠ wallet.address")
    if not plan["sim_ok"]: raise SystemExit("bloqueado: simulação falhou")
    if bal < amount_in: raise SystemExit("saldo insuficiente")
    nonce = w3.eth.get_transaction_count(me); gp = w3.eth.gas_price
    def send(tx):
        assert_live_to_reg(w3, a.chain, tx["to"])
        s = acct.sign_transaction(tx); h = w3.eth.send_raw_transaction(s.raw_transaction)
        return h.hex(), w3.eth.wait_for_transaction_receipt(h, timeout=180)
    fees = {"gasPrice": gp} if a.chain == "bnb" else {"maxFeePerGas": gp * 2, "maxPriorityFeePerGas": min(gp, w3.to_wei(0.001, "gwei"))}
    if cur_allow != amount_in:
        if cur_allow > 0:
            h, rc = send(tc.functions.approve(router, 0).build_transaction({"from": me, "nonce": nonce, "chainId": CHAIN_IDS[a.chain], "gas": 80000, **fees})); nonce += 1
            if rc.status != 1: raise SystemExit("approve0 falhou")
        assert_exact_approve(amount_in, amount_in)
        h, rc = send(tc.functions.approve(router, amount_in).build_transaction({"from": me, "nonce": nonce, "chainId": CHAIN_IDS[a.chain], "gas": 80000, **fees})); nonce += 1
        if rc.status != 1: raise SystemExit("approve falhou")
    gas = fn.estimate_gas({"from": me})
    h, rc = send(fn.build_transaction({"from": me, "nonce": nonce, "chainId": CHAIN_IDS[a.chain], "gas": int(gas * 1.3), "value": 0, **fees}))
    print(json.dumps({"swap_tx": h, "status": rc.status, "gas_used": rc.gasUsed}, indent=1))

if __name__ == "__main__":
    main()
