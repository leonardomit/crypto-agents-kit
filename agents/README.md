# Agentes (templates de prompt)

Prompts sanitizados dos agentes de cripto, prontos para colar em qualquer runtime de agente
(Grok Bot, Hermes Agent, Claude/GPT com tools, OpenAI Agents, etc.). Todos falam **português (BR)**.

| Arquivo | Papel | Opera dinheiro? |
|---|---|---|
| [`orquestrador.md`](orquestrador.md) | Roteia scouts → trader → humano; failover | Não |
| [`defi-scout.md`](defi-scout.md) | DefiLlama pools/lending + memes L2/Sol + revisão de posição | **Não** (alerta only) |
| [`polymarket-scout.md`](polymarket-scout.md) | Mercados Polymarket via Gamma API + sentimento X | **Não** (alerta only) |
| [`crypto-defi-trader.md`](crypto-defi-trader.md) | Executa LP Uni v3 / swaps Uniswap + Jupiter dentro do teto | Sim, ≤ teto (default US$25) |
| [`scout-push-routines.md`](scout-push-routines.md) | Rotinas "lê latest.md do scout → avisa orquestrador se acionável" | Não |

Placeholders usados nos prompts:

- `{{TRADER_AGENT_ID}}`, `{{SCOUT_AGENT_ID}}`, `{{ORCHESTRATOR_AGENT_ID}}` — ids dos agentes no seu runtime
- `{{OWNER}}` — a pessoa que recebe os alertas
- `{{KIT_DIR}}` — caminho do clone deste repo
- `{{MAX_POSITION_USD}}` / `{{BANKROLL_USD}}` — mesmos valores do `.env`
- `{{SCOUT_HOST}}` — máquina onde os scouts rodam via cron (pode ser a mesma do trader)

Os cron schedules são exemplos (fuso America/Sao_Paulo).
