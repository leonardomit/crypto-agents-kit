#!/usr/bin/env python3
"""Build $SCOUT_OUT_DIR/latest.md from raw.json. Alert-only; ACTIONABLE only if clear setup.

2026-09-29: cross-pool confirmation + raw.json archived per run.
A candidate (liq>=25k, vol24h>=50k, |Δ1h|>=8%) is ACTIONABLE only if another pool of the
same token on the same chain (liq>=25k) confirms: same Δ1h sign and |Δ1h| >= 50% of the
candidate's, and prices within 3%. Otherwise it is listed as "não confirmado" (no alert).

2026-10-02 (após falso positivo MAGIC/WETH Arbitrum): dois filtros extras p/ ACTIONABLE:
 1. Máxima 1h: rejeita se o preço atual já está >5% abaixo da máxima estimada da última hora.
    DexScreener não dá high 1h; estimativa = max(preço atual, preço implícito 5 min atrás = p/(1+m5),
    preço implícito 1h atrás = p/(1+h1), preços do MESMO pool nos snapshots history/raw-*.json
    dos últimos 60 min). É um limite inferior da máxima real (picos entre snapshots de 30 min escapam).
 2. Pool de execução: o pool mais líquido do token nessa chain (entre os coletados) precisa ter
    liquidez >= US$100k. O link do alerta aponta para esse pool.
 Rejeitados vão para "Não confirmados (sem alerta)" com o motivo.

2026-10-02 (versão c):
 - pool CONFIRMADOR (2º pool) também precisa liq >= US$100k (antes 25k).
 - filtro "máxima 1h" vale só p/ momentum long (Δ1h>0); fade/short mantém a lógica anterior
   (sem filtro de máxima 1h), mas também exige execução >= US$100k e confirmador >= US$100k.
 - alerta de fade traz rótulo informativo "Short disponível: ..." (Hyperliquid perp líquido);
   o rótulo NÃO altera ACTIONABLE.
 Replay: make_meme_digest.py --replay history/raw-YYYYMMDD-HHMM.json  (não grava nada)
"""
import json, os, shutil, datetime, sys, glob
from pathlib import Path
from zoneinfo import ZoneInfo

DIR = Path((os.environ.get("SCOUT_OUT_DIR") or Path(__file__).resolve().parent / "out"))
DIR.mkdir(parents=True, exist_ok=True)
raw_path = DIR / "raw.json"
hist = DIR / "history"
hist.mkdir(parents=True, exist_ok=True)
BRT = ZoneInfo("America/Sao_Paulo")
REPLAY = sys.argv[sys.argv.index("--replay") + 1] if "--replay" in sys.argv else None
if REPLAY:
    raw_path = Path(REPLAY) if Path(REPLAY).is_absolute() else DIR / REPLAY
    _fa = json.loads(raw_path.read_text()).get("fetched_at")
    now = datetime.datetime.strptime(_fa, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).astimezone(BRT)
else:
    now = datetime.datetime.now(BRT)
stamp = now.strftime("%Y%m%d-%H%M")

MIN_LIQ, MIN_VOL, MIN_CH1 = 25000, 50000, 8
PEER_MIN_LIQ, PEER_RATIO, PRICE_TOL = 100000, 0.5, 0.03   # confirmador >= US$100k desde 2026-10-02c
EXEC_MIN_LIQ = 100000          # liquidez mínima do pool de execução
MAX_BELOW_HIGH = 0.05          # só momentum long: rejeita se preço > 5% abaixo da máxima 1h estimada
# Perps Hyperliquid líquidos (pesquisa do Trader, 2026-10-02). POPCAT/BRETT/GMX listados mas vetados (liquidez baixa).
HL_LIQUID_PERPS = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "BONK": "kBONK", "WIF": "WIF", "ARB": "ARB", "PENDLE": "PENDLE"}
HL_ALIASES = {"WBTC": "BTC", "CBBTC": "BTC", "BTCB": "BTC", "WETH": "ETH", "WSOL": "SOL"}

def short_label(sym):
    s = (sym or "").upper().lstrip("$")
    s = HL_ALIASES.get(s, s)
    if s in HL_LIQUID_PERPS:
        return (f"Short disponível: Hyperliquid perp {HL_LIQUID_PERPS[s]} (ordem mín. US$10) — "
                "informativo, paper trading recomendado")
    return "Short disponível: não (sem perp líquido)"

try:
    raw = json.loads(raw_path.read_text()) if raw_path.exists() else {"pairs": [], "errors": ["missing raw.json"]}
except Exception as e:
    raw = {"pairs": [], "errors": [str(e)]}

# archive raw snapshot for audit
if raw_path.exists() and not REPLAY:
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

