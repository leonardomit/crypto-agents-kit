#!/usr/bin/env python3
"""Lending supply multi-chain (Aave v3 Base/BNB/Arbitrum; Venus core BNB). DRY-RUN DEFAULT.

Hard rules:
- Pool resolvido via PoolAddressesProvider.getPool() E tem que bater com chains.json verificado
- eth_getCode + allowlist antes de qualquer live; approve EXATO; cap US$25
- simulação eth_call + estimateGas com state-override (saldo/allowance)
- live só com DRY_RUN=0 + --execute + --i-understand-live
Uso:
  python aave_supply_multi.py --chain base --asset usdc --amount 10
  python aave_supply_multi.py --chain bnb  --asset usdt --amount 10 [--protocol venus]
"""
from __future__ import annotations
import argparse, json, sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_caps import assert_size_ok, load_address, load_key  # noqa
from lib_chains import (CHAIN_IDS, addr, assert_exact_approve, assert_live_to_reg, erc20_slots,
                        gas_cost, live_allowed, make_w3, token)

PROV = [{"inputs": [], "name": "getPool", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"}]
POOL = [{"inputs": [{"name": "asset", "type": "address"}, {"name": "amount", "type": "uint256"}, {"name": "onBehalfOf", "type": "address"}, {"name": "referralCode", "type": "uint16"}],
         "name": "supply", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [{"name": "asset", "type": "address"}], "name": "getReserveData", "stateMutability": "view", "type": "function",
         "outputs": [{"components": [{"name": "configuration", "type": "uint256"}, {"name": "liquidityIndex", "type": "uint128"}, {"name": "currentLiquidityRate", "type": "uint128"},
           {"name": "variableBorrowIndex", "type": "uint128"}, {"name": "currentVariableBorrowRate", "type": "uint128"}, {"name": "currentStableBorrowRate", "type": "uint128"},
           {"name": "lastUpdateTimestamp", "type": "uint40"}, {"name": "id", "type": "uint16"}, {"name": "aTokenAddress", "type": "address"}, {"name": "stableDebtTokenAddress", "type": "address"},
           {"name": "variableDebtTokenAddress", "type": "address"}, {"name": "interestRateStrategyAddress", "type": "address"}, {"name": "accruedToTreasury", "type": "uint128"},
           {"name": "unbacked", "type": "uint128"}, {"name": "isolationModeTotalDebt", "type": "uint128"}], "type": "tuple"}]}]
VT = [{"name": "mint", "type": "function", "stateMutability": "nonpayable", "inputs": [{"name": "a", "type": "uint256"}], "outputs": [{"type": "uint256"}]},
      {"name": "supplyRatePerBlock", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint256"}]},
      {"name": "blocksOrSecondsPerYear", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint256"}]}]
ERC20 = [{"name": "approve", "type": "function", "stateMutability": "nonpayable", "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}], "outputs": [{"type": "bool"}]},
         {"name": "allowance", "type": "function", "stateMutability": "view", "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}], "outputs": [{"type": "uint256"}]},
         {"name": "balanceOf", "type": "function", "stateMutability": "view", "inputs": [{"name": "a", "type": "address"}], "outputs": [{"type": "uint256"}]}]
ATOK = {("base", "usdc"): "ausdc_aave", ("bnb", "usdt"): "ausdt_aave"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", required=True, choices=["base", "bnb"])
    ap.add_argument("--asset", required=True); ap.add_argument("--amount", required=True, type=Decimal)
    ap.add_argument("--protocol", default="aave", choices=["aave", "venus"])
    ap.add_argument("--execute", action="store_true"); ap.add_argument("--i-understand-live", action="store_true")
    a = ap.parse_args()
    assert_size_ok(a.amount)
    from web3 import Web3
    C = Web3.to_checksum_address
    w3 = make_w3(a.chain); me = C(load_address())
    asset, dec = token(a.chain, a.asset); amount = int(a.amount * Decimal(10) ** dec)
    assert_live_to_reg(w3, a.chain, asset)
    plan = {"chain": a.chain, "protocol": a.protocol, "asset": asset, "amount": str(amount), "amount_human": str(a.amount), "from": me}
    if a.protocol == "aave":
        prov = addr(a.chain, "aave_v3_pool_addresses_provider"); assert_live_to_reg(w3, a.chain, prov)
        pool = w3.eth.contract(address=prov, abi=PROV).functions.getPool().call()
        if pool.lower() != addr(a.chain, "aave_v3_pool").lower():
            raise SystemExit(f"bloqueado: getPool {pool} ≠ registro")
        assert_live_to_reg(w3, a.chain, pool)
        pc = w3.eth.contract(address=pool, abi=POOL)
        rd = pc.functions.getReserveData(asset).call()
        exp_a = addr(a.chain, ATOK[(a.chain, a.asset.lower())]) if (a.chain, a.asset.lower()) in ATOK else None
        if exp_a and rd[8].lower() != exp_a.lower():
            raise SystemExit("bloqueado: aToken ≠ registro")
        apr = Decimal(rd[2]) / Decimal(10) ** 27
        plan.update({"pool": pool, "pool_resolved_via": "getPool() == chains.json", "aToken": rd[8],
                     "supply_apr_pct": f"{apr*100:.3f}", "supply_apy_pct": f"{((1+apr/31536000)**31536000-1)*100:.3f}"})
        target = pool; fn = pc.functions.supply(asset, amount, me, 0); ret_t = []
    else:
        vt = addr("bnb", "vusdt_venus") if a.asset.lower() == "usdt" else None
        if not vt: raise SystemExit("venus: só usdt no registro")
        assert_live_to_reg(w3, a.chain, vt)
        vc = w3.eth.contract(address=vt, abi=VT)
        r = vc.functions.supplyRatePerBlock().call()
        try: bpy = vc.functions.blocksOrSecondsPerYear().call()
        except Exception: bpy = None
        plan.update({"vToken": vt, "supplyRatePerBlock": str(r), "blocks_per_year_onchain": bpy})
        if bpy:
            rate = Decimal(r) / Decimal(10) ** 18
            plan["supply_apr_pct"] = f"{rate*bpy*100:.3f}"; plan["supply_apy_pct_daily_comp"] = f"{((1+rate*bpy/365)**365-1)*100:.3f}"
        target = vt; fn = vc.functions.mint(amount); ret_t = ["uint256"]
    bal_slot, allow_slot = erc20_slots(w3, asset, me, target)
    ov = {asset: {"stateDiff": {}}, me: {"balance": hex(10 ** 18)}}
    for s in (bal_slot, allow_slot):
        if s: ov[asset]["stateDiff"][s] = "0x" + amount.to_bytes(32, "big").hex()
    plan["override_slots_found"] = {"balance": bool(bal_slot), "allowance": bool(allow_slot)}
    data = fn._encode_transaction_data(); txc = {"from": me, "to": target, "data": data, "value": 0}
    try:
        res = w3.eth.call(txc, "latest", ov)
        plan["sim_ok"] = True
        if ret_t:
            err = w3.codec.decode(ret_t, res)[0]; plan["venus_mint_err_code"] = err; plan["sim_ok"] = err == 0
    except Exception as e:
        plan["sim_ok"] = False; plan["sim_err"] = str(e)[:300]
    try:
        g = w3.eth.estimate_gas(txc, "latest", ov); plan["estimate_gas_supply"] = g
        plan["gas_cost_supply"] = {k: str(v) for k, v in gas_cost(w3, a.chain, g, bytes.fromhex(data[2:]), target).items()}
    except Exception as e:
        plan["estimate_gas_err"] = str(e)[:300]
    tc = w3.eth.contract(address=asset, abi=ERC20)
    ad = tc.functions.approve(target, amount)._encode_transaction_data()
    try:
        ga = w3.eth.estimate_gas({"from": me, "to": asset, "data": ad}, "latest", {me: {"balance": hex(10 ** 18)}}); plan["estimate_gas_approve"] = ga
        plan["gas_cost_approve"] = {k: str(v) for k, v in gas_cost(w3, a.chain, ga, bytes.fromhex(ad[2:]), asset).items()}
    except Exception as e:
        plan["estimate_gas_approve_err"] = str(e)[:200]
    bal = tc.functions.balanceOf(me).call(); cur = tc.functions.allowance(me, target).call()
    plan.update({"wallet_balance": str(bal), "allowance_current": str(cur), "approve_amount_exact": str(amount)})
    live = live_allowed(a.execute, a.i_understand_live); plan["dry_run"] = not live
    print(json.dumps(plan, indent=1))
    if not live:
        print("# dry-run: nenhuma tx assinada/enviada", file=sys.stderr); return
    # ---------------- LIVE ----------------
    from eth_account import Account
    acct = Account.from_key(load_key())
    if acct.address.lower() != me.lower(): raise SystemExit("chave ≠ wallet.address")
    if not plan["sim_ok"] or bal < amount: raise SystemExit("bloqueado: sim falhou ou saldo insuficiente")
    gp = w3.eth.gas_price; nonce = w3.eth.get_transaction_count(me)
    fees = {"gasPrice": gp} if a.chain == "bnb" else {"maxFeePerGas": gp * 2, "maxPriorityFeePerGas": min(gp, w3.to_wei(0.001, "gwei"))}
    def send(tx):
        assert_live_to_reg(w3, a.chain, tx["to"])
        s = acct.sign_transaction(tx); h = w3.eth.send_raw_transaction(s.raw_transaction)
        return h.hex(), w3.eth.wait_for_transaction_receipt(h, timeout=180)
    if cur != amount:
        if cur > 0:
            h, r = send(tc.functions.approve(target, 0).build_transaction({"from": me, "nonce": nonce, "chainId": CHAIN_IDS[a.chain], "gas": 80000, **fees})); nonce += 1
        assert_exact_approve(amount, amount)
        h, r = send(tc.functions.approve(target, amount).build_transaction({"from": me, "nonce": nonce, "chainId": CHAIN_IDS[a.chain], "gas": 80000, **fees})); nonce += 1
        if r.status != 1: raise SystemExit("approve falhou")
    gas = fn.estimate_gas({"from": me})
    h, r = send(fn.build_transaction({"from": me, "nonce": nonce, "chainId": CHAIN_IDS[a.chain], "gas": int(gas * 1.3), **fees}))
    print(json.dumps({"supply_tx": h, "status": r.status, "gas_used": r.gasUsed}, indent=1))

if __name__ == "__main__":
    main()
