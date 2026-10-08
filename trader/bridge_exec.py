#!/usr/bin/env python3
"""bridge_exec.py — Relay bridge executor (2026-10-08). DRY-RUN by default.

Usado em produção em 08/10/2026 (3 rotas, teste de ~US$2 por rota antes do valor cheio). Rode em dry-run antes.
Requer: node + `npm install` em trader/relay_verify (SDK oficial @relay-protocol/settlement-sdk) p/ recomputar o orderId.

Live ONLY with: DRY_RUN=0 + --execute + --i-understand-live.
Escopo original: consolidar saldos na Arbitrum (cada rota exige ok humano; bridge NÃO é automática).
Routes (no others):
  eth_to_arb   : Ethereum ETH  -> Arbitrum ETH   (Relay Depository depositNative)
  arb_to_pol   : Arbitrum ETH  -> Polygon POL    (gas top-up, EXACT_OUTPUT)
  pol_usdt_arb : Polygon USDT  -> Arbitrum USDC  (exact approve + Relay Depository depositErc20)

Hard locks:
 1. tx `to` and approval spender must be in the HARDCODED allowlist below AND have non-empty bytecode.
 2. quote destination chain / currency / recipient asserted; minimumAmount must be > 0.
    Depository calldata decoded: selector, depositor == wallet, id == quote requestId, value/token/amount == request.
 3. exact approval only (amount == bridged amount).
 4. steps must be exactly [deposit] or [approve(exact), deposit]; anything else -> abort.
 5. eth_call + estimateGas simulation before signing; per-route USD cost cap.
 6. Arbitrum: abort if LP watcher fired recently / pending nonce mismatch.
Never prints secrets.
"""
from __future__ import annotations
import argparse, json, os, shutil, sys, time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import requests
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_caps import STATE_DIR, load_address  # noqa: E402
WALLET = Web3.to_checksum_address(load_address())  # env DEFI_WALLET_ADDRESS ou $DEFI_STATE_DIR/wallet.address
ZERO = "0x0000000000000000000000000000000000000000"
JOURNAL = STATE_DIR / "positions-journal.json"
WATCH_REPORTS_DIR = STATE_DIR / "reports"  # lp-oor-watch-<id>.json (lp_oor_watch.py)
RELAY_API = "https://api.relay.link"

# --- HARDCODED allowlists -------------------------------------------------------
# Relay Depository v2: same address on Ethereum(1), Polygon(137), Arbitrum(42161).
#   doc: https://docs.relay.link/references/protocol/addresses  (table sourced live from
#        https://api.relay.link/chains -> chains[].protocol.v2.depository), verified 2026-10-08.
#   ABI: https://docs.relay.link/references/protocol/contracts/evm-depository
RELAY_DEPOSITORY = "0x4cd00e387622c35bddb9b4c962c136462338bc31"
TX_TO_ALLOW = {1: {RELAY_DEPOSITORY}, 137: {RELAY_DEPOSITORY}, 42161: {RELAY_DEPOSITORY}}
# Token contracts that may receive an approve() (Polygon USDT PoS, doc: https://polygonscan.com/token/0xc2132d05d31c914a87c6611c10748aeb04b58e8f ;
#   Tether: https://tether.to/en/supported-protocols)
APPROVE_TOKEN_ALLOW = {137: {"0xc2132d05d31c914a87c6611c10748aeb04b58e8f"}}
SPENDER_ALLOW = {137: {RELAY_DEPOSITORY}}
SEL_DEPOSIT_NATIVE = "0x49290c1c"   # depositNative(address depositor, bytes32 id)
SEL_DEPOSIT_ERC20 = "0xe8017952"    # depositErc20(address depositor, address token, uint256 amount, bytes32 id)
SEL_APPROVE = "0x095ea7b3"
PROTO_CHAIN = {1: "ethereum", 137: "polygon", 42161: "arbitrum"}
# Relay ERC20Router (official, https://api.relay.link/chains -> contracts.erc20Router; docs:
#   https://docs.relay.link/references/api/api_resources/contract-addresses) - appears only inside order extraData.
RELAY_ERC20_ROUTER = "0xb92fe925dc43a0ecde6c8b1a2709c170ec4fff4f"
EXTRA_OK = {"0x", "0x" + "0" * 24 + RELAY_ERC20_ROUTER[2:]}
ORDER_ID_JS = HERE / "relay_verify" / "order_id.js"   # uses official @relay-protocol/settlement-sdk getOrderId
# Order verification method: https://docs.relay.link/references/api/api_core_concepts/input-validation
UNLIMITED = 1 << 200

