#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_vault.py — espelha os resultados legíveis dos crons (scouts) no vault Obsidian (pasta $VAULT_FOLDER, default "Grok Bot/").
Só lê os arquivos dos crons (latest.md, history/*.md, pumpfun-*.md, runs.jsonl/paper.jsonl) — NUNCA altera nada deles.
Sem rede, sem LLM. Estado de dedupe fora do vault: $VAULT_SYNC_DIR/state.json.

Layouts de origem (env VAULT_SYNC_LAYOUT):
  hermes (default) — pastas ~/hermes-defi-scout, ~/hermes-meme-scout, ... (instalação original no Hermes)
  kit              — scouts/<nome>/out deste repositório

Uso: sync_vault.py [--vault DIR] [--since YYYY-MM-DD] [--dry]
"""
import os, sys, re, json, glob, hashlib, datetime, time, shutil

HOME = os.path.expanduser("~")
BRT = datetime.timezone(datetime.timedelta(hours=-3), "BRT")
def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else default
    return default
VAULT = arg("--vault", os.environ.get("OBSIDIAN_VAULT") or os.path.join(HOME, "Documents", "Obsidian Vault"))
VAULT_FOLDER = os.environ.get("VAULT_FOLDER", "Grok Bot")
ROOT = os.path.join(VAULT, VAULT_FOLDER)
LAYOUT = os.environ.get("VAULT_SYNC_LAYOUT", "hermes")
KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KIT_DIRS = {"defi": "scouts/defi/out", "polymarket": "scouts/polymarket/out", "meme": "scouts/meme/out",
            "onchain": "scouts/onchain-btc/out", "auditoria": "scouts/auditoria-rotinas/out", "pumpfun": "scouts/pumpfun-paper/out"}
SINCE = arg("--since", "2026-09-28")
DRY = "--dry" in sys.argv
SYNC_DIR = os.environ.get("VAULT_SYNC_DIR") or os.path.join(HOME, "hermes-vault-sync")
STATE_F = os.path.join(SYNC_DIR, "state.json") if "--vault" not in sys.argv else os.path.join(SYNC_DIR, "state-test.json")
LOCK = os.path.join(SYNC_DIR, ".lock")

CRONS = [
    # key, pasta no vault, dir do cron, wrapper, agenda (texto), descrição
    ("defi", "DeFi Scout", "hermes-defi-scout", "run-scout.sh",
     "`0,45 9-17 * * *` + `0 18 * * *` (todo dia)",
     "Varre pools DeFi (DefiLlama yields/TVL, Uni v3 slot0 Base/Arb) e propõe setups ≤US$25. Só alerta, sem trade."),
    ("polymarket", "Polymarket Scout", "hermes-polymarket-scout", "run-polymarket-scout.sh",
     "`0,45 9-17 * * *` + `0 18 * * *` (todo dia)",
     "Top mercados Polymarket por volume 24h (Gamma API) e alertas de edge. Só alerta, sem trade."),
    ("meme", "Meme Scout", "hermes-meme-scout", "run-meme-scout.sh",
     "`0,30 9-17 * * *` + `0 18 * * *` (todo dia)",
     "Pares de memecoins Sol/Base/Arb/Eth/BSC via DexScreener; marca ACTIONABLE quando passa a barra. Sem trade."),
    ("onchain", "On-Chain BTC", "hermes-onchain", "run-onchain.sh",
     "`30 8 * * 1-5` + `30 18 * * 1-5` (dias úteis)",
     "Relatório BTC: preço, Fear & Greed, mempool, hashrate, TVL; score /10 e sinais."),
    ("auditoria", "Auditoria", "hermes-auditoria-rotinas", "run-auditoria.sh",
     "`0 9 * * 1` (segunda)",
     "Auditoria semanal das rotinas Grok/Hermes: propõe o que pode virar script. Só proposta."),
    ("pumpfun", "Pump.fun Paper", "hermes-memes", "run-pumpfun.sh",
     "scanner `*/15 9-22 * * *` + `0 23 * * *`; resumo `5 23 * * *`; final `10 23 8 10 *`",
     "Scanner de memecoins novas do pump.fun em PAPER TRADING (simulação US$4/entrada, sem carteira). Até 08/10/2026."),
]

# ------------------------------------------------------------------ redaction
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
REDACT = [
    (re.compile(r"\bEAA[A-Za-z0-9]{20,}"), "[REDACTED:meta-token]"),
    (re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{16,}"), "[REDACTED:sk-key]"),
    (re.compile(r"\bxai-[A-Za-z0-9_\-]{16,}"), "[REDACTED:xai-key]"),
    (re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"), "[REDACTED:github-token]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), "[REDACTED:slack-token]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED:aws-key]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "[REDACTED:google-key]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), "[REDACTED:jwt]"),
    (re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=\-]{10,}"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)\b(authorization|x-api-key|api[_-]?key|apikey|access[_-]?token|secret|password|passwd|private[_-]?key)(\s*[:=]\s*)[\"']?[^\s\"'&|,)]{6,}"),
     r"\1\2[REDACTED]"),
    (re.compile(r"(?i)([?&](?:api[_-]?key|key|token|access_token|secret|sig|signature)=)[^&\s)]+"), r"\1[REDACTED]"),
    # hex longo SEM prefixo 0x (endereço EVM 0x+40 e tx hash 0x+64 ficam); só se tiver letra a-f
    (re.compile(r"(?<![0-9A-Za-z])(?<!0x)(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{64,}(?![0-9A-Za-z])"), "[REDACTED:hex]"),
    # base58 muito longo (chave privada Solana ~87-88); endereços/mints (32-44) ficam
]
B58_RX = re.compile(r"(?<![%s])[%s]{60,}(?![%s])" % (B58, B58, B58))
HEX_RX = re.compile(r"^x[0-9a-fA-F]+$")
def _b58(m):
    # '0x' + hex (tx hash EVM) não é base58: o '0' fica fora do alfabeto e sobra 'x...'
    if m.start() > 0 and m.string[m.start() - 1] == "0" and HEX_RX.match(m.group(0)): return m.group(0)
    return "[REDACTED:base58]"
def scrub(text):
    n = 0
    for rx, rep in REDACT:
        text, k = rx.subn(rep, text); n += k
    before = text.count("[REDACTED:base58]")
    text = B58_RX.sub(_b58, text)
    n += text.count("[REDACTED:base58]") - before
    return text, n

# ------------------------------------------------------------------ helpers
def now(): return datetime.datetime.now(BRT)
def h(s): return hashlib.sha256(re.sub(r"\s+", " ", s).strip().encode()).hexdigest()[:20]
def read(p):
    with open(p, encoding="utf-8", errors="replace") as f: return f.read()
def mtime_dt(p): return datetime.datetime.fromtimestamp(os.path.getmtime(p), BRT)

def write(path, text):
    if DRY:
        print(f"[dry] write {path} ({len(text)}b)"); return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path) and read(path) == text: return
    tmp = path + ".tmp-sync"
    with open(tmp, "w", encoding="utf-8") as f: f.write(text)
    os.replace(tmp, path)

def demote(md, levels=2):
    """Rebaixa títulos (# -> ###) fora de blocos de código, para caber sob '## HH:MM BRT'."""
    out, fence = [], False
    for line in md.splitlines():
        if line.lstrip().startswith("```"): fence = not fence
        if not fence and re.match(r"^#{1,6}\s", line):
            hashes = len(line) - len(line.lstrip("#"))
            line = "#" * min(6, hashes + levels) + line[hashes:]
        out.append(line)
    return "\n".join(out).strip() + "\n"

def parse_hist_name(name):
    m = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})(?:-(\d{2})(\d{2}))?\.md$", name)
    if not m: return None
    y, mo, d, hh, mm = m.groups()
    return datetime.datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0), tzinfo=BRT)

