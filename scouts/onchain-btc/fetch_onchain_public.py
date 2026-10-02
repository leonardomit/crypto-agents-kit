#!/usr/bin/env python3
"""Public BTC/crypto snapshot for Hermes on-chain digest. No secrets. Never invents."""
import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path((os.environ.get("SCOUT_OUT_DIR") or Path(__file__).resolve().parent / "out"))
BASE.mkdir(parents=True, exist_ok=True)
out_json = BASE / "snapshot.json"
out_md = BASE / "latest.md"

def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "crypto-agents-kit-onchain/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

snap = {"when_brt": datetime.now().strftime("%Y-%m-%d %H:%M"), "ok": True, "metrics": {}}
m = snap["metrics"]

try:
    cg = get(
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin,ethereum,solana,binancecoin,ripple,dogecoin,avalanche-2,chainlink,arbitrum"
        "&vs_currencies=usd&include_24hr_change=true"
    )
    m["prices"] = cg
except Exception as e:
    m["prices_error"] = str(e)

try:
    fg = get("https://api.alternative.me/fng/?limit=1")
    m["fear_greed"] = fg.get("data", [{}])[0]
except Exception as e:
    m["fear_greed_error"] = str(e)

try:
    # DefiLlama BTC/ETH dominance-ish via chains TVL
    tvls = get("https://api.llama.fi/v2/chains")
    top = sorted(tvls, key=lambda x: -(x.get("tvl") or 0))[:8]
    m["defi_tvl_top"] = [{"name": x.get("name"), "tvl": x.get("tvl")} for x in top]
except Exception as e:
    m["defi_tvl_error"] = str(e)

try:
    # mempool.space fees
    fees = get("https://mempool.space/api/v1/fees/recommended")
    m["mempool_fees"] = fees
except Exception as e:
    m["mempool_fees_error"] = str(e)

out_json.write_text(json.dumps(snap, indent=2))

# Markdown skeleton — agente LLM enriquece; orquestrador pode publicar este esqueleto se o agente atrasar
prices = m.get("prices") or {}
fg = m.get("fear_greed") or {}
lines = [
    "# Relatório on-chain / mercado (snapshot público)",
    f"_BRT {snap['when_brt']}_",
    "",
    "## Preços (CoinGecko)",
]
for key, label in [
    ("bitcoin", "BTC"), ("ethereum", "ETH"), ("solana", "SOL"),
    ("binancecoin", "BNB"), ("ripple", "XRP"), ("dogecoin", "DOGE"),
    ("avalanche-2", "AVAX"), ("chainlink", "LINK"), ("arbitrum", "ARB"),
]:
    p = prices.get(key) or {}
    if p:
        lines.append(
            f"- **{label}**: ${p.get('usd'):,} | 24h {p.get('usd_24h_change'):+.2f}%"
            if p.get("usd") is not None else f"- **{label}**: Dado atual não confirmado"
        )
    else:
        lines.append(f"- **{label}**: Dado atual não confirmado")

lines += [
    "",
    "## Fear & Greed",
    f"- Valor: {fg.get('value', 'Dado atual não confirmado')} ({fg.get('value_classification', '')})",
    "",
    "## Mempool fees (sat/vB)",
    f"- {json.dumps(m.get('mempool_fees') or 'Dado atual não confirmado')}",
    "",
    "## DeFi TVL top (DefiLlama)",
]
for t in (m.get("defi_tvl_top") or [])[:6]:
    lines.append(f"- {t.get('name')}: ${t.get('tvl'):,.0f}" if t.get("tvl") else f"- {t}")

lines += [
    "",
    "## Métricas on-chain profundas (MVRV, NUPL, SOPR, etc.)",
    "Dado atual não confirmado neste snapshot HTTP — Hermes deve completar via fontes públicas ou marcar não confirmado.",
    "",
    "_Alerta only. Avisar orquestrador se sinal entrada/saída ≠ inexistente._",
]
out_md.write_text("\n".join(lines) + "\n")
print(out_md.read_text()[:1500])