def _ts(fa):
    try:
        return datetime.datetime.strptime(fa, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None

# preços dos últimos 60 min por (chain, pair) a partir dos snapshots arquivados
now_utc = _ts(raw.get("fetched_at")) or now.astimezone(datetime.timezone.utc)
recent_px = {}
for fp in sorted(glob.glob(str(hist / "raw-*.json")))[-150:]:
    try:
        d = json.loads(Path(fp).read_text())
    except Exception:
        continue
    t = _ts(d.get("fetched_at"))
    if not t or not (datetime.timedelta(0) < now_utc - t <= datetime.timedelta(minutes=60)):
        continue
    for q in d.get("pairs") or []:
        k = (q.get("chain"), (q.get("pair") or "").lower())
        try:
            recent_px.setdefault(k, []).append((t, float(q.get("priceUsd") or 0)))
        except Exception:
            pass

def high_1h(p):
    """Máxima 1h estimada (limite inferior) e as fontes usadas."""
    px = f(p.get("priceUsd"))
    cands = [("agora", px)]
    for key, label in (("change5m", "5min atrás"), ("change1h", "1h atrás")):
        ch = p.get(key)
        if ch is not None and f(ch) > -99:
            cands.append((label, px / (1 + f(ch) / 100)))
    for t, v in recent_px.get((p.get("chain"), (p.get("pair") or "").lower()), []):
        if v > 0:
            cands.append((f"snapshot {t.astimezone(BRT).strftime('%H:%M')}", v))
    lab, hi = max(cands, key=lambda x: x[1])
    return hi, lab

def exec_pool(p):
    """Pool de execução = o mais líquido do mesmo token na mesma chain (inclui o próprio)."""
    addr = (p.get("baseAddress") or "").lower()
    sym = (p.get("base") or "").upper()
    same = [q for q in pairs if q.get("chain") == p.get("chain") and
            (((q.get("baseAddress") or "").lower() == addr) if addr else ((q.get("base") or "").upper() == sym))]
    return max(same or [p], key=lambda q: f(q.get("liquidityUsd")))

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
    ex = exec_pool(p)
    hi, hi_src = high_1h(p)
    below = (hi - price) / hi if hi > 0 and price > 0 else 0.0
    p["_exec"], p["_high1h"], p["_high_src"], p["_below"] = ex, hi, hi_src, below
    if ok_peer and f(ex.get("liquidityUsd")) < EXEC_MIN_LIQ:
        unconfirmed.append((score, p, ch1, liq, vol,
            f"pool de execução {ex.get('dex')}/{ex.get('quote')} pair={ex.get('pair')} liq US${f(ex.get('liquidityUsd')):,.0f} < US${EXEC_MIN_LIQ:,.0f}"))
    elif ok_peer and ch1 > 0 and below > MAX_BELOW_HIGH:
        unconfirmed.append((score, p, ch1, liq, vol,
            f"preço {below:.1%} abaixo da máxima 1h estimada ({hi:.6g}, fonte: {hi_src}) > {MAX_BELOW_HIGH:.0%}"))
    elif ok_peer:
        confirmed.append((score, p, ch1, liq, vol, ok_peer))
    else:
        why = f"sem outro pool com liq≥US${PEER_MIN_LIQ/1000:.0f}k p/ confirmar" if not peers else \
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
    lines.append("Sem setup actionable (barra: liq≥25k, vol24h≥50k, |Δ1h|≥8% + confirmação de 2º pool liq≥100k + pool de execução liq≥100k + long: preço ≤5% abaixo da máxima 1h). Silêncio pro orquestrador.")
else:
    lines.append("## Setups (sugestão ≤US$25)")
    for i, (score, p, ch1, liq, vol, q) in enumerate(top, 1):
        side = "momentum long" if ch1 > 0 else "fade/short-risk (só alerta)"
        lines += [f"### {i}. {p.get('base')}/{p.get('quote')} ({p.get('chain')})",
                  f"- Tese: {side}; Δ1h={ch1:.1f}% Δ24h={p.get('change24h')} dex={p.get('dex')}",
                  f"- Liq US${liq:,.0f} | Vol24h US${vol:,.0f} | price={p.get('priceUsd')} | pair={p.get('pair')}",
                  f"- Confirmado por: {q.get('dex')}/{q.get('quote')} pair={q.get('pair')} Δ1h={f(q.get('change1h')):.1f}% price={q.get('priceUsd')}",
                  f"- Execução: {p['_exec'].get('dex')}/{p['_exec'].get('quote')} pair={p['_exec'].get('pair')} liq US${f(p['_exec'].get('liquidityUsd')):,.0f} | "
                  f"máx 1h est. {p['_high1h']:.6g} ({p['_high_src']}), preço {p['_below']:.1%} abaixo"
                  + ("" if ch1 > 0 else " (filtro máx 1h não se aplica a fade)"),
                  *([f"- {short_label(p.get('base'))}"] if ch1 <= 0 else []),
                  "- Size sug. ≤US$25 | TP +15–25% / SL −8–12% / timebox 4–12h",
                  f"- Link: {p['_exec'].get('url') or p.get('url')}", ""]
if unconfirmed:
    lines += ["", "## Não confirmados (sem alerta)"]
    for score, p, ch1, liq, vol, why in unconfirmed[:5]:
        lines.append(f"- {p.get('base')}/{p.get('quote')} ({p.get('chain')}, {p.get('dex')}, pair={p.get('pair')}): "
                     f"Δ1h={ch1:.1f}% price={p.get('priceUsd')} — {why}")

text = "\n".join(lines) + "\n"
if REPLAY:
    print("[REPLAY — nada gravado]\n" + text)
    raise SystemExit(0)
(DIR / "latest.md").write_text(text)
(hist / f"{stamp}.md").write_text(text)
print(text)