def load_state():
    try: return json.load(open(STATE_F))
    except Exception: return {"hashes": {}, "pumpfun_runs": [], "files": {}, "redactions": 0}

def save_state(st):
    if DRY: return
    for k, v in st["hashes"].items(): st["hashes"][k] = v[-3000:]
    st["pumpfun_runs"] = st["pumpfun_runs"][-3000:]
    tmp = STATE_F + ".tmp"
    json.dump(st, open(tmp, "w"), indent=1); os.replace(tmp, STATE_F)

STATS = {}
def stat(key, k, n=1):
    STATS.setdefault(key, {}); STATS[key][k] = STATS[key].get(k, 0) + n

def daily_note_path(folder, dt): return os.path.join(ROOT, folder, dt.strftime("%Y-%m-%d") + ".md")

def append_daily(key, folder, title, dt, body, st):
    """Acrescenta '## HH:MM BRT' + digest à nota diária, se o hash ainda não foi visto."""
    body, nred = scrub(body)
    hv = h(body)
    seen = st["hashes"].setdefault(key, [])
    if hv in seen:
        stat(key, "dup"); return False
    p = daily_note_path(folder, dt)
    if DRY:
        print(f"[dry] append {p} {dt:%H:%M}")
    else:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"---\ntags: [grok-bot, {key}]\n---\n# {title} — {dt:%d/%m/%Y}\n\n"
                        f"Execuções do cron (mais antiga primeiro). Índice: [[{VAULT_FOLDER}/README|{VAULT_FOLDER}]] · [[{VAULT_FOLDER}/{folder}/latest|latest]]\n")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"\n## {dt:%H:%M} BRT\n\n{demote(body)}")
    seen.append(hv); st["redactions"] = st.get("redactions", 0) + nred
    stat(key, "appended"); stat(key, "days:" + dt.strftime("%Y-%m-%d"))
    return True

