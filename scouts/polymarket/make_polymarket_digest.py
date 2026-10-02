#!/usr/bin/env python3
import json
import os
from datetime import datetime
from pathlib import Path

base = Path((os.environ.get("SCOUT_OUT_DIR") or Path(__file__).resolve().parent / "out"))
base.mkdir(parents=True, exist_ok=True)
markets_path = base / "markets.json"
out = base / "latest.md"
try:
    data = json.loads(markets_path.read_text())
except Exception as e:
    out.write_text(f"# Polymarket Scout\n\nErro: {e}\n")
    raise SystemExit(0)

now = datetime.now().strftime("%Y-%m-%d %H:%M")
lines = [
    "# Polymarket Scout digest",
    f"_BRT {now}_",
    "",
    "Alerta only. Zero trade/wallet. Edge ≥~8% → avisar orquestrador (priority).",
    "",
    "## Top por volume 24h (Gamma API)",
    "",
]
if not data:
    lines.append("Sem mercados neste scan.")
else:
    for i, m in enumerate(data[:12], 1):
        yes = m.get("yes")
        try:
            yes_f = float(yes) if yes is not None else None
        except (TypeError, ValueError):
            yes_f = None
        vol = m.get("volume24hr") or 0
        try:
            vol_f = float(vol)
        except (TypeError, ValueError):
            vol_f = 0.0
        liq = m.get("liquidity") or 0
        try:
            liq_f = float(liq)
        except (TypeError, ValueError):
            liq_f = 0.0
        yes_s = f"{yes_f:.3f}" if yes_f is not None else "?"
        # Rough flag: mid-market (0.35–0.65) often where edge hunt lives
        flag = ""
        if yes_f is not None and 0.35 <= yes_f <= 0.65 and vol_f >= 50000:
            flag = " ← candidato edge (mid + vol)"
        lines.append(
            f"{i}. {m.get('question') or '(sem pergunta)'}"
        )
        lines.append(
            f"   YES={yes_s} | vol24h=${vol_f:,.0f} | liq=${liq_f:,.0f}{flag}"
        )
        lines.append(f"   {m.get('url') or ''}")
        lines.append("")
    lines.append("_Agente LLM: cruzar X/news e estimar edge; avisar orquestrador só se |edge|≳8% ou risco forte._")
out.write_text("\n".join(lines) + "\n")
print(out.read_text()[:1800])
