#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pumpfun_paper.py — scanner de memecoins novas do pump.fun em modo PAPER TRADING.
SIMULAÇÃO APENAS: nenhuma ordem real, nenhuma carteira, nenhuma chave privada.

Fontes (HTTP público): pump.fun frontend-api-v3, DexScreener, Jupiter (lite-api quote),
RugCheck (report), Solana RPC público (fallback p/ authorities / maiores holders).

Uso: pumpfun_paper.py            -> roda 1 ciclo (atualiza posições, depois procura entradas)
     pumpfun_paper.py --dry      -> idem, mas não grava state/jsonl (debug)
"""
import json, os, sys, time, datetime, urllib.request, urllib.parse, urllib.error, traceback, shutil, glob

# ----------------------------------------------------------------- config
BASE = (os.environ.get("SCOUT_OUT_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"))
STATE_F = os.path.join(BASE, "pumpfun-state.json")
EVENTS_F = os.path.join(BASE, "pumpfun-paper.jsonl")
CAND_F = os.path.join(BASE, "pumpfun-candidates.jsonl")
LOGDIR = os.path.join(BASE, "logs")
RUNS_F = os.path.join(LOGDIR, "runs.jsonl")
CAND_ARCHIVE = os.path.join(LOGDIR, "candidates-archive")
CAND_KEEP_DAYS = 10

BRT = datetime.timezone(datetime.timedelta(hours=-3), "BRT")
# Sem novas entradas a partir de PUMPFUN_CUTOFF_NEW (ISO, ex. 2026-12-31T23:00-03:00). Vazio = sem corte.
_cut = os.environ.get("PUMPFUN_CUTOFF_NEW", "").strip()
CUTOFF_NEW = datetime.datetime.fromisoformat(_cut) if _cut else datetime.datetime(9999, 1, 1, tzinfo=BRT)

ENTRY_USD = 4.0
MAX_OPEN = 2
TP1_MULT, TP1_FRAC = 1.50, 0.5      # vende 50% em +50%
TP2_MULT = 2.00                     # vende o restante em +100%
STOP_MULT = 0.70                    # stop -30% (sobre o restante), referência = preço de entrada
TIME_STOP_H = 4.0
MIN_SLIP = 0.005                    # slippage mínimo assumido por perna (0,5%: taxa LP/prioridade)
DEFAULT_SLIP = 0.02                 # se a cotação Jupiter falhar

# filtros
MAX_AGE_H = 6.0
MIN_CURVE_PROGRESS = 85.0
MIN_LIQ_USD = 20000.0
MAX_TOP10_PCT = 30.0
MAX_RUG_SCORE_NORM = 60             # RugCheck score_normalised (0=melhor .. 100=pior); exige <= 60
RISE_RATIO_M5 = 1.0                 # v2: requisito adicional ao snapshot: ritmo m5 >= 1,0x média 5 min da h1
RISE_SNAP_MIN_GROWTH = 1.10         # h1 vol e h1 txns >= +10% vs snapshot de 10-40 min atrás
SNAP_MIN_AGE_MIN, SNAP_MAX_AGE_MIN = 10, 40
LIQ_DROP_VETO = 0.20                # v2: rejeita entrada se liquidez caiu >= 20% vs snapshot 15-30 min (ou 10-40)
LIQ_DROP_EXIT = 0.20                # v2: posição aberta sai se liquidez cai >= 20% entre ciclos
SNAP_HISTORY_MIN = 60               # mantém histórico de snapshots por mint (últimos 60 min)
RULES_VERSION = 3
MIN_LP_LOCKED_PCT = 90.0            # v3: LP do pool de execução >= 90% travado/queimado (RugCheck markets[].lp.lpLockedPct)
POS_RUNS_F = os.path.join(LOGDIR, "positions-runs.jsonl")
POSITIONS_ONLY = "--positions-only" in sys.argv
RULES_CHANGES_V3 = [
    "monitoramento de posições abertas a cada 5 min, 24h/dia (modo --positions-only: sem rede se não há posição; sem novas varreduras; pula os minutos da varredura completa)",
    f"LP do pool de execução precisa estar >= {MIN_LP_LOCKED_PCT:.0f}% travado/queimado (RugCheck markets[].lp.lpLockedPct); senão rejeita 'LP não travado/queimado (x%)'",
]
RULES_CHANGES_V2 = [
    "1ª observação nunca entra: exige snapshot anterior (10-40 min) e crescimento h1 vol/txns >= +10% vs ele (mín. 2 observações)",
    "ritmo m5 >= 1,0x média de 5 min da h1 (vol e txns) mantido como requisito adicional (não acelerar = não entra)",
    "veto de liquidez: queda >= 20% vs snapshot de 15-30 min (ou o mais próximo de 10-40 min) rejeita entrada",
    "posição aberta: queda de liquidez >= 20% entre ciclos -> saída imediata (liq_drop) no preço atual com slippage Jupiter",
]
MAX_RUGCHECK_PER_RUN = 10
PUMP_PAGES = 8                      # páginas de 50 (sort=created_timestamp, complete=true)

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL = "So11111111111111111111111111111111111111112"
BURN_ADDRS = {"1nc1nerator11111111111111111111111111111111", "11111111111111111111111111111111"}
INITIAL_REAL_TOKEN_RESERVES = 793_100_000_000_000  # pump.fun bonding curve (6 decimais)
UA = {"User-Agent": "Mozilla/5.0 (crypto-agents-kit paper-scanner/1.0)", "Accept": "application/json"}

DRY = "--dry" in sys.argv
NOW = datetime.datetime.now(BRT)
NOW_TS = time.time()
SRC = {}   # saúde das fontes neste ciclo: nome -> {"ok":n,"err":n,"last_err":str}

def iso(dt=None):
    return (dt or datetime.datetime.now(BRT)).astimezone(BRT).isoformat(timespec="seconds")

def log(msg):
    print(f"[{iso()}] {msg}", flush=True)

def mark(src, ok, err=None):
    s = SRC.setdefault(src, {"ok": 0, "err": 0, "last_err": None})
    if ok: s["ok"] += 1
    else:
        s["err"] += 1; s["last_err"] = str(err)[:200]

def http_json(url, src, data=None, timeout=20, retries=2, sleep=0.35):
    """GET/POST JSON com timeout, retry em 429/5xx e pequeno sleep (rate limit)."""
    last = None
    for attempt in range(retries + 1):
        try:
            h = dict(UA); body = None
            if data is not None:
                h["Content-Type"] = "application/json"; body = json.dumps(data).encode()
            with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=h), timeout=timeout) as r:
                out = json.loads(r.read().decode())
            time.sleep(sleep)
            if isinstance(out, dict) and out.get("statusCode") == 429:
                raise urllib.error.HTTPError(url, 429, "rate limit (body)", None, None)
            mark(src, True)
            return out
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 504, 530) and attempt < retries:
                time.sleep(2.0 * (attempt + 1)); continue
            break
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            if attempt < retries:
                time.sleep(1.5); continue
    mark(src, False, last)
    return None

def fnum(x, d=0.0):
    try: return float(x)
    except Exception: return d

# ----------------------------------------------------------------- persistence
def load_state():
    try:
        with open(STATE_F) as f: return json.load(f)
    except Exception:
        return {"created_at": iso(), "open": [], "closed": [], "snapshots": {}, "signaled": {},
                "traded_mints": [], "realized_pnl_usd": 0.0, "runs": 0}

def save_state(st):
    if DRY: return
    tmp = STATE_F + ".tmp"
    with open(tmp, "w") as f: json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_F)

def append_jsonl(path, obj):
    if DRY: return
    with open(path, "a") as f: f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def rotate_candidates():
    """Rotação diária do log de candidatos; mantém CAND_KEEP_DAYS arquivos."""
    if DRY or not os.path.exists(CAND_F): return
    try:
        with open(CAND_F) as f: first = f.readline()
        day = json.loads(first)["ts"][:10] if first.strip() else None
    except Exception:
        day = None
    today = NOW.strftime("%Y-%m-%d")
    if day and day != today:
        os.makedirs(CAND_ARCHIVE, exist_ok=True)
        shutil.move(CAND_F, os.path.join(CAND_ARCHIVE, f"pumpfun-candidates-{day.replace('-', '')}.jsonl"))
    files = sorted(glob.glob(os.path.join(CAND_ARCHIVE, "pumpfun-candidates-*.jsonl")))
    for old in files[:-CAND_KEEP_DAYS]:
        os.remove(old)

# ----------------------------------------------------------------- data helpers
def dex_pairs_batch(mints):
    """DexScreener /tokens/v1/solana/<até 30 mints>. Retorna mint -> lista de pares."""
    out = {}
    mints = list(dict.fromkeys(mints))
    for i in range(0, len(mints), 30):
        chunk = mints[i:i + 30]
        d = http_json("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk), "dexscreener")
        if not isinstance(d, list): continue
        for p in d:
            m = (p.get("baseToken") or {}).get("address")
            if m in chunk: out.setdefault(m, []).append(p)
    return out

def best_pair(pairs):
    pairs = [p for p in (pairs or []) if (p.get("chainId") == "solana")]
    if not pairs: return None
    return max(pairs, key=lambda p: fnum((p.get("liquidity") or {}).get("usd")))

def jup_quote(input_mint, output_mint, amount_raw):
    q = urllib.parse.urlencode({"inputMint": input_mint, "outputMint": output_mint,
                                "amount": int(amount_raw), "slippageBps": 300})
    d = http_json("https://lite-api.jup.ag/swap/v1/quote?" + q, "jupiter", sleep=0.6)
    if isinstance(d, dict) and d.get("outAmount"):
        return d
    return None

def rpc(method, params):
    d = http_json("https://api.mainnet-beta.solana.com",
                  "solana_rpc", data={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, sleep=0.5, retries=1)
    return (d or {}).get("result") if isinstance(d, dict) else None

def rpc_mint_info(mint):
    r = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
    try:
        return r["value"]["data"]["parsed"]["info"]
    except Exception:
        return None

# ----------------------------------------------------------------- discovery
def discover():
    """Coleta mints candidatas. Retorna dict mint -> meta pump.fun (ou {} se veio de outra fonte)."""
    cands = {}
    oldest_ms = (NOW_TS - MAX_AGE_H * 3600) * 1000
    for page in range(PUMP_PAGES):
        url = ("https://frontend-api-v3.pump.fun/coins?" + urllib.parse.urlencode({
            "offset": page * 50, "limit": 50, "sort": "created_timestamp", "order": "DESC",
            "complete": "true", "includeNsfw": "false"}))
        d = http_json(url, "pumpfun_graduated", sleep=1.2, retries=3)
        if not isinstance(d, list) or not d: break
        for c in d:
            if c.get("mint"): cands[c["mint"]] = c
        if min(fnum(c.get("created_timestamp"), 0) for c in d) < oldest_ms:
            break
    # quase graduando / atividade recente (curva >= 85% entra pelo filtro de progresso)
    url = ("https://frontend-api-v3.pump.fun/coins?" + urllib.parse.urlencode({
        "offset": 0, "limit": 50, "sort": "last_trade_timestamp", "order": "DESC", "includeNsfw": "false"}))
    d = http_json(url, "pumpfun_last_trade", sleep=1.2, retries=3)
    if isinstance(d, list):
        for c in d:
            if c.get("mint") and c["mint"] not in cands and fnum(c.get("created_timestamp")) >= oldest_ms:
                cands[c["mint"]] = c
    # DexScreener: perfis/boosts recentes de tokens pump (Solana, final 'pump')
    for url, src in [("https://api.dexscreener.com/token-profiles/latest/v1", "dexscreener_profiles"),
                     ("https://api.dexscreener.com/token-boosts/latest/v1", "dexscreener_boosts")]:
        d = http_json(url, src)
        if isinstance(d, list):
            for t in d:
                m = t.get("tokenAddress") or ""
                if t.get("chainId") == "solana" and m.endswith("pump") and m not in cands:
                    cands[m] = {"mint": m, "_src": src}
    return cands

def curve_progress(c):
    if c.get("complete"): return 100.0
    rtr = c.get("real_token_reserves")
    if rtr is None: return None
    return max(0.0, min(100.0, 100.0 * (1 - fnum(rtr) / INITIAL_REAL_TOKEN_RESERVES)))

# ----------------------------------------------------------------- filters
def snap_list(st, mint):
    v = (st.get("snapshots") or {}).get(mint)
    if isinstance(v, dict): v = [v]          # formato v1 (um snapshot) -> lista
    return v or []

def pick_snapshot(st, mint):
    """Escolhe snapshot de 15-30 min atrás (mais próximo de 22,5 min); senão o mais próximo dentro de 10-40 min."""
    best = None
    for sn in snap_list(st, mint):
        age = (NOW_TS - sn["t"]) / 60
        if not (SNAP_MIN_AGE_MIN <= age <= SNAP_MAX_AGE_MIN): continue
        pref = 0 if 15 <= age <= 30 else 1
        key = (pref, abs(age - 22.5))
        if best is None or key < best[0]: best = (key, sn, age)
    return (best[1], best[2]) if best else (None, None)

def activity_check(mint, pair, st):
    """v2: exige snapshot anterior (>= 2 observações) + crescimento h1 vs snapshot + ritmo m5 >= 1,0x."""
    tx = pair.get("txns") or {}; vol = pair.get("volume") or {}
    m5_tx = sum(fnum((tx.get("m5") or {}).get(k)) for k in ("buys", "sells"))
    h1_tx = sum(fnum((tx.get("h1") or {}).get(k)) for k in ("buys", "sells"))
    m5_v, h1_v = fnum(vol.get("m5")), fnum(vol.get("h1"))
    pv = m5_v / (h1_v / 12) if h1_v > 0 else 0
    pt = m5_tx / (h1_tx / 12) if h1_tx > 0 else 0
    info = {"m5_txns": m5_tx, "h1_txns": h1_tx, "m5_vol": round(m5_v, 2), "h1_vol": round(h1_v, 2),
            "vol_pace": round(pv, 2), "txns_pace": round(pt, 2), "n_snapshots": len(snap_list(st, mint))}
    snap, age_min = pick_snapshot(st, mint)
    if not snap or snap.get("h1_vol", 0) <= 0 or snap.get("h1_txns", 0) <= 0:
        info["metodo"] = "aguardando_2a_observacao"
        return False, "1ª observação: aguardando snapshot 10-40 min (sem entrada)", info
    gv, gt = h1_v / snap["h1_vol"], h1_tx / snap["h1_txns"]
    info.update({"metodo": "snapshot+m5", "snap_age_min": round(age_min, 1),
                 "h1_vol_growth": round(gv, 2), "h1_txns_growth": round(gt, 2)})
    if not (gv >= RISE_SNAP_MIN_GROWTH and gt >= RISE_SNAP_MIN_GROWTH):
        return False, "volume/txns não subiram vs snapshot", info
    if not (pv >= RISE_RATIO_M5 and pt >= RISE_RATIO_M5 and m5_tx >= 10):
        return False, "ritmo m5 desacelerando", info
    return True, "ok", info

def liq_drop_check(mint, liq, st):
    snap, age_min = pick_snapshot(st, mint)
    if not snap or not snap.get("liq"): return False, None
    drop = 1 - liq / snap["liq"]
    return drop >= LIQ_DROP_VETO, {"liq_snap": round(snap["liq"], 2), "snap_age_min": round(age_min, 1), "liq_drop_pct": round(100 * drop, 1)}

def top10_excluding(report, excl):
    holders = report.get("topHolders") or []
    known = report.get("knownAccounts") or {}
    excl = set(excl) | BURN_ADDRS
    for addr, k in known.items():
        if (k or {}).get("type") in ("AMM", "LOCKER", "BURN"): excl.add(addr)
    keep = [h for h in holders if h.get("owner") not in excl and h.get("address") not in excl]
    return sum(fnum(h.get("pct")) for h in keep[:10]), len(holders)

def rpc_top10(mint, supply_raw, excl):
    r = rpc("getTokenLargestAccounts", [mint])
    if not r: return None
    accs = [a for a in r.get("value", []) if a.get("address") not in excl]
    # sem 'owner' aqui (precisaria 1 chamada por conta); exclui só endereços conhecidos
    return 100.0 * sum(fnum(a.get("amount")) for a in accs[:10]) / supply_raw if supply_raw else None

def lp_locked_pct(rep, pair_addr):
    """% do LP travado/queimado no market do RugCheck que corresponde ao pool de execução.
    Se o pool não aparecer em markets[], usa o market com mais liquidez (marcado na info)."""
    mkts = [m for m in (rep.get("markets") or []) if isinstance(m, dict)]
    if not mkts: return None, "sem markets"
    mk = next((m for m in mkts if m.get("pubkey") == pair_addr), None)
    note = "pool de execução"
    if mk is None:
        mk = max(mkts, key=lambda m: fnum((m.get("lp") or {}).get("quoteUSD")) + fnum((m.get("lp") or {}).get("baseUSD")))
        note = "pool de execução ausente no RugCheck; usado market mais líquido"
    lp = mk.get("lp") or {}
    pct = lp.get("lpLockedPct")
    if pct is None:
        lk, ul = fnum(lp.get("lpLocked")), fnum(lp.get("lpUnlocked"))
        pct = 100.0 * lk / (lk + ul) if (lk + ul) > 0 else None
    return (None if pct is None else round(fnum(pct), 2)), f"{mk.get('marketType')} {str(mk.get('pubkey'))[:8]} ({note})"

def evaluate(mint, meta, pairs, st, budget):
    """Aplica todos os filtros. Retorna (passou, motivo, detalhes)."""
    det = {"mint": mint, "symbol": meta.get("symbol"), "fonte": meta.get("_src", "pumpfun")}
    pair = best_pair(pairs)
    # idade
    created_ms = fnum(meta.get("created_timestamp")) or (fnum(pair.get("pairCreatedAt")) if pair else 0)
    age_h = (NOW_TS * 1000 - created_ms) / 3.6e6 if created_ms else None
    det["idade_h"] = round(age_h, 2) if age_h is not None else None
    if age_h is None: return False, "idade desconhecida", det
    if age_h >= MAX_AGE_H: return False, f"idade >= {MAX_AGE_H}h", det
    # graduação / curva
    prog = curve_progress(meta) if meta.get("created_timestamp") else None
    dex_ids = sorted({p.get("dexId") for p in pairs or []})
    graduated_dex = any(d in ("pumpswap", "raydium", "meteora", "orca") for d in dex_ids)
    det.update({"curva_pct": round(prog, 1) if prog is not None else None, "dexes": dex_ids})
    if not (graduated_dex or (prog is not None and prog >= MIN_CURVE_PROGRESS)):
        return False, "não graduado / curva < 85%", det
    if not pair: return False, "sem par na DexScreener", det
    det["symbol"] = det["symbol"] or (pair.get("baseToken") or {}).get("symbol")
    liq = fnum((pair.get("liquidity") or {}).get("usd"))
    price = fnum(pair.get("priceUsd"))
    det.update({"liq_usd": round(liq, 2), "preco_usd": price, "dex": pair.get("dexId"),
                "par": pair.get("pairAddress"), "mcap": pair.get("marketCap")})
    if liq < MIN_LIQ_USD: return False, f"liquidez < US${MIN_LIQ_USD:,.0f}", det
    if price <= 0: return False, "sem preço", det
    dropped, ld = liq_drop_check(mint, liq, st)
    det["liq_check"] = ld
    if dropped: return False, f"liquidez caiu >= {LIQ_DROP_VETO:.0%} vs snapshot", det
    rising, why, act = activity_check(mint, pair, st)
    det["atividade"] = act
    if not rising: return False, why, det
    # RugCheck (orçamento por ciclo)
    if budget["rugcheck"] <= 0: return False, "orçamento RugCheck do ciclo esgotado (reavaliar próximo ciclo)", det
    budget["rugcheck"] -= 1
    rep = http_json(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report", "rugcheck", timeout=30, sleep=1.0)
    if not isinstance(rep, dict):
        return False, "RugCheck indisponível (conservador: rejeita)", det
    mint_auth, freeze_auth = rep.get("mintAuthority"), rep.get("freezeAuthority")
    if "mintAuthority" not in rep:
        info = rpc_mint_info(mint) or {}
        mint_auth, freeze_auth = info.get("mintAuthority", "?"), info.get("freezeAuthority", "?")
    risks = rep.get("risks") or []
    dangers = [r.get("name") for r in risks if (r.get("level") or "").lower() == "danger"]
    det.update({"mint_authority": mint_auth, "freeze_authority": freeze_auth,
                "rug_score_norm": rep.get("score_normalised"), "rug_dangers": dangers,
                "rug_warns": [r.get("name") for r in risks if (r.get("level") or "").lower() == "warn"],
                "rugged": rep.get("rugged"), "creator": rep.get("creator") or meta.get("creator"),
                "holders": rep.get("totalHolders")})
    if mint_auth: return False, "mint authority ativa", det
    if freeze_auth: return False, "freeze authority ativa", det
    if rep.get("rugged"): return False, "RugCheck: marcado como rugged", det
    if dangers: return False, "RugCheck danger: " + "; ".join(dangers[:3]), det
    sn = rep.get("score_normalised")
    if sn is None or fnum(sn) > MAX_RUG_SCORE_NORM: return False, f"RugCheck score_normalised {sn} > {MAX_RUG_SCORE_NORM}", det
    # v3: LP travado/queimado no pool de execução (par mais líquido da DexScreener)
    lp_pct, lp_info = lp_locked_pct(rep, pair.get("pairAddress"))
    det["lp_locked_pct"], det["lp_market"] = lp_pct, lp_info
    if lp_pct is None or lp_pct < MIN_LP_LOCKED_PCT:
        return False, f"LP não travado/queimado ({'sem dado' if lp_pct is None else f'{lp_pct:.0f}%'})", det
    # top10 excluindo pool/curva/burn
    excl = {p.get("pairAddress") for p in pairs or []} | {meta.get("bonding_curve"), meta.get("associated_bonding_curve"),
             meta.get("pump_swap_pool"), meta.get("pool_address")}
    for mk in rep.get("markets") or []:
        excl |= {mk.get("pubkey"), mk.get("liquidityA"), mk.get("liquidityB")}
    excl.discard(None)
    if rep.get("topHolders"):
        top10, nh = top10_excluding(rep, excl); det["top10_fonte"] = "rugcheck"
    else:
        supply = fnum(((rep.get("token") or {}).get("supply"))) or fnum(meta.get("total_supply"))
        top10 = rpc_top10(mint, supply, excl); det["top10_fonte"] = "rpc"
    det["top10_pct"] = round(top10, 2) if top10 is not None else None
    if top10 is None: return False, "top holders indisponível", det
    if top10 >= MAX_TOP10_PCT: return False, f"top10 {top10:.1f}% >= {MAX_TOP10_PCT}%", det
    return True, "passou em todos os filtros", det

# ----------------------------------------------------------------- positions
def slip_from_quote(q):
    if not q: return None
    return max(fnum(q.get("priceImpactPct")), 0.0)

def sell(pos, frac_of_initial, price, reason, events):
    """Vende frac_of_initial da quantidade inicial ao preço 'price' aplicando slippage estimado."""
    qty = min(pos["qty_initial"] * frac_of_initial, pos["qty_left"])
    if qty <= 0: return 0.0
    raw = int(qty * (10 ** pos.get("decimals", 6)))
    q = jup_quote(pos["mint"], USDC, raw) if raw > 0 else None
    slip = slip_from_quote(q)
    slip_src = "jupiter_quote"
    if slip is None:
        slip = pos.get("entry_slip", DEFAULT_SLIP); slip_src = "estimado_entrada"
    slip = max(slip, MIN_SLIP)
    proceeds = qty * price * (1 - slip)
    cost = pos["cost_usd"] * (qty / pos["qty_initial"])
    pnl = proceeds - cost
    pos["qty_left"] -= qty
    pos["proceeds_usd"] = pos.get("proceeds_usd", 0.0) + proceeds
    pos.setdefault("fills", []).append({"ts": iso(), "qty": qty, "price": price, "slip": slip, "reason": reason})
    final = pos["qty_left"] <= pos["qty_initial"] * 1e-9
    ev = {"ts": iso(), "event": "exit" if final else "partial_exit", "mint": pos["mint"], "symbol": pos["symbol"],
          "exit_reason": reason, "price_usd": price, "entry_price_usd": pos["entry_price"],
          "variacao_pct": round(100 * (price / pos["entry_price"] - 1), 2),
          "qty_sold": qty, "fraction_of_initial": round(qty / pos["qty_initial"], 4),
          "slippage_est": round(slip, 5), "slippage_fonte": slip_src,
          "proceeds_usd": round(proceeds, 4), "cost_basis_usd": round(cost, 4),
          "pnl_usd": round(pnl, 4), "pnl_pct": round(100 * pnl / cost, 2) if cost else None,
          "paper": True}
    if final:
        tot = pos["proceeds_usd"] - pos["cost_usd"]
        ev.update({"trade_pnl_usd": round(tot, 4), "trade_pnl_pct": round(100 * tot / pos["cost_usd"], 2),
                   "held_h": round((NOW_TS - pos["entry_t"]) / 3600, 2)})
    events.append(ev)
    return pnl

def update_positions(st, events):
    if not st["open"]: return
    pm = dex_pairs_batch([p["mint"] for p in st["open"]])
    still = []
    for pos in st["open"]:
        pair = best_pair(pm.get(pos["mint"]))
        price = fnum(pair.get("priceUsd")) if pair else 0.0
        liq_now = fnum((pair.get("liquidity") or {}).get("usd")) if pair else 0.0
        liq_prev = pos.get("last_liq")
        liq_drop = bool(liq_prev and liq_now > 0 and liq_now <= liq_prev * (1 - LIQ_DROP_EXIT))
        if liq_now > 0: pos["last_liq"] = liq_now
        held_h = (NOW_TS - pos["entry_t"]) / 3600
        if price > 0:
            pos["last_price"], pos["last_price_ts"] = price, iso()
            pos["max_price"] = max(pos.get("max_price", price), price)
            pos["min_price"] = min(pos.get("min_price", price), price)
        else:
            log(f"  ! {pos['symbol']}: sem preço DexScreener neste ciclo")
            if held_h >= TIME_STOP_H and pos.get("last_price"):
                price = pos["last_price"]  # fecha no último preço conhecido
            else:
                still.append(pos); continue
        mult = price / pos["entry_price"]
        realized = 0.0
        if liq_drop and price > 0 and pair:
            realized += sell(pos, 1.0, price, f"liq_drop (liquidez US${liq_prev:,.0f} -> US${liq_now:,.0f}, "
                             f"{100*(1-liq_now/liq_prev):.0f}%)", events)
        elif held_h >= TIME_STOP_H:
            realized += sell(pos, 1.0, price, f"time stop {TIME_STOP_H:.0f}h" + ("" if pair else " (último preço conhecido)"), events)
        elif mult <= STOP_MULT:
            realized += sell(pos, 1.0, price, "stop -30%", events)
        else:
            if mult >= TP1_MULT and not pos.get("tp1_done"):
                realized += sell(pos, TP1_FRAC, price, "alvo +50% (50%)", events); pos["tp1_done"] = True
            if mult >= TP2_MULT and pos["qty_left"] > 0:
                realized += sell(pos, 1.0, price, "alvo +100% (restante)", events)
        st["realized_pnl_usd"] = st.get("realized_pnl_usd", 0.0) + realized
        if pos["qty_left"] > pos["qty_initial"] * 1e-9:
            pos["unrealized_usd"] = round(pos["qty_left"] * price - pos["cost_usd"] * pos["qty_left"] / pos["qty_initial"], 4)
            still.append(pos)
            log(f"  posição {pos['symbol']}: {100*(mult-1):+.1f}% | {held_h:.2f}h | restante {pos['qty_left']/pos['qty_initial']:.0%}")
        else:
            pos["closed_at"] = iso(); pos["pnl_usd"] = round(pos["proceeds_usd"] - pos["cost_usd"], 4)
            st["closed"].append(pos)
            log(f"  posição {pos['symbol']} FECHADA: P&L US${pos['pnl_usd']:+.2f}")
    st["open"] = still

def open_position(det, st, events):
    mint, price = det["mint"], det["preco_usd"]
    q = jup_quote(USDC, mint, ENTRY_USD * 1e6)
    slip = slip_from_quote(q); slip_src = "jupiter_quote"
    decimals = 6
    jup_px = None
    if q:
        # preço implícito na cotação (token pump = 6 decimais)
        out = fnum(q.get("outAmount")) / 10 ** decimals
        jup_px = ENTRY_USD / out if out > 0 else None
    if slip is None:
        slip = DEFAULT_SLIP; slip_src = "padrao_sem_cotacao"
    slip = max(slip, MIN_SLIP)
    qty = ENTRY_USD * (1 - slip) / price
    pos = {"mint": mint, "symbol": det.get("symbol"), "entry_ts": iso(), "entry_t": NOW_TS,
           "entry_price": price, "cost_usd": ENTRY_USD, "qty_initial": qty, "qty_left": qty, "decimals": decimals,
           "entry_slip": slip, "last_liq": det.get("liq_usd"), "entry_liq": det.get("liq_usd"), "tp1_done": False, "proceeds_usd": 0.0, "pair": det.get("par"), "dex": det.get("dex")}
    st["open"].append(pos)
    st.setdefault("traded_mints", []).append(mint)
    events.append({"ts": iso(), "event": "entry", "mint": mint, "symbol": det.get("symbol"), "paper": True,
                   "entry_usd": ENTRY_USD, "price_usd": price, "jupiter_implied_price": jup_px,
                   "slippage_est": round(slip, 5), "slippage_fonte": slip_src,
                   "jupiter_route": [r.get("swapInfo", {}).get("label") for r in (q or {}).get("routePlan", [])],
                   "qty": qty, "entry_reason": det,
                   "plano": {"tp1": price * TP1_MULT, "tp2": price * TP2_MULT, "stop": price * STOP_MULT,
                             "time_stop": iso(NOW + datetime.timedelta(hours=TIME_STOP_H))}})
    log(f"  >>> ENTRADA (paper) {det.get('symbol')} @ US${price:.8g} | slip {slip:.2%} ({slip_src})")

# ----------------------------------------------------------------- main
def positions_only():
    """v3: só atualiza/fecha posições abertas. Sem posição -> sai sem rede e sem log."""
    st = load_state()
    if not st.get("open"):
        return
    events = []
    log(f"[posições 5min] abertas={len(st['open'])} | dry={DRY}")
    update_positions(st, events)
    for ev in events:
        ev["modo"] = "positions-only"
        append_jsonl(EVENTS_F, ev)
    st["last_positions_run"] = iso()
    save_state(st)
    append_jsonl(POS_RUNS_F, {"ts": iso(), "open": len(st["open"]), "events": [e["event"] for e in events],
                              "sources": SRC, "realized_pnl_usd": round(st.get("realized_pnl_usd", 0), 4)})

def main():
    os.makedirs(LOGDIR, exist_ok=True)
    if POSITIONS_ONLY:
        return positions_only()
    rotate_candidates()
    st = load_state()
    events = []
    changes_by_v = {2: RULES_CHANGES_V2, 3: RULES_CHANGES_V3}
    for v in range(st.get("rules_version", 1) + 1, RULES_VERSION + 1):
        ev = {"ts": iso(), "event": "rules_change", "rules_version": v,
              "changes": changes_by_v.get(v, []), "paper": True}
        append_jsonl(EVENTS_F, ev)
        st["rules_version"] = v; st["rules_changed_at"] = ev["ts"]
        log(f"regras v{v} registradas (rules_change)")
    if "--rules-only" in sys.argv:
        save_state(st); return
    log(f"ciclo início | abertas={len(st['open'])} | dry={DRY}")
    # 1) atualiza posições abertas
    update_positions(st, events)
    # 2) procura entradas
    stats = {"descobertos": 0, "avaliados": 0, "passaram": 0, "entradas": 0, "rejeicoes": {}}
    allow_new = NOW < CUTOFF_NEW
    if not allow_new:
        log("após 08/10/2026 23:00 BRT: não abre novas posições (só gerencia as abertas)")
    else:
        cands = discover()
        stats["descobertos"] = len(cands)
        oldest_ms = (NOW_TS - MAX_AGE_H * 3600) * 1000
        # pré-filtro barato por idade (quando conhecida), depois DexScreener em lote
        young = {m: c for m, c in cands.items()
                 if not c.get("created_timestamp") or fnum(c["created_timestamp"]) >= oldest_ms}
        pm = dex_pairs_batch(list(young.keys()))
        budget = {"rugcheck": MAX_RUGCHECK_PER_RUN}
        traded = set(st.get("traded_mints", []))
        open_mints = {p["mint"] for p in st["open"]}
        # mais líquidos primeiro (orçamento RugCheck vai para os melhores)
        order = sorted(young, key=lambda m: -fnum((best_pair(pm.get(m)) or {}).get("liquidity", {}).get("usd")))
        passed = []
        for m in order:
            meta = young[m]
            if m in traded or m in open_mints:
                continue
            stats["avaliados"] += 1
            try:
                ok, reason, det = evaluate(m, meta, pm.get(m, []), st, budget)
            except Exception as e:
                ok, reason, det = False, f"erro na avaliação: {type(e).__name__}: {e}", {"mint": m}
            if ok:
                passed.append(det); stats["passaram"] += 1
            else:
                stats["rejeicoes"][reason] = stats["rejeicoes"].get(reason, 0) + 1
                append_jsonl(CAND_F, {"ts": iso(), "mint": m, "symbol": det.get("symbol"), "status": "rejeitado",
                                      "motivo": reason, "detalhes": det})
        # atualiza snapshots (histórico 60 min por mint) p/ comparação 10-40 min nos próximos ciclos
        snaps = st.setdefault("snapshots", {})
        for m, ps in pm.items():
            p = best_pair(ps)
            if not p: continue
            tx = p.get("txns") or {}
            lst = snap_list(st, m)
            # não grava de novo se o último tem < 8 min (ciclos manuais fora do cron)
            if lst and (NOW_TS - lst[-1]["t"]) / 60 < 8: snaps[m] = lst; continue
            lst.append({"t": NOW_TS, "h1_vol": fnum((p.get("volume") or {}).get("h1")),
                        "h1_txns": sum(fnum((tx.get("h1") or {}).get(k)) for k in ("buys", "sells")),
                        "liq": fnum((p.get("liquidity") or {}).get("usd"))})
            snaps[m] = lst
        for m in list(snaps):
            lst = [x for x in snap_list(st, m) if NOW_TS - x["t"] <= SNAP_HISTORY_MIN * 60]
            if lst: snaps[m] = lst
            else: del snaps[m]
        # sinais e entradas
        today = NOW.strftime("%Y-%m-%d")
        sig = st.setdefault("signaled", {})
        for det in passed:
            m = det["mint"]
            slot = len(st["open"]) < MAX_OPEN
            if sig.get(m) != today:
                sig[m] = today
                events.append({"ts": iso(), "event": "signal", "mint": m, "symbol": det.get("symbol"),
                               "entrou": slot, "obs": None if slot else f"limite de {MAX_OPEN} posições abertas",
                               "filtros": det, "paper": True})
            append_jsonl(CAND_F, {"ts": iso(), "mint": m, "symbol": det.get("symbol"), "status": "aprovado",
                                  "motivo": "passou" if slot else "passou (sem vaga)", "detalhes": det})
            if slot:
                open_position(det, st, events); stats["entradas"] += 1
        for m in [m for m, d in sig.items() if d != today]:
            del sig[m]
    for ev in events:
        append_jsonl(EVENTS_F, ev)
    st["runs"] = st.get("runs", 0) + 1
    st["last_run"] = iso()
    st["last_sources"] = SRC
    st["last_stats"] = stats
    save_state(st)
    run = {"ts": iso(), "stats": stats, "sources": SRC, "open": len(st["open"]),
           "events": [e["event"] for e in events], "realized_pnl_usd": round(st.get("realized_pnl_usd", 0), 4)}
    append_jsonl(RUNS_F, run)
    top = sorted(stats["rejeicoes"].items(), key=lambda x: -x[1])[:6]
    log(f"descobertos={stats['descobertos']} avaliados={stats['avaliados']} passaram={stats['passaram']} "
        f"entradas={stats['entradas']} abertas={len(st['open'])}")
    log("principais rejeições: " + "; ".join(f"{k} ({v})" for k, v in top))
    log("fontes: " + "; ".join(f"{k} ok={v['ok']} err={v['err']}" + (f" [{v['last_err']}]" if v['err'] else "")
                                for k, v in SRC.items()))
    if DRY:
        print(json.dumps({"events": events, "stats": stats}, ensure_ascii=False, indent=1)[:4000])

def _timeout(signum, frame):
    raise TimeoutError("ciclo excedeu 12 min (timeout de segurança)")

if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGALRM, _timeout); signal.alarm(240 if POSITIONS_ONLY else 720)
    try:
        main()
    except Exception:
        log("ERRO FATAL:\n" + traceback.format_exc())
        try:
            append_jsonl(RUNS_F, {"ts": iso(), "fatal": traceback.format_exc()[-1500:], "sources": SRC})
        except Exception:
            pass
        sys.exit(1)