def write_latest(key, folder, title, src_path, extra=""):
    if not os.path.exists(src_path): return
    body, nred = scrub(read(src_path))
    dt = mtime_dt(src_path)
    txt = (f"---\ntags: [grok-bot, {key}, latest]\n---\n> [!info] {title} — última execução\n"
           f"> Atualizado {dt:%d/%m/%Y %H:%M} BRT · origem `~/{os.path.relpath(src_path, HOME)}` · "
           f"[[{VAULT_FOLDER}/README|índice]]{extra}\n\n{body.strip()}\n")
    write(os.path.join(ROOT, folder, "latest.md"), txt)

# ------------------------------------------------------------------ crons genéricos
def sync_generic(key, folder, d, title, st):
    since = datetime.datetime.fromisoformat(SINCE).replace(tzinfo=BRT)
    items = []
    for p in glob.glob(os.path.join(d, "history", "*.md")):
        dt = parse_hist_name(os.path.basename(p))
        if dt and dt >= since: items.append((dt, p))
    latest = os.path.join(d, "latest.md")
    if os.path.exists(latest) and mtime_dt(latest) >= since:
        items.append((mtime_dt(latest), latest))
    items.sort()
    for dt, p in items:
        body = read(p)
        if not body.strip(): continue
        append_daily(key, folder, title, dt, body, st)
    write_latest(key, folder, title, latest)

def sync_auditoria(key, folder, d, title, st):
    """Relatórios semanais como notas próprias + latest."""
    for p in sorted(glob.glob(os.path.join(d, "history", "*.md"))):
        dt = parse_hist_name(os.path.basename(p))
        if not dt: continue
        body, nred = scrub(read(p))
        name = f"Auditoria {dt:%Y-%m-%d}.md"
        txt = (f"---\ntags: [grok-bot, auditoria]\n---\n> [!info] Auditoria semanal de rotinas — {dt:%d/%m/%Y}\n"
               f"> Origem `~/{os.path.relpath(p, HOME)}` · [[{VAULT_FOLDER}/README|índice]] · [[{VAULT_FOLDER}/{folder}/latest|latest]]\n\n"
               f"{body.strip()}\n")
        hv = h(txt)
        if st["files"].get(name) != hv:
            write(os.path.join(ROOT, folder, name), txt); st["files"][name] = hv; stat(key, "notes")
        stat(key, "days:" + dt.strftime("%Y-%m-%d"))
    write_latest(key, folder, title, os.path.join(d, "latest.md"))

# ------------------------------------------------------------------ pump.fun
def rj(path):
    out = []
    if not os.path.exists(path): return out
    for line in open(path, encoding="utf-8", errors="replace"):
        try: out.append(json.loads(line))
        except Exception: pass
    return out

def fmt_ev(e):
    t = e.get("ts", "")[11:16]; s = e.get("symbol") or "?"; m = e.get("mint", "")
    k = e.get("event")
    if k == "entry":
        r = e.get("entry_reason") or {}
        return (f"- {t} 🟢 **ENTRADA** {s} `{m}` @ US${e.get('price_usd'):.8g} · US${e.get('entry_usd', 4):.0f} · "
                f"slip {100*(e.get('slippage_est') or 0):.2f}% · liq US${(r.get('liq_usd') or 0):,.0f} · "
                f"idade {r.get('idade_h')}h · top10 {r.get('top10_pct')}% · rug {r.get('rug_score_norm')}")
    if k in ("partial_exit", "exit"):
        extra = f" · trade {e.get('trade_pnl_usd'):+.2f} US$ ({e.get('trade_pnl_pct'):+.1f}%)" if k == "exit" else ""
        return (f"- {t} {'🔴' if (e.get('pnl_usd') or 0) < 0 else '🟡'} **{'SAÍDA' if k == 'exit' else 'SAÍDA PARCIAL'}** "
                f"{s} @ US${e.get('price_usd'):.8g} ({e.get('variacao_pct'):+.1f}%) — {e.get('exit_reason')} · "
                f"P&L {e.get('pnl_usd'):+.2f} US${extra}")
    if k == "signal":
        return f"- {t} 📡 sinal {s} `{m}`" + ("" if e.get("entrou") else f" — {e.get('obs') or 'sem entrada'}")
    if k == "rules_change":
        return f"- {t} ⚙️ **mudança de regras v{e.get('rules_version')}**: " + "; ".join(e.get("changes") or [])
    return f"- {t} {k} {s}"

