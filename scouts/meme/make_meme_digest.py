#!/usr/bin/env python3
"""Build $SCOUT_OUT_DIR/latest.md from raw.json. Alert-only; ACTIONABLE only if clear setup.

2026-09-29: cross-pool confirmation + raw.json archived per run.
A candidate (liq>=25k, vol24h>=50k, |Δ1h|>=8%) is ACTIONABLE only if another pool of the
same token on the same chain (liq>=25k) confirms: same Δ1h sign and |Δ1h| >= 50% of the
candidate's, and prices within 3%. Otherwise it is listed as "não confirmado" (no alert).
"""
import json, os, shutil, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DIR = Path((os.environ.get("SCOUT_OUT_DIR") or Path(__file__).resolve().parent / "out"))
DIR.mkdir(parents=True, exist_ok=True)
raw_path = DIR / "raw.json"
hist = DIR / "history"
hist.mkdir(parents=True, exist_ok=True)
BRT = ZoneInfo("America/Sao_Paulo")
now = datetime.datetime.now(BRT)
stamp = now.strftime("%Y%m%d-%H%M")

MIN_LIQ, MIN_VOL, MIN_CH1 = 25000, 50000, 8
PEER_MIN_LIQ, PEER_RATIO, PRICE_TOL = 25000, 0.5, 0.03

try:
    raw = json.loads(raw_path.read_text()) if raw_path.exists() else {"pairs": [], "errors": ["missing raw.json"]}
except Exception as e:
    raw = {"pairs": [], "errors": [str(e)]}

# archive raw snapshot for audit
if raw_path.exists():
    try:
        shutil.copy2(raw_path, hist / f"raw-{stamp}.json")
    except Exception:
        pass

def f(x):
    try:
        return float(x or 0)
    except Exception:
        return 0.0

pairs = raw.get("pairs") or []

def peers_of(p):
    addr = (p.get("baseAddress") or "").lower()
    sym = (p.get("base") or "").upper()
    def same_token(q):
        if addr and q.get("baseAddress"):
            return (q.get("baseAddress") or "").lower() == addr
        return (q.get("base") or "").upper() == sym
    return [q for q in pairs
            if q is not p and q.get("chain") == p.get("chain")
            and same_token(q)
            and f(q.get("liquidityUsd")) >= PEER_MIN_LIQ]

confirmed, unconfirmed = [], []
for p in pairs:
    liq, vol, ch1 = f(p.get("liquidityUsd")), f(p.get("volume24h")), f(p.get("change1h"))
    if liq < MIN_LIQ or vol < MIN_VOL or abs(ch1) < MIN_CH1:
        continue
    score = abs(ch1) * (vol ** 0.3) * (liq ** 0.2)
    price = f(p.get("priceUsd"))
    peers = peers_of(p)
    ok_peer = None
    for q in peers:
        qch, qpx = f(q.get("change1h")), f(q.get("priceUsd"))
        same_dir = (qch > 0) == (ch1 > 0) and abs(qch) >= PEER_RATIO * abs(ch1)
        px_ok = price > 0 and qpx > 0 and abs(qpx - price) / price <= PRICE_TOL
        if same_dir and px_ok:
            ok_peer = q
            break
    if ok_peer:
        confirmed.append((score, p, ch1, liq, vol, ok_peer))
    else:
        why = "sem outro pool com liq≥25k" if not peers else \
              "outros pools não confirmam (" + ", ".join(
                  f"{(q.get('dex') or '?')}/{q.get('quote')} Δ1h={f(q.get('change1h')):.1f}% px={q.get('priceUsd')}"
                  for q in peers[:3]) + ")"
        unconfirmed.append((score, p, ch1, liq, vol, why))

confirmed.sort(key=lambda x: -x[0])
unconfirmed.sort(key=lambda x: -x[0])
top = confirmed[:3]
actionable = len(top) > 0

lines = ["# Meme Scout (Sol/Base/Arb/Eth/BSC)", "",
         f"- Quando: {now.strftime('%Y-%m-%d %H:%M')} BRT",
         "- Modo: HTTP DexScreener only, zero wallet/trade, size teto US$25",
         f"- ACTIONABLE: {'true' if actionable else 'false'}",
         f"- Pares vistos: {len(pairs)} | erros: {len(raw.get('errors') or [])}",
         f"- Raw: history/raw-{stamp}.json (fetched_at {raw.get('fetched_at')})",
         ""]
if not top:
    lines.append("Sem setup actionable (barra: liq≥25k, vol24h≥50k, |Δ1h|≥8% + confirmação de 2º pool). Silêncio pro orquestrador.")
else:
    lines.append("## Setups (sugestão ≤US$25)")
    for i, (score, p, ch1, liq, vol, q) in enumerate(top, 1):
        side = "momentum long" if ch1 > 0 else "fade/short-risk (só alerta)"
        lines += [f"### {i}. {p.get('base')}/{p.get('quote')} ({p.get('chain')})",
                  f"- Tese: {side}; Δ1h={ch1:.1f}% Δ24h={p.get('change24h')} dex={p.get('dex')}",
                  f"- Liq US${liq:,.0f} | Vol24h US${vol:,.0f} | price={p.get('priceUsd')} | pair={p.get('pair')}",
                  f"- Confirmado por: {q.get('dex')}/{q.get('quote')} pair={q.get('pair')} Δ1h={f(q.get('change1h')):.1f}% price={q.get('priceUsd')}",
                  "- Size sug. ≤US$25 | TP +15–25% / SL −8–12% / timebox 4–12h",
                  f"- Link: {p.get('url')}", ""]
if unconfirmed:
    lines += ["", "## Não confirmados (sem alerta)"]
    for score, p, ch1, liq, vol, why in unconfirmed[:5]:
        lines.append(f"- {p.get('base')}/{p.get('quote')} ({p.get('chain')}, {p.get('dex')}, pair={p.get('pair')}): "
                     f"Δ1h={ch1:.1f}% price={p.get('priceUsd')} — {why}")

text = "\n".join(lines) + "\n"
(DIR / "latest.md").write_text(text)
(hist / f"{stamp}.md").write_text(text)
print(text)
