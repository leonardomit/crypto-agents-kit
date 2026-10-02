#!/usr/bin/env python3
import json
import os
from datetime import datetime
from pathlib import Path

base = Path((os.environ.get("SCOUT_OUT_DIR") or Path(__file__).resolve().parent / "out"))
base.mkdir(parents=True, exist_ok=True)
pools_path = base / "pools.json"
out = base / "latest.md"
try:
    data = json.loads(pools_path.read_text())
except Exception as e:
    out.write_text(f"# DeFi Scout\n\nErro lendo pools: {e}\n")
    raise SystemExit(0)

sane = [
    x for x in data
    if (x.get("apyBase") or 0) > 0 and (x.get("apy") or 0) < 500
]
sane.sort(key=lambda x: -(x.get("apyBase") or 0))
now = datetime.now().strftime("%Y-%m-%d %H:%M")
lines = [
    "# DeFi Scout digest",
    f"_BRT {now}_",
    "",
    "## Candidatos (apyBase, APY total <500%)",
    "",
]
if not sane:
    lines.append("Sem sinal A/B sane neste scan (pools com APY farm extremo filtrados).")
else:
    for i, x in enumerate(sane[:5], 1):
        lines.append(
            f"{i}. **{x.get('symbol')}** ({x.get('chain')}/{x.get('project')}) — "
            f"apyBase {float(x.get('apyBase') or 0):.2f}% | "
            f"APY {float(x.get('apy') or 0):.1f}% | "
            f"TVL ${float(x.get('tvlUsd') or 0):,.0f}"
        )
        lines.append(f"   {x.get('url')}")
        lines.append("")
    lines.append("_Alerta only. Size sugerido ≤US$25. Zero trade neste job._")
out.write_text("\n".join(lines) + "\n")
print(out.read_text())