def run_digest(r, evs):
    s = r.get("stats") or {}
    if r.get("fatal"):
        return "**ERRO FATAL no ciclo** — ver `logs/` do pumpfun-paper.\n" + "\n".join(evs) + "\n"
    top = sorted((s.get("rejeicoes") or {}).items(), key=lambda x: -x[1])[:3]
    src_err = [f"{k} ({v.get('err')} erro(s): {v.get('last_err')})" for k, v in (r.get("sources") or {}).items() if v.get("err")]
    L = [f"- Descobertos {s.get('descobertos', 0)} · avaliados {s.get('avaliados', 0)} · passaram {s.get('passaram', 0)} · "
         f"entradas {s.get('entradas', 0)} · abertas {r.get('open', 0)} · P&L realizado acumulado US${r.get('realized_pnl_usd', 0):+.2f}"]
    if top: L.append("- Principais rejeições: " + "; ".join(f"{k} ({v})" for k, v in top))
    L.append("- Fontes: " + ("todas OK" if not src_err else "; ".join(src_err)))
    L += evs
    return "\n".join(L) + "\n"

def sync_pumpfun(key, folder, d, title, st):
    runs = rj(os.path.join(d, "logs", "runs.jsonl"))
    evs = [e for e in rj(os.path.join(d, "pumpfun-paper.jsonl")) if e.get("event") != "signal" or True]
    done = set(st["pumpfun_runs"])
    prev_ts = ""
    for r in sorted(runs, key=lambda x: x.get("ts", "")):
        ts = r.get("ts", "")
        mine = [fmt_ev(e) for e in evs if prev_ts < e.get("ts", "") <= ts and e.get("event") != "signal"]
        nsig = sum(1 for e in evs if prev_ts < e.get("ts", "") <= ts and e.get("event") == "signal")
        prev_ts = ts
        if ts in done or ts[:10] < SINCE: continue
        dt = datetime.datetime.fromisoformat(ts).astimezone(BRT)
        body = run_digest(r, mine)
        if nsig: body += f"- Sinais novos no ciclo: {nsig}\n"
        body = f"Ciclo `{ts}`\n\n" + body   # ts único -> hash único por ciclo
        append_daily(key, folder, title, dt, body, st)
        st["pumpfun_runs"].append(ts)
    # resumos diários como notas próprias
    for p in sorted(glob.glob(os.path.join(d, "pumpfun-daily-2*.md"))):
        m = re.search(r"(\d{4})(\d{2})(\d{2})", os.path.basename(p))
        name = f"Resumo {m.group(1)}-{m.group(2)}-{m.group(3)}.md"
        body, _ = scrub(read(p))
        txt = (f"---\ntags: [grok-bot, pumpfun, resumo]\n---\n> [!info] Pump.fun Paper — resumo diário (simulação)\n"
               f"> Origem `~/{os.path.relpath(p, HOME)}` · [[{VAULT_FOLDER}/README|índice]] · [[{VAULT_FOLDER}/{folder}/latest|latest]]\n\n{body.strip()}\n")
        hv = h(txt)
        if st["files"].get(name) != hv:
            write(os.path.join(ROOT, folder, name), txt); st["files"][name] = hv; stat(key, "notes")
    fr = os.path.join(d, "pumpfun-final-report.md")
    if os.path.exists(fr):
        body, _ = scrub(read(fr))
        txt = (f"---\ntags: [grok-bot, pumpfun, relatorio-final]\n---\n> [!info] Pump.fun Paper — relatório final (simulação)\n"
               f"> Atualizado {mtime_dt(fr):%d/%m/%Y %H:%M} BRT · origem `pumpfun-final-report.md` · "
               f"[[{VAULT_FOLDER}/README|índice]]\n\n{body.strip()}\n")
        hv = h(txt)
        if st["files"].get("Relatório final.md") != hv:
            write(os.path.join(ROOT, folder, "Relatório final.md"), txt); st["files"]["Relatório final.md"] = hv; stat(key, "notes")
    # latest: último ciclo + resumo diário mais recente
    if runs:
        r = max(runs, key=lambda x: x.get("ts", ""))
        lr = os.path.join(d, "pumpfun-daily-latest.md")
        txt = (f"---\ntags: [grok-bot, pumpfun, latest]\n---\n> [!info] Pump.fun Paper — último ciclo (simulação, sem ordens reais)\n"
               f"> Ciclo {r.get('ts')} · [[{VAULT_FOLDER}/README|índice]] · [[{VAULT_FOLDER}/{folder}/{r.get('ts', '')[:10]}|nota do dia]]\n\n"
               f"## Último ciclo\n\n{run_digest(r, [])}\n")
        if os.path.exists(lr):
            txt += "\n" + demote(scrub(read(lr))[0], 1)
        write(os.path.join(ROOT, folder, "latest.md"), txt)

