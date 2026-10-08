# hermes/ — rodando os scouts com o Hermes Agent

Como os scouts deste kit rodam numa máquina com o [Hermes Agent](https://hermes-agent.nousresearch.com)
(ex.: um Mac mini sempre ligado): **cron do sistema** roda os scripts HTTP (sem LLM, custo zero) e
**jobs do Hermes** enriquecem o digest com LLM alguns minutos depois e entregam o alerta.

| Arquivo | O quê |
|---|---|
| `crontab.hermes.example` | crontab das linhas cripto (scouts, pump.fun v3 com `--positions-only`, auditoria, vault-sync) |
| `jobs.crypto.example.json` | extrato **redigido** dos jobs cripto do `~/.hermes/cron/jobs.json`: nome, agenda, `script`/`no_agent` e prompt. Sem deliver, ids, tokens ou estado |
| `vault-sync/sync_vault.py` | espelha os resultados (latest.md, history/, resumos do pump.fun) no Obsidian, com dedupe por hash e máscara de segredos por regex. Só lê; sem rede |

## Jobs do Hermes (resumo)

| Job | Agenda (BRT) | Tipo | O que faz |
|---|---|---|---|
| DeFi Scout | `1,46 9-18 * * 1-5` | `script: defi_scout.py`, `no_agent: true` | roda `scouts/defi/defi_scout.py` (copie para `~/.hermes/scripts/`); stdout vira alerta só se houver 2–3 setups A/B novos |
| On-Chain BTC Report | `32 8,18 * * 1-5` | agente | lê `snapshot.json`, completa métricas públicas, score/10 e sinais; não inventa MVRV/NUPL/SOPR |
| Polymarket Scout Enrich | `1,46 9-18 * * 1-5` | agente + skill `polymarket-scout` | cruza notícias públicas, destaca só \|edge\| ≥ 8 pp ou risco forte |
| Auditoria de Rotinas Enrich | `1 9 * * 1` | agente | enriquece candidatas novas a script; nunca aplica |

O skill do Polymarket está em [`../skills/polymarket-scout/SKILL.md`](../skills/polymarket-scout/SKILL.md)
(copie para `~/.hermes/skills/polymarket-scout/`).

## Vault sync

```bash
OBSIDIAN_VAULT="$HOME/Documents/Obsidian Vault" VAULT_FOLDER="Grok Bot" VAULT_SYNC_LAYOUT=kit \
  python3 hermes/vault-sync/sync_vault.py --dry      # mostra o que escreveria
```

`VAULT_SYNC_LAYOUT=hermes` (default) lê as pastas `~/hermes-<scout>` da instalação original; `kit` lê
`scouts/<nome>/out/` deste repositório. Estado de dedupe em `$VAULT_SYNC_DIR` (default `~/hermes-vault-sync`).

> Nunca commite o `jobs.json` real: ele guarda destinos de entrega e, às vezes, tokens de outras integrações.
