#!/usr/bin/env python3
"""Server-side market data -> market.json (same-origin) for index.html + btc-onchain.html.

Read-only public APIs, no keys. Per-dataset TTL cache; on failure keeps last good
value (marked stale) and records the error. Route order per dataset:
direct -> optional relay host (ssh+curl, different egress IP; set RELAY_SSH) -> alternative source.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BRT = ZoneInfo("America/Sao_Paulo")
HERE = Path(__file__).resolve().parent
OUT = HERE / "market.json"
CG = "https://api.coingecko.com/api/v3"
# Opcional: relay via outro host com IP de saída diferente (ex.: "ssh -o BatchMode=yes user@relay-host").
# Vazio = sem relay.
import os  # noqa: E402
MINI_SSH = shlex.split(os.environ.get("RELAY_SSH", ""))

COINS = [  # coingecko id, symbol, OKX spot inst, Coinbase product
    ("bitcoin", "btc", "BTC-USDT", "BTC-USD"),
    ("ethereum", "eth", "ETH-USDT", "ETH-USD"),
    ("solana", "sol", "SOL-USDT", "SOL-USD"),
    ("binancecoin", "bnb", "BNB-USDT", None),
    ("ripple", "xrp", "XRP-USDT", "XRP-USD"),
    ("dogecoin", "doge", "DOGE-USDT", "DOGE-USD"),
    ("avalanche-2", "avax", "AVAX-USDT", "AVAX-USD"),
    ("chainlink", "link", "LINK-USDT", "LINK-USD"),
    ("arbitrum", "arb", "ARB-USDT", "ARB-USD"),
]
IDS = ",".join(c[0] for c in COINS)

TTL = {"markets": 180, "global": 300, "btc_chart": 3600, "fng": 1800, "funding": 300,
       "hashrate": 600, "fees": 120, "stables": 3600}


def get_direct(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "defi-dashboard/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def get_via_mini(url, timeout=60):
    if not MINI_SSH:
        raise RuntimeError("relay disabled (RELAY_SSH unset)")
    # one retry after a pause (CoinGecko public tier rate-limits bursts)
    q = shlex.quote(url)
    cmd = (f"for i in 1 2; do out=$(curl -s -m 25 -w '\\n%{{http_code}}' -H 'Accept: application/json' {q}); "
           "code=${out##*$'\\n'}; if [ \"$code\" = 200 ]; then printf '%s' \"${out%$'\\n'*}\"; exit 0; fi; sleep 6; done; "
           "echo \"HTTP $code\" >&2; exit 22")
    r = subprocess.run(MINI_SSH + [cmd], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"mini relay {(r.stderr or '').strip()[-40:] or r.returncode}")
    return json.loads(r.stdout)


def try_routes(url, label, errs, mini=True):
    try:
        return get_direct(url), f"{label} (direct)"
    except Exception as e:
        errs.append(f"{label} direct: {getattr(e, 'code', '') or type(e).__name__}")
    if mini:
        try:
            return get_via_mini(url), f"{label} (via relay)"
        except Exception as e:
            errs.append(f"{label} mini: {type(e).__name__}")
    raise RuntimeError("; ".join(errs))


# ---------- dataset fetchers: return (data, source, notes)
def f_markets(errs):
    try:
        d, src = try_routes(f"{CG}/coins/markets?vs_currency=usd&ids={IDS}&price_change_percentage=24h", "CoinGecko", errs)
        keep = ("id", "symbol", "name", "current_price", "price_change_percentage_24h", "total_volume",
                "market_cap", "high_24h", "low_24h", "last_updated")
        return [{k: x.get(k) for k in keep} for x in d], src
    except Exception:
        pass
    # fallback: OKX spot tickers (one call), then Coinbase stats
    try:
        tick = {t["instId"]: t for t in get_direct("https://www.okx.com/api/v5/market/tickers?instType=SPOT")["data"]}
        out = []
        for cid, sym, okx, _ in COINS:
            t = tick.get(okx)
            if not t:
                continue
            last, op = float(t["last"]), float(t["sodUtc0"] if not t.get("open24h") else t["open24h"])
            out.append({"id": cid, "symbol": sym, "current_price": last,
                        "price_change_percentage_24h": (last / op - 1) * 100 if op else None,
                        "total_volume": float(t.get("volCcy24h") or 0), "market_cap": None,
                        "high_24h": float(t["high24h"]), "low_24h": float(t["low24h"])})
        if out:
            return out, "OKX spot (fallback; USDT pairs, sem market cap)"
    except Exception as e:
        errs.append(f"OKX: {type(e).__name__}")
    out = []
    for cid, sym, _, cb in COINS:
        if not cb:
            continue
        try:
            s = get_direct(f"https://api.exchange.coinbase.com/products/{cb}/stats")
            last, op = float(s["last"]), float(s["open"])
            out.append({"id": cid, "symbol": sym, "current_price": last,
                        "price_change_percentage_24h": (last / op - 1) * 100 if op else None,
                        "total_volume": float(s["volume"]) * last, "market_cap": None,
                        "high_24h": float(s["high"]), "low_24h": float(s["low"])})
        except Exception:
            pass
    if out:
        return out, "Coinbase Exchange (fallback; sem BNB/market cap)"
    raise RuntimeError("all market sources failed")


def f_global(errs):
    try:
        d, src = try_routes(f"{CG}/global", "CoinGecko", errs)
    except Exception:
        g = get_direct("https://api.coinpaprika.com/v1/global")
        e = get_direct("https://api.coinpaprika.com/v1/tickers/eth-ethereum")["quotes"]["USD"]
        tot = float(g["market_cap_usd"])
        return {"data": {"market_cap_percentage": {"btc": g.get("bitcoin_dominance_percentage"),
                                                   "eth": float(e["market_cap"]) / tot * 100 if tot else None},
                         "total_market_cap": {"usd": tot},
                         "market_cap_change_percentage_24h_usd": g.get("market_cap_change_24h")}}, \
            "CoinPaprika global (fallback)"
    g = d.get("data") or {}
    return {"data": {"market_cap_percentage": g.get("market_cap_percentage"),
                     "total_market_cap": {"usd": (g.get("total_market_cap") or {}).get("usd")},
                     "market_cap_change_percentage_24h_usd": g.get("market_cap_change_percentage_24h_usd")}}, src


def f_btc_chart(errs):
    try:  # days=max now requires a CoinGecko key (401); 365d covers SMA350
        d, src = try_routes(f"{CG}/coins/bitcoin/market_chart?vs_currency=usd&days=365&interval=daily", "CoinGecko 365d", errs)
        return {"prices": d.get("prices") or []}, src
    except Exception:
        pass
    k = get_direct("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440")
    rows = next(v for kk, v in k["result"].items() if kk != "last")
    return {"prices": [[int(r[0]) * 1000, float(r[4])] for r in rows][-400:]}, "Kraken OHLC diário XBT/USD (fallback)"


def f_fng(errs):
    d, src = try_routes("https://api.alternative.me/fng/?limit=30", "Alternative.me", errs)
    return {"data": d.get("data") or []}, src


def f_funding(errs):
    try:
        d, src = try_routes("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT", "Binance Futures", errs)
        return {"lastFundingRate": d.get("lastFundingRate"), "markPrice": d.get("markPrice"), "venue": "binance"}, src
    except Exception:
        pass
    d = get_direct("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP")["data"][0]
    return {"lastFundingRate": d.get("fundingRate"), "venue": "okx"}, "OKX BTC-USDT-SWAP (fallback)"


def f_hashrate(errs):
    d, src = try_routes("https://mempool.space/api/v1/mining/hashrate/3d", "mempool.space", errs)
    return {"currentHashrate": d.get("currentHashrate"), "currentDifficulty": d.get("currentDifficulty"),
            "hashrates": (d.get("hashrates") or [])[-3:]}, src


def f_fees(errs):
    return try_routes("https://mempool.space/api/v1/fees/recommended", "mempool.space", errs)


def f_stables(errs):
    d, src = try_routes("https://stablecoins.llama.fi/stablecoincharts/all", "DeFiLlama stablecoins", errs)
    return (d[-1:] if isinstance(d, list) else []), src


FETCHERS = {"markets": f_markets, "global": f_global, "btc_chart": f_btc_chart, "fng": f_fng,
            "funding": f_funding, "hashrate": f_hashrate, "fees": f_fees, "stables": f_stables}


def main():
    try:
        prev = json.loads(OUT.read_text()).get("datasets", {})
    except Exception:
        prev = {}
    now = time.time()
    datasets = {}
    for name, fn in FETCHERS.items():
        p = prev.get(name) or {}
        if p.get("ok") and not p.get("stale") and now - (p.get("fetched_ts") or 0) < TTL[name]:
            datasets[name] = p
            continue
        errs = []
        try:
            data, src = fn(errs)
            datasets[name] = {"ok": True, "stale": False, "data": data, "source": src,
                              "fetched_ts": now,
                              "fetched_at_brt": datetime.now(BRT).strftime("%Y-%m-%d %H:%M:%S"),
                              "ttl_s": TTL[name], "notes": errs or None}
        except Exception as e:
            msg = "; ".join(errs) or f"{type(e).__name__}: {e}"
            if p.get("data") is not None:
                datasets[name] = {**p, "stale": True, "error": msg[:300]}
            else:
                datasets[name] = {"ok": False, "stale": False, "data": None, "source": None,
                                  "error": msg[:300], "fetched_ts": now,
                                  "fetched_at_brt": datetime.now(BRT).strftime("%Y-%m-%d %H:%M:%S"), "ttl_s": TTL[name]}
    out = {"updated_at": datetime.now(BRT).isoformat(timespec="seconds"),
           "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "read_only": True, "datasets": datasets}
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False) + "\n")
    tmp.replace(OUT)
    print(json.dumps({"ok": True, "wrote": str(OUT), "status": {k: (v.get("source") if v.get("ok") and not v.get("stale") else ("STALE " if v.get("stale") else "ERR ") + (v.get("error") or "")[:80]) for k, v in datasets.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
