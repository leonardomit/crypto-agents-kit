#!/bin/bash
# 2026-10-02: + change5m/change6h/volume1h/txns1h no raw (p/ filtro de máxima 1h do digest).
# 2026-09-29: + ethereum (token-pairs por endereço) e bsc; busca filtra chain + símbolo antes de pegar top 6.
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
python3 <<'PY'
import json, urllib.request, urllib.parse, time, datetime
queries = {
  "solana": ["POPCAT", "MEW"],
  "base": ["BRETT", "DEGEN", "TOSHI", "HIGHER"],
  "arbitrum": ["ARB", "GMX", "PENDLE", "MAGIC"],
  "bsc": ["CAKE", "FLOKI", "BABYDOGE", "TST"],
}
# busca por nome na Ethereum volta poluída; usa endereço do token (verificado 29/09)
eth_tokens = {
  "PEPE": "0x6982508145454Ce325dDbE47a25d4ec3d2311933",
  "SHIB": "0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE",
  "MOG": "0xaaeE1A9723aaDB7afA2810263653A34bA2C21C7a",
  "SPX": "0xE0f63A424a4439cBE457D80E4f4b51aD25b2c56C",
  "FLOKI": "0xcf0C122c6b73ff809C693DB761e7BaeBe62b6a2E",
}
UA = {"User-Agent": "crypto-agents-kit-meme-scout/1.0"}
out = {"fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "pairs": [], "errors": []}

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.loads(r.read().decode())

def add(chain, p):
    out["pairs"].append({
        "chain": chain,
        "pair": p.get("pairAddress"),
        "base": (p.get("baseToken") or {}).get("symbol"),
        "baseAddress": (p.get("baseToken") or {}).get("address"),
        "quote": (p.get("quoteToken") or {}).get("symbol"),
        "priceUsd": p.get("priceUsd"),
        "liquidityUsd": float((p.get("liquidity") or {}).get("usd") or 0),
        "volume24h": float((p.get("volume") or {}).get("h24") or 0),
        "change1h": float((p.get("priceChange") or {}).get("h1") or 0),
        "change24h": (p.get("priceChange") or {}).get("h24"),
        # 2026-10-02: campos extras (mesma resposta, custo zero) p/ estimar máxima 1h no digest
        "change5m": (p.get("priceChange") or {}).get("m5"),
        "change6h": (p.get("priceChange") or {}).get("h6"),
        "volume1h": (p.get("volume") or {}).get("h1"),
        "txns1h": (p.get("txns") or {}).get("h1"),
        "url": p.get("url"),
        "dex": p.get("dexId"),
    })

def pick(ps, chain, sym):
    ps = [p for p in ps if (p.get("chainId") or "").lower() == chain
          and ((p.get("baseToken") or {}).get("symbol") or "").upper().lstrip("$") == sym.upper()]
    ps.sort(key=lambda p: -float((p.get("liquidity") or {}).get("usd") or 0))
    if not ps:
        return []
    # só o token canônico: o endereço do pool mais líquido (evita cópias com o mesmo ticker)
    canon = ((ps[0].get("baseToken") or {}).get("address") or "").lower()
    ps = [p for p in ps if ((p.get("baseToken") or {}).get("address") or "").lower() == canon]
    return ps[:6]

for chain, qlist in queries.items():
    for q in qlist:
        try:
            for p in pick(get("https://api.dexscreener.com/latest/dex/search?q=" + urllib.parse.quote(q)).get("pairs") or [], chain, q):
                add(chain, p)
        except Exception as e:
            out["errors"].append(f"{chain}/{q}: {type(e).__name__}: {e}")
        time.sleep(0.2)
# busca por nome não traz o pool principal de BONK/WIF; usa endereço
sol_tokens = {
  "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
  "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
}
for chain, toks in (("ethereum", eth_tokens), ("solana", sol_tokens)):
    for sym, addr in toks.items():
        try:
            for p in pick(get(f"https://api.dexscreener.com/token-pairs/v1/{chain}/" + addr) or [], chain, sym):
                add(chain, p)
        except Exception as e:
            out["errors"].append(f"{chain}/{sym}: {type(e).__name__}: {e}")
        time.sleep(0.2)

seen = set(); uniq = []
for p in out["pairs"]:
    k = (p.get("chain"), p.get("pair"))
    if k in seen: continue
    seen.add(k); uniq.append(p)
out["pairs"] = uniq
print(json.dumps(out))
PY
