#!/usr/bin/env python3
"""DeFi lending scout — DefiLlama yields (HTTP público, read-only, alerta only).

Varre yields.llama.fi/pools e lista os melhores supplies de stablecoin em protocolos
de lending "blue chip" nas chains configuradas. Nunca opera, nunca toca wallet.

Env (todos opcionais):
  LENDING_CHAINS       default "Arbitrum,Base,Optimism,Ethereum"
  LENDING_PROJECTS     default "aave-v3,compound-v3,morpho-blue,spark,fluid-lending,euler-v2"
  LENDING_MIN_TVL_USD  default 10000000
  LENDING_MAX_APY      default 40   (acima disso = provável farm/incentivo insustentável)
  LENDING_MIN_APY      default 3
  LENDING_SKIP_APY     default 5    (abaixo disso não vale gas p/ ticket pequeno)
  SCOUT_OUT_DIR        default ./out
Saída: $SCOUT_OUT_DIR/lending-latest.json + lending-latest.md
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path((os.environ.get("SCOUT_OUT_DIR") or Path(__file__).resolve().parent / "out"))
CHAINS = [c.strip() for c in os.environ.get("LENDING_CHAINS", "Arbitrum,Base,Optimism,Ethereum").split(",") if c.strip()]
PROJECTS = [p.strip() for p in os.environ.get(
    "LENDING_PROJECTS", "aave-v3,compound-v3,morpho-blue,spark,fluid-lending,euler-v2").split(",") if p.strip()]
MIN_TVL = float(os.environ.get("LENDING_MIN_TVL_USD", "10000000"))
MAX_APY = float(os.environ.get("LENDING_MAX_APY", "40"))
MIN_APY = float(os.environ.get("LENDING_MIN_APY", "3"))
SKIP_APY = float(os.environ.get("LENDING_SKIP_APY", "5"))
TZ = ZoneInfo(os.environ.get("TZ_REPORT", "America/Sao_Paulo"))


def get(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": "crypto-agents-kit-lending-scout/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(TZ)
    data = get("https://yields.llama.fi/pools").get("data", [])
    rows = []
    for p in data:
        if p.get("chain") not in CHAINS or p.get("project") not in PROJECTS:
            continue
        if not p.get("stablecoin"):
            continue
        tvl, apy = float(p.get("tvlUsd") or 0), float(p.get("apy") or 0)
        if tvl < MIN_TVL or not (MIN_APY <= apy <= MAX_APY):
            continue
        rows.append({
            "project": p.get("project"), "chain": p.get("chain"), "symbol": p.get("symbol"),
            "apy": apy, "apyBase": p.get("apyBase"), "apyReward": p.get("apyReward"),
            "apyMean30d": p.get("apyMean30d"), "tvlUsd": tvl, "pool": p.get("pool"),
            "url": f"https://defillama.com/yields/pool/{p.get('pool')}",
        })
    # prioriza apyBase (orgânico) e consistência 30d
    rows.sort(key=lambda x: -((x.get("apyBase") or 0) + 0.5 * (x.get("apyMean30d") or 0)))
    top = rows[:10]
    actionable = [r for r in top if (r.get("apyBase") or 0) >= SKIP_APY]
    out = {"when": now.isoformat(), "filters": {"chains": CHAINS, "projects": PROJECTS, "min_tvl": MIN_TVL,
           "apy_range": [MIN_APY, MAX_APY], "skip_below": SKIP_APY}, "top": top, "actionable": bool(actionable)}
    (OUT / "lending-latest.json").write_text(json.dumps(out, indent=2))
    lines = ["# Lending Scout (DefiLlama)", f"_{now:%Y-%m-%d %H:%M} BRT_", "",
             f"- ACTIONABLE: {'true' if actionable else 'false'} (apyBase ≥ {SKIP_APY}%)", ""]
    if not top:
        lines.append("Sem pool passando nos filtros.")
    for i, r in enumerate(top, 1):
        lines.append(f"{i}. **{r['symbol']}** {r['chain']}/{r['project']} — APY {r['apy']:.2f}% "
                     f"(base {float(r.get('apyBase') or 0):.2f}%, 30d {float(r.get('apyMean30d') or 0):.2f}%) | "
                     f"TVL ${r['tvlUsd']:,.0f}\n   {r['url']}")
    lines += ["", "_Alerta only. Ticket sugerido ≤ teto do trader (default US$25). Não é recomendação financeira._"]
    (OUT / "lending-latest.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