# ------------------------------------------------------------------ README
def write_readme():
    L = ["---", "tags: [grok-bot, indice]", "---", f"# {VAULT_FOLDER} — crons dos scouts", "",
         f"_Espelho automático gerado por `sync_vault.py` (cron `3,18,33,48 8-23 * * *`). "
         f"Última sincronização: {now():%d/%m/%Y %H:%M} BRT._", "",
         "Só leitura dos resultados — os arquivos originais (latest.md, history/, jsonl) ficam nas pastas dos crons e não são alterados. "
         "Segredos são mascarados por regex. Nada aqui é ordem de trade.", "",
         "| Cron | O que faz | Agenda (BRT) | Script | Notas |", "|---|---|---|---|---|"]
    for key, folder, d, wrapper, sched, desc in CRONS:
        extra = ""
        # dentro de tabela o '|' do alias precisa ser escapado (\|)
        if key == "pumpfun": extra = f" · [[{VAULT_FOLDER}/{folder}/Relatório final\\|relatório final]]"
        L.append(f"| **{folder}** | {desc} | {sched} | `~/{d}/{wrapper}` | [[{VAULT_FOLDER}/{folder}/latest\\|latest]]{extra} |")
    L += ["", "## Estrutura", "",
          "- `<cron>/latest.md` — sobrescrito a cada execução.",
          "- `<cron>/AAAA-MM-DD.md` — nota diária; cada execução vira uma seção `## HH:MM BRT` (dedupe por hash).",
          "- `Auditoria/Auditoria AAAA-MM-DD.md` — relatórios semanais.",
          "- `Pump.fun Paper/Resumo AAAA-MM-DD.md` (resumo diário 23:05) e `Relatório final.md`.", ""]
    write(os.path.join(ROOT, "README.md"), "\n".join(L) + "\n")

def main():
    os.makedirs(SYNC_DIR, exist_ok=True)
    if not os.path.isdir(VAULT):
        print("vault não encontrado:", VAULT); return 0
    try:
        os.mkdir(LOCK)
    except FileExistsError:
        if time.time() - os.path.getmtime(LOCK) < 600:
            print("outra sincronização em andamento; saindo"); return 0
        shutil.rmtree(LOCK, ignore_errors=True); os.mkdir(LOCK)
    try:
        st = load_state()
        for key, folder, d, wrapper, sched, desc in CRONS:
            dd = os.path.join(KIT, KIT_DIRS[key]) if LAYOUT == "kit" else os.path.join(HOME, d)
            if not os.path.isdir(dd): continue
            try:
                if key == "pumpfun": sync_pumpfun(key, folder, dd, folder, st)
                elif key == "auditoria": sync_auditoria(key, folder, dd, folder, st)
                else: sync_generic(key, folder, dd, folder, st)
            except Exception as e:
                print(f"[{now():%Y-%m-%d %H:%M}] erro em {key}: {type(e).__name__}: {e}")
        write_readme()
        st["last_sync"] = now().isoformat(timespec="seconds")
        save_state(st)
        summ = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("days:")} | {"dias": sorted(kk[5:] for kk in v if kk.startswith("days:"))}
                for k, v in STATS.items()}
        print(f"[{now():%Y-%m-%d %H:%M}] sync ok: " + json.dumps(summ, ensure_ascii=False))
    finally:
        shutil.rmtree(LOCK, ignore_errors=True)
    return 0

if __name__ == "__main__":
    try: sys.exit(main())
    except Exception as e:
        print(f"[{now():%Y-%m-%d %H:%M}] ERRO: {type(e).__name__}: {e}"); sys.exit(0)
