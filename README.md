# crypto-agents-kit

Kit de agentes cripto **alerta-first**: scouts que só observam (DeFi/lending, memes, Polymarket, pump.fun
paper, on-chain BTC) alimentam um **trader** com teto baixo por posição (Uniswap v3 na Arbitrum + Jupiter na
Solana), com gate humano ou automático. Inclui prompts de agentes, skill de relatório on-chain BTC,
ferramentas de research e um painel BTC on-chain.

> ⚠️ **Não é recomendação financeira.** Software experimental, sem garantia. Cripto/DeFi envolve risco de
> perda total (smart contract, IL, rug, slippage, bugs nestes scripts). Use **hot wallet dedicada** com
> valor que você aceita perder, revise o código e rode tudo em `DRY_RUN=1` antes.

## Arquitetura

```
             cron (HTTP público, sem wallet)                       agente LLM (barato: só lê digest)
┌──────────────────────────────────────────────┐        ┌──────────────────────────────────────────┐
│ scouts/defi        DefiLlama pools + lending │        │ scout-push: lê out/latest.md             │
│ scouts/meme        DexScreener multi-chain   │──────▶ │  acionável? → orquestrador (priority)    │
│ scouts/polymarket  Gamma API                 │ latest │  senão → silêncio                        │
│ scouts/pumpfun-paper  simulação pump.fun     │  .md   └───────────────────┬──────────────────────┘
│ scouts/onchain-btc CoinGecko/F&G/mempool     │                            │
└──────────────────────────────────────────────┘                            ▼
                                                        ┌──────────────────────────────────────────┐
                                                        │ orquestrador → avisa humano              │
                                                        │            → aciona Trader se ≤ teto     │
                                                        └───────────────────┬──────────────────────┘
                                                                            ▼
                                     ┌──────────────────────────────────────────────────────────────┐
                                     │ trader/  gate: TRADER_MODE=manual (humano aprova)            │
                                     │                ou auto (só se size ≤ US$25 + checks)         │
                                     │  dry-run → bytecode/denylist → approve exato → live          │
                                     └──────────────────────────────────────────────────────────────┘
```

- **Scouts nunca operam.** São scripts determinísticos; o LLM só enriquece/decide se avisa.
- **Trader** é o único com chave. Teto `MAX_POSITION_USD` (default US$25), `DRY_RUN=1` por default,
  live exige `DRY_RUN=0` **e** `--execute`. Regras em [`trader/RULES.md`](trader/RULES.md).

## O que tem aqui

| Pasta | Conteúdo |
|---|---|
| [`scouts/`](scouts/) | defi (DefiLlama pools + lending + `defi_scout.py` compartilhado), meme (DexScreener, confirmação cruzada), polymarket (Gamma), pumpfun-paper (simulação v3), onchain-btc, auditoria-rotinas |
| [`trader/`](trader/) | swap Uniswap v3 (single/multi-hop, ARB cadastrado), LP enter/exit Uni v3 + monitor de saída OOR, Aave supply, bridge Relay (`bridge_exec.py`), multichain Base/BNB, relatório de posições, swap Jupiter/Solana |
| [`agents/`](agents/) | prompts (perfil + rotinas) de DeFi Scout, Polymarket Scout, Trader, orquestrador e rotinas de push |
| [`skills/`](skills/) | `relatorio-onchain-btc/SKILL.md`, `polymarket-scout/SKILL.md` (regras de edge do enrich) |
| [`hermes/`](hermes/) | crontab e jobs (redigidos) para rodar no Hermes Agent, `vault-sync` para Obsidian |
| [`research/`](research/) | comparador de opções (Deribit/Derive/Aevo) e de bridges (Across/LI.FI/Relay/deBridge) |
| [`dashboard/`](dashboard/) | painel BTC on-chain estático (`btc-onchain.html` + `fetch_market.py`, dados públicos) |

## Setup

```bash
git clone <este repo> crypto-agents-kit && cd crypto-agents-kit
cp .env.example .env            # preencha; .env é gitignored
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt # só o trader precisa; scouts usam stdlib + curl + jq
set -a; . ./.env; set +a

# scouts (não precisam de .env)
bash scouts/defi/run-scout.sh
python3 scouts/defi/defillama_lending_scout.py
bash scouts/meme/run-meme-scout.sh
bash scouts/polymarket/run-polymarket-scout.sh
bash scouts/onchain-btc/run-onchain.sh
bash scouts/pumpfun-paper/run-pumpfun.sh --dry
bash scouts/auditoria-rotinas/run-auditoria.sh   # precisa de out/routines-inventory.json

# trader (dry-run)
python trader/validate-wallet.py
python trader/report-positions.py
bash trader/run-dry-swap-arb.sh
bash trader/run-dry-sol-swap.sh

# painel
bash dashboard/serve.sh   # http://127.0.0.1:8765/btc-onchain.html
```

Depois cole os prompts de [`agents/`](agents/) no seu runtime de agentes, trocando os `{{PLACEHOLDERS}}`.

## Cron

Veja [`crontab.example`](crontab.example). Resumo (America/Sao_Paulo, dias úteis):

```cron
30 9,11,13,15,17,18 * * 1-5  bash $KIT/scouts/defi/run-scout.sh
0,30 9-17 * * 1-5            bash $KIT/scouts/meme/run-meme-scout.sh
0 10,12,14,16,18 * * 1-5     bash $KIT/scouts/polymarket/run-polymarket-scout.sh
30 8,18 * * 1-5              bash $KIT/scouts/onchain-btc/run-onchain.sh
*/15 * * * *                 bash $KIT/scouts/pumpfun-paper/run-pumpfun.sh
*/5 * * * *                  bash $KIT/scouts/pumpfun-paper/run-pumpfun.sh --positions-only
0 9 * * 1                    bash $KIT/scouts/auditoria-rotinas/run-auditoria.sh
```

Rodando com Hermes Agent: [`hermes/crontab.hermes.example`](hermes/crontab.hermes.example). Novidades: [`CHANGELOG.md`](CHANGELOG.md).

O trader **não** roda por cron direto: é acionado pelo agente Trader (que segue o gate).

## Segurança

- Nunca commite `.env`, chaves, seed phrases, RPC com API key, webhooks.
- Use uma carteira dedicada só para isto. Endereços de contratos em `tokens.py`/scripts são **contratos
  públicos** (Uniswap, Aave, tokens) — confira em explorers antes de usar.
- Rode um secret scan antes de qualquer push (`gitleaks detect`).

## Licença

MIT — ver [`LICENSE`](LICENSE).