RPCS = {1: ["https://ethereum-rpc.publicnode.com", "https://eth.llamarpc.com"],
        137: ["https://polygon-bor-rpc.publicnode.com", "https://polygon-rpc.com"],
        42161: ["https://arb1.arbitrum.io/rpc", "https://arbitrum-one-rpc.publicnode.com"]}
EXPLORER = {1: "https://etherscan.io/tx/", 137: "https://polygonscan.com/tx/", 42161: "https://arbiscan.io/tx/"}
USDC_ARB = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
USDT_POL = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
ROUTES = {
    "eth_to_arb":   dict(o=1, d=42161, ci=ZERO, co=ZERO, ndec=18, odec=18, trade="EXACT_INPUT", cap_usd=1.5),
    "arb_to_pol":   dict(o=42161, d=137, ci=ZERO, co=ZERO, ndec=18, odec=18, trade="EXACT_OUTPUT", cap_usd=0.5),
    "pol_usdt_arb": dict(o=137, d=42161, ci=USDT_POL, co=USDC_ARB, ndec=6, odec=6, trade="EXACT_INPUT", cap_usd=1.5),
}
ERC20 = [{"name": "balanceOf", "type": "function", "stateMutability": "view", "inputs": [{"name": "a", "type": "address"}], "outputs": [{"type": "uint256"}]},
         {"name": "allowance", "type": "function", "stateMutability": "view", "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}], "outputs": [{"type": "uint256"}]}]

def log(*a): print(*a, flush=True)
def die(msg, ctx=None):
    log("ABORT:", msg); journal({"decision": "ABORT", "reason": msg, **(ctx or {})}); sys.exit(2)

def w3_for(cid):
    last = None
    for u in RPCS[cid]:
        try:
            w = Web3(Web3.HTTPProvider(u, request_kwargs={"timeout": 20}))
            w.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if w.eth.chain_id == cid: return w
        except Exception as e: last = e
    raise SystemExit(f"no RPC for chain {cid}: {last}")

def journal(entry):
    entry = {"when_brt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "source": "bridge_exec.py", **entry}
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(JOURNAL.read_text()) if JOURNAL.exists() else []
        bak = JOURNAL.with_suffix(".json.bak-bridge")
        if JOURNAL.exists(): shutil.copy2(JOURNAL, bak)
        data.append(entry)
        tmp = JOURNAL.with_suffix(".json.tmp"); tmp.write_text(json.dumps(data, indent=1, default=str)); tmp.replace(JOURNAL)
    except Exception as e:
        log("journal write failed:", e)

def prices():
    def cb(p):
        return float(requests.get(f"https://api.coinbase.com/v2/prices/{p}-USD/spot", timeout=15).json()["data"]["amount"])
    return {"ETH": cb("ETH"), "POL": cb("POL")}

def native_price(cid, px): return px["POL"] if cid == 137 else px["ETH"]

def relay_quote(r, amount, slippage_bps):
    body = {"user": WALLET, "recipient": WALLET, "originChainId": r["o"], "destinationChainId": r["d"],
            "originCurrency": r["ci"], "destinationCurrency": r["co"], "amount": str(amount), "tradeType": r["trade"], "includeProtocolData": True}
    if slippage_bps is not None and r["trade"] == "EXACT_INPUT": body["slippageTolerance"] = str(slippage_bps)
    resp = requests.post(f"{RELAY_API}/quote/v2", json=body, timeout=30)
    j = resp.json()
    if resp.status_code != 200: raise SystemExit(f"relay quote error {resp.status_code}: {str(j)[:300]}")
    return j

def word(data, i): return data[10 + 64 * i: 10 + 64 * (i + 1)]
def as_addr(w): return "0x" + w[24:]
def as_int(w): return int(w, 16)

def vm_map():
    vm = {"evm": "ethereum-vm", "svm": "solana-vm", "bvm": "bitcoin-vm", "hypevm": "hyperliquid-vm", "lvm": "lighter-vm",
          "tonvm": "ton-vm", "tvm": "tron-vm", "xrpvm": "xrp-vm"}
    out = {}
    for c in requests.get(f"{RELAY_API}/chains", timeout=30).json()["chains"]:
        pc = ((c.get("protocol") or {}).get("v2") or {}).get("chainId")
        if pc and c.get("vmType") in vm: out[pc] = vm[c["vmType"]]
    return out

def verify_order(r, q, amount_in):
    """Relay protocol-v2 order checks (recipient, chains, currencies, min out, refunds, calls) + recompute orderId."""
    import subprocess
    v2 = ((q.get("protocol") or {}).get("v2")) or die("quote has no protocol.v2 data")
    od = v2["orderData"]
    if len(od.get("inputs", [])) != 1: die("order must have exactly 1 input")
    pay = od["inputs"][0]["payment"]
    if pay["chainId"] != PROTO_CHAIN[r["o"]]: die(f"order payment chain {pay['chainId']}")
    if pay["currency"].lower() != r["ci"].lower(): die("order payment currency mismatch")
    for rf in od["inputs"][0].get("refunds", []):
        if rf["recipient"].lower() != WALLET.lower(): die(f"refund recipient {rf['recipient']} != wallet")
        if rf["chainId"] not in (PROTO_CHAIN[r["o"]], PROTO_CHAIN[r["d"]]): die(f"refund chain {rf['chainId']} unexpected")
        if rf.get("extraData", "0x").lower() not in EXTRA_OK: die("refund extraData unexpected")
    out = od["output"]
    if out["chainId"] != PROTO_CHAIN[r["d"]]: die(f"order output chain {out['chainId']} != {PROTO_CHAIN[r['d']]}")
    if out.get("calls"): die("order output has calls (must be plain transfer)")
    if out.get("extraData", "0x").lower() not in EXTRA_OK: die(f"output extraData unexpected {out.get('extraData')}")
    if len(out.get("payments", [])) != 1: die("order must have exactly 1 output payment")
    op = out["payments"][0]
    if op["recipient"].lower() != WALLET.lower(): die(f"order recipient {op['recipient']} != wallet")
    if op["currency"].lower() != r["co"].lower(): die("order output currency mismatch")
    if int(op.get("minimumAmount") or 0) <= 0: die("order minimumAmount zero/missing")
    if int(out["deadline"]) < time.time() + 60: die("order deadline too close/expired")
    if od.get("fees"): die(f"order has extra fees {od.get('fees')}")
    pd = v2.get("paymentDetails", {})
    if pd.get("depository", "").lower() != RELAY_DEPOSITORY or str(pd.get("amount")) != str(pay["amount"]): die("paymentDetails mismatch")
    res = subprocess.run(["node", str(ORDER_ID_JS)], input=json.dumps({"orderData": od, "chains": vm_map()}),
                         capture_output=True, text=True, timeout=60)
    comp = res.stdout.strip().lower()
    if res.returncode != 0 or not comp.startswith("0x") or comp != v2["orderId"].lower(): die(f"orderId recompute mismatch ({comp} vs {v2['orderId']}) {res.stderr[:200]}")
    return comp, int(pay["amount"]), int(op["minimumAmount"])

def validate(r, q, amount_in):
    """Locks 1-4 on the quote. Returns (approve_item|None, deposit_item, info)."""
    det = q["details"]; cin, cout = det["currencyIn"], det["currencyOut"]
    order_id, order_in, order_min = verify_order(r, q, amount_in)
    if det.get("recipient", "").lower() != WALLET.lower(): die(f"recipient mismatch {det.get('recipient')}")
    if det.get("sender", "").lower() != WALLET.lower(): die(f"sender mismatch {det.get('sender')}")
    if int(cout["currency"]["chainId"]) != r["d"]: die(f"dest chain mismatch {cout['currency']['chainId']} != {r['d']}")
    if int(cin["currency"]["chainId"]) != r["o"]: die("origin chain mismatch")
    if cout["currency"]["address"].lower() != r["co"].lower(): die(f"dest currency mismatch {cout['currency']['address']}")
    if cin["currency"]["address"].lower() != r["ci"].lower(): die("origin currency mismatch")
    min_out = int(cout.get("minimumAmount") or 0); exp_out = int(cout.get("amount") or 0)
    if min_out <= 0 or exp_out <= 0: die("minimumAmount missing/zero")
    if min_out < exp_out * 0.97: die(f"minimumAmount too loose ({min_out} vs {exp_out})")
    in_amt = int(cin["amount"])
    if order_in != in_amt: die(f"order payment amount {order_in} != quote input {in_amt}")
    if order_min != min_out: die(f"order minimumAmount {order_min} != quote minimumAmount {min_out}")
    if r["trade"] == "EXACT_INPUT" and in_amt != amount_in: die(f"input amount mismatch {in_amt} != {amount_in}")
    if r["trade"] == "EXACT_OUTPUT" and min_out < amount_in: die("exact-output min < requested")
    steps = q.get("steps", [])
    ids = [s.get("id") for s in steps]
    if ids not in (["deposit"], ["approve", "deposit"]): die(f"unexpected step layout {ids}")
    for s in steps:
        if s.get("kind") != "transaction" or len(s.get("items", [])) != 1: die(f"step {s.get('id')} not single tx")
    is_erc20 = r["ci"] != ZERO
    if is_erc20 != (ids == ["approve", "deposit"]): die(f"step layout {ids} inconsistent with token type")
    dep_step = steps[-1]; dep = dep_step["items"][0]["data"]; req_id = dep_step.get("requestId", "").lower()
    if int(dep["chainId"]) != r["o"]: die("deposit chainId mismatch")
    if dep.get("from", "").lower() != WALLET.lower(): die("deposit from mismatch")
    if dep["to"].lower() not in TX_TO_ALLOW[r["o"]]: die(f"deposit to {dep['to']} not in hardcoded allowlist")
    data = dep["data"].lower()
    if not is_erc20:
        if data[:10] != SEL_DEPOSIT_NATIVE or len(data) != 10 + 128: die(f"unexpected native calldata {data[:10]}")
        if as_addr(word(data, 0)) != WALLET.lower(): die("depositor mismatch")
        if "0x" + word(data, 1) != order_id: die("deposit id != verified orderId")
        if int(dep["value"]) != in_amt: die("deposit value != input amount")
    else:
        if data[:10] != SEL_DEPOSIT_ERC20 or len(data) != 10 + 256: die(f"unexpected erc20 calldata {data[:10]}")
        if as_addr(word(data, 0)) != WALLET.lower(): die("depositor mismatch")
        if as_addr(word(data, 1)) != r["ci"].lower(): die("deposit token mismatch")
        if as_int(word(data, 2)) != in_amt: die("deposit amount mismatch")
        if "0x" + word(data, 3) != order_id: die("deposit id != verified orderId")
        if int(dep.get("value") or 0) != 0: die("erc20 deposit has value")
    appr = None
    if is_erc20:
        appr = steps[0]["items"][0]["data"]; ad = appr["data"].lower()
        if int(appr["chainId"]) != r["o"]: die("approve chainId mismatch")
        if appr["to"].lower() not in APPROVE_TOKEN_ALLOW.get(r["o"], set()) or appr["to"].lower() != r["ci"].lower(): die("approve token not allowlisted")
        if ad[:10] != SEL_APPROVE or len(ad) != 10 + 128: die("approve calldata unexpected")
        spender = as_addr(word(ad, 0)); amt = as_int(word(ad, 1))
        if spender not in SPENDER_ALLOW.get(r["o"], set()): die(f"spender {spender} not in hardcoded allowlist")
        if amt != in_amt or amt >= UNLIMITED: die(f"approve not exact ({amt} != {in_amt})")
        if int(appr.get("value") or 0) != 0: die("approve has value")
    return appr, dep, {"request_id": req_id, "order_id": order_id, "in": in_amt, "out": exp_out, "min_out": min_out,
                       "in_usd": float(cin.get("amountUsd") or 0), "out_usd": float(cout.get("amountUsd") or 0),
                       "fees_usd": {k: (v or {}).get("amountUsd") for k, v in q.get("fees", {}).items()}}

def bytecode_ok(w3, a):
    code = w3.eth.get_code(Web3.to_checksum_address(a))
    if not code: die(f"eth_getCode empty: {a}")
    return len(code)

def fee_params(w3, cid):
    base = w3.eth.get_block("latest")["baseFeePerGas"]
    if cid == 1:
        tip = min(int(w3.eth.max_priority_fee), 10**9)  # cap tip at 1 gwei
        tip = max(tip, 5 * 10**7)
        return {"maxFeePerGas": int(base * 1.3) + tip, "maxPriorityFeePerGas": tip, "base": base}
    if cid == 137:
        tip = max(int(w3.eth.max_priority_fee), 30 * 10**9)
        return {"maxFeePerGas": base * 2 + tip, "maxPriorityFeePerGas": tip, "base": base}
    return {"maxFeePerGas": base * 2, "maxPriorityFeePerGas": 0, "base": base}

def tx_from(item, w3, cid, fees, gas, nonce):
    return {"from": WALLET, "to": Web3.to_checksum_address(item["to"]), "data": item["data"], "value": int(item.get("value") or 0),
            "chainId": cid, "gas": gas, "nonce": nonce, "type": 2,
            "maxFeePerGas": fees["maxFeePerGas"], "maxPriorityFeePerGas": fees["maxPriorityFeePerGas"]}

def simulate(w3, item, overrides=None):
    call = {"from": WALLET, "to": Web3.to_checksum_address(item["to"]), "data": item["data"], "value": int(item.get("value") or 0)}
    if overrides:
        w3.eth.call(call, "latest", overrides); return None
    w3.eth.call(call, "latest")
    return w3.eth.estimate_gas(call)

def arb_guard(w3):
    import subprocess
    if subprocess.run(["pgrep", "-f", "lp_exit.py"], capture_output=True).returncode == 0:
        die("lp_exit.py is running right now (watcher fired); wait for it")
    for rep in sorted(WATCH_REPORTS_DIR.glob("lp-oor-watch-*.json")):
        try:
            st = json.loads(rep.read_text())
            if st.get("status") in ("EXIT_EXECUTED", "EXIT_FAILED") and time.time() - rep.stat().st_mtime < 900:
                die("LP watcher fired <15min ago; check its tx first")
        except json.JSONDecodeError: die(f"watch report unreadable (mid-write?) {rep.name}")
    latest = w3.eth.get_transaction_count(WALLET, "latest"); pend = w3.eth.get_transaction_count(WALLET, "pending")
    if latest != pend: die(f"Arbitrum has a pending tx (latest {latest} != pending {pend}); wait")
    return pend

def send(w3, acct, tx, label, ctx):
    signed = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
    if not h.startswith("0x"): h = "0x" + h
    log(f"{label} sent: {EXPLORER[tx['chainId']]}{h}")
    rc = w3.eth.wait_for_transaction_receipt(h, timeout=600, poll_latency=3)
    fee = rc["gasUsed"] * rc["effectiveGasPrice"]
    ok = rc["status"] == 1
    journal({"decision": f"LIVE_{label.upper()}", "tx": h, "status": rc["status"], "gas_used": rc["gasUsed"], "fee_wei": fee, **ctx})
    log(f"{label} receipt status={rc['status']} gasUsed={rc['gasUsed']} fee_native={fee/1e18:.8f}")
    if not ok: die(f"{label} reverted {h}", ctx)
    return h, fee

def wait_relay(req_id, timeout=900):
    t0 = time.time(); last = None
    while time.time() - t0 < timeout:
        try:
            j = requests.get(f"{RELAY_API}/intents/status/v3", params={"requestId": req_id}, timeout=20).json()
            last = j
            if j.get("status") in ("success",): return j
            if j.get("status") in ("failure", "refund", "refunded"): die(f"relay status {j.get('status')}: {j}")
        except Exception as e: last = str(e)
        time.sleep(5)
    die(f"relay fill timeout; last={last}")

def dest_balance(r):
    w = w3_for(r["d"])
    if r["co"] == ZERO: return w.eth.get_balance(WALLET)
    return w.eth.contract(address=Web3.to_checksum_address(r["co"]), abi=ERC20).functions.balanceOf(WALLET).call()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", required=True, choices=ROUTES)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--amount", help="raw units (input for EXACT_INPUT, output for EXACT_OUTPUT)")
    g.add_argument("--max", action="store_true", help="native eth_to_arb: balance minus gas for this tx")
    ap.add_argument("--slippage-bps", type=int, default=50)
    ap.add_argument("--cap-usd", type=float)
    ap.add_argument("--execute", action="store_true"); ap.add_argument("--i-understand-live", action="store_true")
    a = ap.parse_args()
    r = ROUTES[a.route]; cap = a.cap_usd if a.cap_usd is not None else r["cap_usd"]
    live = os.environ.get("DRY_RUN", "1") in ("0", "false", "False", "no") and a.execute and a.i_understand_live
    w3 = w3_for(r["o"]); px = prices(); npx = native_price(r["o"], px)
    nonce = arb_guard(w3) if r["o"] == 42161 else w3.eth.get_transaction_count(WALLET, "pending")
    if r["o"] != 42161 and nonce != w3.eth.get_transaction_count(WALLET, "latest"): die("pending tx on origin chain")
    fees = fee_params(w3, r["o"])
    bal = w3.eth.get_balance(WALLET)
    if a.max:
        if a.route != "eth_to_arb": die("--max only for eth_to_arb")
        gas_lim = 36000
        amount = bal - gas_lim * fees["maxFeePerGas"]
        if amount <= 0: die("balance below gas buffer")
    else:
        amount = int(a.amount)
    q = relay_quote(r, amount, a.slippage_bps)
    appr, dep, info = validate(r, q, amount)
    ctx = {"route": a.route, "live": live, "request_id": info["request_id"], "order_id": info["order_id"], "amount_in_raw": info["in"],
           "expected_out_raw": info["out"], "min_out_raw": info["min_out"], "relay_fees_usd": info["fees_usd"],
           "doc": "https://docs.relay.link/references/protocol/addresses"}
    code_len = {dep["to"]: bytecode_ok(w3, dep["to"])}
    if appr: code_len[appr["to"]] = bytecode_ok(w3, appr["to"]); code_len["spender"] = bytecode_ok(w3, RELAY_DEPOSITORY)
    ctx["bytecode_len"] = code_len
    # simulation
    if appr:
        tok = w3.eth.contract(address=Web3.to_checksum_address(r["ci"]), abi=ERC20)
        tbal = tok.functions.balanceOf(WALLET).call()
        if tbal < info["in"]: die(f"token balance {tbal} < {info['in']}")
        g_appr = simulate(w3, appr)
        cur_allow = tok.functions.allowance(WALLET, Web3.to_checksum_address(RELAY_DEPOSITORY)).call()
        if cur_allow >= info["in"]:
            g_dep = simulate(w3, dep)
        else:
            from lib_chains import erc20_slots
            _, slot = erc20_slots(w3, Web3.to_checksum_address(r["ci"]), WALLET, Web3.to_checksum_address(RELAY_DEPOSITORY))
            if not slot: die("could not locate allowance slot for deposit simulation")
            simulate(w3, dep, {Web3.to_checksum_address(r["ci"]): {"stateDiff": {slot: "0x" + info["in"].to_bytes(32, "big").hex()}}})
            g_dep = int(dep.get("gas") or 130000)
        gas_units = [int(g_appr * 1.25), int(g_dep * 1.25)]
    else:
        g_dep = simulate(w3, dep); gas_units = [int(g_dep * 1.15) if not a.max else max(int(g_dep * 1.1), 0)]
        if a.max and gas_units[0] > 36000: die(f"gas estimate {g_dep} exceeds --max buffer")
        if a.max: gas_units = [36000]
    est_gas_native = sum(gu for gu in gas_units) * (fees["base"] + fees["maxPriorityFeePerGas"])
    worst_gas_native = sum(gas_units) * fees["maxFeePerGas"]
    if r["ci"] == ZERO and info["in"] + worst_gas_native > bal: die("insufficient native for value+gas")
    if r["ci"] != ZERO and worst_gas_native > bal: die(f"insufficient native gas on origin ({bal} < {worst_gas_native})")
    gas_usd = est_gas_native / 1e18 * npx
    # bridge fee in USD from Relay's own valuation (in_usd - out_usd)
    bridge_usd = max(info["in_usd"] - info["out_usd"], 0.0)
    total_usd = gas_usd + bridge_usd
    ctx.update({"gas_units": gas_units, "est_gas_usd": round(gas_usd, 4), "bridge_fee_usd": round(bridge_usd, 4), "total_cost_usd": round(total_usd, 4),
                "in_usd": info["in_usd"], "out_usd": info["out_usd"], "eth_usd": px["ETH"], "pol_usd": px["POL"]})
    log(json.dumps({k: v for k, v in ctx.items()}, default=str, indent=1))
    if total_usd > cap: die(f"cost US${total_usd:.3f} > cap US${cap}", ctx)
    if not live:
        journal({"decision": "DRY_RUN_OK", **ctx}); log("DRY-RUN OK (nothing signed)"); return
    # ---- LIVE ----
    from eth_account import Account
    from lib_caps import load_key
    acct = Account.from_key(load_key())
    if acct.address.lower() != WALLET.lower(): die("key/address mismatch")
    before = dest_balance(r)
    hashes = {}
    if appr:
        h, f = send(w3, acct, tx_from(appr, w3, r["o"], fees, gas_units[0], nonce), "approve", ctx); hashes["approve"] = h; nonce += 1
        allow = w3.eth.contract(address=Web3.to_checksum_address(r["ci"]), abi=ERC20).functions.allowance(WALLET, Web3.to_checksum_address(RELAY_DEPOSITORY)).call()
        if allow != info["in"]: die(f"post-approve allowance {allow} != {info['in']}", ctx)
        simulate(w3, dep)  # real simulation now that allowance exists
        fees = fee_params(w3, r["o"])
    if r["o"] == 42161: nonce = arb_guard(w3)
    h, f = send(w3, acct, tx_from(dep, w3, r["o"], fees, gas_units[-1], nonce), "deposit", ctx); hashes["deposit"] = h
    st = wait_relay(info["request_id"])
    time.sleep(4)
    after = dest_balance(r)
    recv = after - before
    res = {"decision": "LIVE_DONE", **ctx, "txs": hashes, "relay_status": st.get("status"), "dest_tx": st.get("txHashes"),
           "dest_balance_before": before, "dest_balance_after": after, "received_raw": recv}
    journal(res); log(json.dumps(res, default=str, indent=1))
    if recv < info["min_out"]: log(f"WARNING: received {recv} < min_out {info['min_out']} (balance delta may include other flows)")

if __name__ == "__main__":
    main()
