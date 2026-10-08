# auditoria-rotinas — rotinas de agente → script (só proposta)

Classifica as rotinas dos seus agentes e propõe trocar browser/cliques por script HTTP ou conector MCP
(economia de tokens). **Nunca aplica nada**; o humano confirma.

- `run-auditoria.sh` — wrapper do cron (segunda 09:00). Sai com aviso se não houver inventário.
- `make_auditoria_digest.py` — lê `out/routines-inventory.json`, gera `out/latest.md` e `out/proposed-last-week.json`
  (dedupe: candidata já proposta não volta na semana seguinte).
- `AGENTS.md` — prompt curto do agente que enriquece o digest (job "Auditoria de Rotinas Enrich", `1 9 * * 1`).

## Formato esperado do inventário (exemplo)

```json
{
  "exported_brt": "2026-10-05 08:55",
  "routines": [
    {"agent": "DeFi Scout", "agent_dir": "defi-scout", "routine": "Scan DefiLlama pools", "folder": "scan-defillama",
     "enabled": true, "schedule": "30 9,13,17 * * 1-5", "trigger_type": "cron",
     "prompt_excerpt": "curl yields.llama.fi ... jq ..."}
  ]
}
```

O inventário real contém os prompts das suas rotinas — **não commite** (`out/` é gitignored).
Obs.: a classificação é heurística por palavra-chave em `prompt_excerpt`/`routine`; se o seu exportador usar
outros nomes de campo, ajuste `classify()`.
