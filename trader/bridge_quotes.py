#!/usr/bin/env python3
"""Read-only bridge quotes (Across, Relay, LI.FI). NO signing, NO approvals, nothing broadcast."""
import json, os, sys, time, requests
# Endereços PÚBLICOS usados só como user/recipient da cotação (env). Nada é assinado.
EVM = os.environ.get("DEFI_WALLET_ADDRESS", "").strip() or sys.exit("DEFI_WALLET_ADDRESS ausente (ver .env.example)")
SOL = os.environ.get("SOLANA_WALLET_ADDRESS", "").strip() or sys.exit("SOLANA_WALLET_ADDRESS ausente (ver .env.example)")
T = {"arb_usdc": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", "arb_weth": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
     "base_usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "base_weth": "0x4200000000000000000000000000000000000006",
     "bnb_usdt": "0x55d398326f99059fF775485246999027B3197955", "bnb_usdc": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
     "zero": "0x0000000000000000000000000000000000000000", "sol_native_relay": "11111111111111111111111111111111",
     "sol_wsol": "So11111111111111111111111111111111111111112"}
RELAY_SOL = 792703809
LEGS = [
 # name, origin, dest, in_token, out_token, amount_raw, in_dec, out_dec, user, recipient
 ("arb_usdc->base_usdc 10", 42161, 8453, T["arb_usdc"], T["base_usdc"], 10_000_000, 6, 6, EVM, EVM),
 ("arb_usdc->bnb_usdt 3", 42161, 56, T["arb_usdc"], T["bnb_usdt"], 3_000_000, 6, 18, EVM, EVM),
 ("arb_usdc->bnb_usdc 3", 42161, 56, T["arb_usdc"], T["bnb_usdc"], 3_000_000, 6, 18, EVM, EVM),
 ("sol_SOL->base_usdc 0.15", RELAY_SOL, 8453, "SOL", T["base_usdc"], 150_000_000, 9, 6, SOL, EVM),
 ("sol_SOL->bnb_usdt 0.05", RELAY_SOL, 56, "SOL", T["bnb_usdt"], 50_000_000, 9, 18, SOL, EVM),
 ("gas: arb_ETH->base_ETH 0.0003", 42161, 8453, T["zero"], T["zero"], 300_000_000_000_000, 18, 18, EVM, EVM),
 ("gas: arb_usdc->bnb_BNB 1", 42161, 56, T["arb_usdc"], T["zero"], 1_000_000, 6, 18, EVM, EVM),
 ("gas: sol_SOL->base_ETH 0.008", RELAY_SOL, 8453, "SOL", T["zero"], 8_000_000, 9, 18, SOL, EVM),
 ("gas: sol_SOL->bnb_BNB 0.008", RELAY_SOL, 56, "SOL", T["zero"], 8_000_000, 9, 18, SOL, EVM),
]
LIFI_CH = {42161: "ARB", 8453: "BAS", 56: "BSC", RELAY_SOL: "SOL"}
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"

def relay(o, d, ti, to, amt, user, rcpt, topup=False):
    ti = T["sol_native_relay"] if ti == "SOL" else ti
    body = {"user": user, "recipient": rcpt, "originChainId": o, "destinationChainId": d, "originCurrency": ti,
            "destinationCurrency": to, "amount": str(amt), "tradeType": "EXACT_INPUT"}
    if topup: body["topupGas"] = True
    r = S.post("https://api.relay.link/quote", json=body, timeout=30)
    j = r.json()
    if r.status_code != 200: return {"error": str(j)[:250]}
    det = j.get("details", {}); fees = j.get("fees", {})
    return {"out_amount_raw": det.get("currencyOut", {}).get("amount"), "out_usd": det.get("currencyOut", {}).get("amountUsd"),
            "in_usd": det.get("currencyIn", {}).get("amountUsd"), "time_s": det.get("timeEstimate"),
            "fees_usd": {k: (v or {}).get("amountUsd") for k, v in fees.items()}, "total_impact": det.get("totalImpact"),
            "steps": [s.get("id") for s in j.get("steps", [])]}

