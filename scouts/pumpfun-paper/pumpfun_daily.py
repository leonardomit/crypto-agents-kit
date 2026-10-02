#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resumo diário (PT-BR) do paper trading pump.fun.
Uso: pumpfun_daily.py [YYYY-MM-DD]   (padrão: hoje BRT)
     pumpfun_daily.py --final [--auto]  -> relatório final $SCOUT_OUT_DIR/pumpfun-final-report.md
       (--auto só gera se hoje for $PUMPFUN_FINAL_DAY)"""
import json, os, sys, datetime, collections

BASE = (os.environ.get("SCOUT_OUT_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"))
BRT = datetime.timezone(datetime.timedelta(hours=-3), "BRT")
NOW = datetime.datetime.now(BRT)
FINAL_DAY = os.environ.get("PUMPFUN_FINAL_DAY", "")  # YYYY-MM-DD do relatório final (--auto)

def rj(path):
    out = []
    if not os.path.exists(path): return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try: out.append(json.loads(line))
            except Exception: pass
    return out

def usd(x): return f"US${x:+.2f}" if x is not None else "—"

def load_state():
    try: return json.load(open(os.path.join(BASE, "pumpfun-state.json")))
    except Exception: return {}

def trades_from_events(evs):
    """Agrupa eventos por posição (mint+entrada)."""
    trades, cur = [], {}
    for e in evs:
        m = e.get("mint")
        if e["event"] == "entry":
            cur[m] = {"mint": m, "symbol": e.get("symbol"), "entry_ts": e["ts"], "entry_price": e.get("price_usd"),
                      "cost": e.get("entry_usd", 4.0), "slip": e.get("slippage_est"), "fills": [], "closed": None}
            trades.append(cur[m])
        elif e["event"] in ("partial_exit", "exit") and m in cur:
            cur[m]["fills"].append(e)
            if e["event"] == "exit":
                cur[m]["closed"] = e; del cur[m]
    return trades

def sources_table(runs):
    agg = collections.defaultdict(lambda: {"ok": 0, "err": 0, "errs": collections.Counter()})
    for r in runs:
        for k, v in (r.get("sources") or {}).items():
            agg[k]["ok"] += v.get("ok", 0); agg[k]["err"] += v.get("err", 0)
            if v.get("err") and v.get("last_err"): agg[k]["errs"][v["last_err"]] += 1
    lines = ["| Fonte | OK | Erros | Erro mais comum |", "|---|---:|---:|---|"]
    for k in sorted(agg):
        a = agg[k]; tot = a["ok"] + a["err"]
        common = a["errs"].most_common(1)[0][0] if a["errs"] else ""
        lines.append(f"| {k} | {a['ok']} | {a['err']} ({(100*a['err']/tot if tot else 0):.0f}%) | {common} |")
    return lines

def open_positions_lines(st):
    lines = []
    for p in st.get("open", []):
        lp = p.get("last_price") or p["entry_price"]
        var = 100 * (lp / p["entry_price"] - 1)
        lines.append(f"- **{p.get('symbol')}** `{p['mint']}` — entrada {p['entry_ts']} @ US${p['entry_price']:.8g}, "
                     f"último US${lp:.8g} ({var:+.1f}%), restante {p['qty_left']/p['qty_initial']:.0%}, "
                     f"não realizado {usd(p.get('unrealized_usd'))}")
    return lines or ["- nenhuma"]

def report(day_prefix=None, title=None):
    evs = rj(os.path.join(BASE, "pumpfun-paper.jsonl"))
    runs = rj(os.path.join(BASE, "logs", "runs.jsonl"))
    st = load_state()
    sel = (lambda ts: ts.startswith(day_prefix)) if day_prefix else (lambda ts: True)
    devs = [e for e in evs if sel(e.get("ts", ""))]
    druns = [r for r in runs if sel(r.get("ts", ""))]
    signals = [e for e in devs if e["event"] == "signal"]
    entries = [e for e in devs if e["event"] == "entry"]
    exits = [e for e in devs if e["event"] in ("partial_exit", "exit")]
    closed = [e for e in devs if e["event"] == "exit"]
    wins = [e for e in closed if (e.get("trade_pnl_usd") or 0) > 0]
    pnl_period = sum(e.get("pnl_usd", 0) for e in exits)
    pnl_cum = sum(e.get("pnl_usd", 0) for e in evs if e["event"] in ("partial_exit", "exit"))
    unreal = sum(p.get("unrealized_usd") or 0 for p in st.get("open", []))
    fatal = [r for r in druns if r.get("fatal")]
    rej = collections.Counter()
    for r in druns:
        for k, v in ((r.get("stats") or {}).get("rejeicoes") or {}).items(): rej[k] += v
    cand_eval = sum(((r.get("stats") or {}).get("avaliados") or 0) for r in druns)
    L = [f"# {title}", "",
         f"_Gerado em {NOW.isoformat(timespec='seconds')} (BRT). **Simulação (paper trading) — nenhuma ordem real.**_", "",
         "## Números", "",
         f"- Ciclos executados: {len(druns)} (erros fatais: {len(fatal)})",
         f"- Candidatos avaliados (soma dos ciclos): {cand_eval}",
         f"- Sinais (aprovados em todos os filtros): {len(signals)}",
         f"- Entradas (US$4 cada): {len(entries)}",
         f"- Trades fechados: {len(closed)} | acertos: {len(wins)} | taxa de acerto: "
         + (f"{100*len(wins)/len(closed):.0f}%" if closed else "—"),
         f"- P&L realizado no período: **{usd(pnl_period)}**",
         f"- P&L realizado acumulado: **{usd(pnl_cum)}** | não realizado (abertas): {usd(unreal)}", ""]
    if closed:
        srt = sorted(closed, key=lambda e: e.get("trade_pnl_usd") or 0)
        L += ["## Maiores ganhos / perdas (trades fechados)", ""]
        for e in [x for x in reversed(srt) if (x.get("trade_pnl_usd") or 0) > 0][:3]:
            L.append(f"- 🟢 {e.get('symbol')} {usd(e.get('trade_pnl_usd'))} ({e.get('trade_pnl_pct'):+.1f}%) — {e.get('exit_reason')}")
        for e in srt[:3]:
            if (e.get("trade_pnl_usd") or 0) < 0:
                L.append(f"- 🔴 {e.get('symbol')} {usd(e.get('trade_pnl_usd'))} ({e.get('trade_pnl_pct'):+.1f}%) — {e.get('exit_reason')}")
        L.append("")
    if exits or entries:
        L += ["## Eventos", "", "| Hora (BRT) | Evento | Token | Preço US$ | Motivo | P&L US$ |", "|---|---|---|---:|---|---:|"]
        for e in [x for x in devs if x["event"] in ("entry", "partial_exit", "exit")]:
            L.append(f"| {e['ts'][11:16] if day_prefix else e['ts'][:16]} | {e['event']} | {e.get('symbol')} | {(e.get('price_usd') or 0):.8g} | "
                     f"{e.get('exit_reason') or 'sinal'} | {e.get('pnl_usd', 0):+.2f} |")
        L.append("")
    rc = [e for e in evs if e["event"] == "rules_change"]
    if rc:
        cut = rc[-1]["ts"]
        def blk(xs):
            en = [e for e in xs if e["event"] == "entry"]
            sg = [e for e in xs if e["event"] == "signal"]
            cl = [e for e in xs if e["event"] == "exit"]
            w = [e for e in cl if (e.get("trade_pnl_usd") or 0) > 0]
            pn = sum(e.get("pnl_usd", 0) for e in xs if e["event"] in ("partial_exit", "exit"))
            return [len(sg), len(en), len(cl), (f"{100*len(w)/len(cl):.0f}%" if cl else "—"), f"{pn:+.2f}"]
        before = [e for e in devs if e.get("ts", "") < cut]
        after = [e for e in devs if e.get("ts", "") >= cut]
        b, a2 = blk(before), blk(after)
        L += [f"## Antes vs depois da mudança de regras (v{rc[-1].get('rules_version')}, {cut})", "",
              "_Saídas contam no lado em que ocorreram (uma posição aberta antes pode fechar depois)._", "",
              "| | Sinais | Entradas | Fechados | Acerto | P&L realizado US$ |", "|---|---:|---:|---:|---:|---:|",
              "| Antes | " + " | ".join(map(str, b)) + " |", "| Depois | " + " | ".join(map(str, a2)) + " |", ""]
        L += ["Mudanças: " + " / ".join(rc[-1].get("changes") or []), ""]
    L += ["## Posições abertas", ""] + open_positions_lines(st) + [""]
    L += ["## Principais motivos de rejeição", ""]
    L += [f"- {k}: {v}" for k, v in rej.most_common(8)] or ["- —"]
    L += ["", "## Saúde das fontes de dados", ""] + sources_table(druns)
    if fatal:
        L += ["", "### Erros fatais", ""] + [f"- {r['ts']}: `{r['fatal'].strip().splitlines()[-1]}`" for r in fatal[:5]]
    L += ["", "---", "Regras: entrada US$4; máx. 2 posições; 50% em +50%, restante em +100%, stop −30%, time stop 4h; "
          "slippage = priceImpact Jupiter (mín. 0,5%/perna). v2 (a partir do rules_change): mín. 2 observações + veto/saída por queda de liquidez >= 20%. "
          "Sem novas entradas após 08/10/2026 23:00 BRT."]
    return "\n".join(L) + "\n"

def main():
    args = [a for a in sys.argv[1:]]
    if "--final" in args:
        if "--auto" in args and NOW.strftime("%Y-%m-%d") != FINAL_DAY:
            print("--auto: hoje não é", FINAL_DAY, "- nada a fazer"); return
        txt = report(None, "Relatório final — paper trading pump.fun (01/10 a 08/10/2026)")
        p = os.path.join(BASE, "pumpfun-final-report.md")
        open(p, "w").write(txt); print("escrito", p); return
    day = args[0] if args else NOW.strftime("%Y-%m-%d")
    dt = datetime.date.fromisoformat(day)
    txt = report(day, f"Resumo diário pump.fun (paper) — {dt.strftime('%d/%m/%Y')}")
    p1 = os.path.join(BASE, f"pumpfun-daily-{dt.strftime('%Y%m%d')}.md")
    p2 = os.path.join(BASE, "pumpfun-daily-latest.md")
    for p in (p1, p2): open(p, "w").write(txt)
    print("escrito", p1, "e", p2)

if __name__ == "__main__":
    main()
