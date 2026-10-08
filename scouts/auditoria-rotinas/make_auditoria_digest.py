#!/usr/bin/env python3
"""Classify agent routines (Grok Bot / Hermes / outros) for script migration. Propose only — never apply.

Entrada: $SCOUT_OUT_DIR/routines-inventory.json (exportado pelo orquestrador; ver README).
"""
import json, os
from datetime import datetime
from pathlib import Path

base = Path((os.environ.get("SCOUT_OUT_DIR") or Path(__file__).resolve().parent / "out"))
base.mkdir(parents=True, exist_ok=True)
inv_path = base / "routines-inventory.json"
out = base / "latest.md"
prev = base / "proposed-last-week.json"

inv = json.loads(inv_path.read_text())
prev_ids = set()
if prev.exists():
    try:
        prev_ids = set(json.loads(prev.read_text()).get("ids", []))
    except Exception:
        prev_ids = set()

def classify(r):
    p = (r.get("prompt_excerpt") or "").lower()
    name = (r.get("routine") or "").lower()
    # Heuristics
    if any(k in p for k in ("gamma-api", "defillama", "curl", "http/script", "script http", "jq", "yields.llama")):
        return "ja-api"
    if any(k in p for k in ("browser", "clique", "click", "navegador", "playwright", "metamask")):
        return "candidata-a-script"
    if r.get("trigger_type") == "linear" or "linear" in name:
        return "precisa-browser-ou-connector"  # Linear MCP already — keep connector
    if any(k in p for k in ("wallet", "trade", "swap", "lp_", "dry-run", "live")):
        return "execucao-ficar-grok"  # money path stays on Grok
    if not r.get("enabled"):
        return "pausada-revisar"
    return "candidata-a-script" if "scan" in name or "briefing" in name or "relat" in name else "revisar-manual"

cands = []
lines = [
    "# Auditoria de Rotinas → Script",
    f"_BRT {datetime.now().strftime('%Y-%m-%d %H:%M')} · inventário {inv.get('exported_brt')}_",
    "",
    "Só proposta. O humano confirma antes de aplicar. Preferência: conector > script HTTP > browser.",
    "",
]
by = {"ja-api": [], "candidata-a-script": [], "precisa-browser-ou-connector": [], "execucao-ficar-grok": [], "pausada-revisar": [], "revisar-manual": []}
for r in inv.get("routines", []):
    by[classify(r)].append(r)

lines.append("## Resumo")
for k, v in by.items():
    lines.append(f"- **{k}**: {len(v)}")
lines.append("")

new_ids = []
lines.append("## Candidatas novas (proposta)")
shown = 0
for r in by["candidata-a-script"] + by["revisar-manual"]:
    rid = f"{r.get('agent_dir')}/{r.get('folder')}"
    if rid in prev_ids:
        continue
    if not r.get("enabled") and classify(r) == "pausada-revisar":
        continue
    new_ids.append(rid)
    shown += 1
    lines.append(f"### {shown}. {r.get('agent')} — {r.get('routine')}")
    lines.append(f"- Estado: enabled={r.get('enabled')} · schedule/trigger: {r.get('schedule') or r.get('trigger_type')}")
    lines.append(f"- Por quê: parece depender de browser/agente em vez de HTTP/conector.")
    lines.append(f"- Esboço: trocar por script/API ou MCP; output = digest markdown; auth via secrets/env, nunca no chat.")
    lines.append(f"- Risco: baixo se só leitura; alto se publica/trade — aí não migrar sem gate.")
    lines.append("")
if shown == 0:
    lines.append("Nenhuma candidata nova esta semana.")
    lines.append("")

lines.append("## Já API / execução Grok (não mexer sem pedido)")
for r in by["ja-api"][:8]:
    lines.append(f"- {r.get('agent')} / {r.get('routine')} (já-API)")
for r in by["execucao-ficar-grok"][:8]:
    lines.append(f"- {r.get('agent')} / {r.get('routine')} (execução/caixa → Grok)")
lines.append("")
lines.append("_Push pro orquestrador só se houver candidata nova._")

out.write_text("\n".join(lines) + "\n")
prev.write_text(json.dumps({"ids": sorted(set(prev_ids) | set(new_ids)), "when": datetime.now().isoformat()}, indent=2))
print(out.read_text()[:2500])