def across(o, d, ti, to, amt, rcpt, out_dec, in_dec):
    if ti == "SOL": return {"error": "n/a (Across não aceita SOL nativo)"}
    ti2 = T["arb_weth"] if ti == T["zero"] else ti
    to2 = (T["base_weth"] if d == 8453 else None) if to == T["zero"] else to
    if to2 is None: return {"error": "n/a (sem BNB nativo como output no Across)"}
    p = {"inputToken": ti2, "outputToken": to2, "originChainId": o, "destinationChainId": d, "amount": amt, "recipient": rcpt}
    if in_dec != out_dec: p["allowUnmatchedDecimals"] = "true"
    r = S.get("https://app.across.to/api/suggested-fees", params=p, timeout=30); j = r.json()
    if r.status_code != 200: return {"error": str(j)[:250]}
    out = j.get("outputAmount")
    return {"out_amount_raw": out, "total_relay_fee_raw": j.get("totalRelayFee", {}).get("total"),
            "time_s": j.get("estimatedFillTimeSec"), "limits_min_raw": j.get("limits", {}).get("minDeposit"), "isAmountTooLow": j.get("isAmountTooLow")}

def lifi(o, d, ti, to, amt, user, rcpt):
    p = {"fromChain": LIFI_CH[o], "toChain": LIFI_CH[d], "fromToken": "SOL" if ti == "SOL" else ti, "toToken": to,
         "fromAmount": str(amt), "fromAddress": user, "toAddress": rcpt}
    r = S.get("https://li.quest/v1/quote", params=p, timeout=40); j = r.json()
    if r.status_code != 200: return {"error": str(j.get("message", j))[:250]}
    e = j.get("estimate", {})
    return {"tool": j.get("toolDetails", {}).get("name"), "out_amount_raw": e.get("toAmount"), "out_min_raw": e.get("toAmountMin"),
            "out_usd": e.get("toAmountUSD"), "in_usd": e.get("fromAmountUSD"), "time_s": e.get("executionDuration"),
            "fee_costs_usd": sum(float(c.get("amountUSD") or 0) for c in e.get("feeCosts", [])),
            "gas_costs_usd": sum(float(c.get("amountUSD") or 0) for c in e.get("gasCosts", []))}

def main():
    res = {"at": time.strftime("%Y-%m-%d %H:%M:%S %z"), "legs": []}
    for (n, o, d, ti, to, amt, idec, odec, user, rcpt) in LEGS:
        row = {"leg": n, "amount_in_raw": amt, "in_dec": idec, "out_dec": odec}
        for name, f in (("relay", lambda: relay(o, d, ti, to, amt, user, rcpt)), ("across", lambda: across(o, d, ti, to, amt, rcpt, odec, idec)),
                        ("lifi", lambda: lifi(o, d, ti, to, amt, user, rcpt))):
            try: row[name] = f()
            except Exception as e: row[name] = {"error": str(e)[:200]}
            for k in ("out_amount_raw",):
                v = row[name].get(k)
                if v: row[name]["out_human"] = int(v) / 10 ** odec
        res["legs"].append(row)
    # Relay topupGas variant: Arb USDC -> BNB USDT with destination gas
    try: res["relay_topup_arb_usdc_bnb_usdt_3"] = relay(42161, 56, T["arb_usdc"], T["bnb_usdt"], 3_000_000, EVM, EVM, topup=True)
    except Exception as e: res["relay_topup_arb_usdc_bnb_usdt_3"] = {"error": str(e)}
    try: res["relay_topup_arb_usdc_base_usdc_10"] = relay(42161, 8453, T["arb_usdc"], T["base_usdc"], 10_000_000, EVM, EVM, topup=True)
    except Exception as e: res["relay_topup_arb_usdc_base_usdc_10"] = {"error": str(e)}
    out = sys.argv[1] if len(sys.argv) > 1 else "/dev/stdout"
    open(out, "w").write(json.dumps(res, indent=1))
main()
