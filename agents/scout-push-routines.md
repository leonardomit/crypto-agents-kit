# Rotinas "scout → push" (baixo custo)

Os scouts rodam por cron como scripts HTTP puros e escrevem `out/latest.md`. Um agente LLM só é acordado
alguns minutos depois para ler o digest e decidir se avisa. Isso mantém o custo de tokens mínimo.

## Template (ajuste caminho, critério e cron)

> Depois do scout `<NOME>` (cron do script às :00, enrich opcional às :01, você às :06 BRT).
> Objetivo: gastar o mínimo e só avisar o orquestrador quando houver alerta acionável.
> 1. Leia `{{KIT_DIR}}/scouts/<nome>/out/latest.md` com um comando rápido de shell. Se faltar ou estiver
>    velho (> 2h), termine em silêncio.
> 2. Acionável só quando: `<CRITÉRIO>`.
> 3. Se acionável, mande ao orquestrador ({{ORCHESTRATOR_AGENT_ID}}) um resumo curto em português com
>    priority true: ativo/mercado, sinal, link.
> 4. Se não, termine em silêncio. Nada de FYI.
> Nada de trade, carteira ou aposta. Não invente números.

| Scout | Arquivo | Critério de acionável | Cron sugerido |
|---|---|---|---|
| DeFi | `scouts/defi/out/latest.md` + `lending-latest.md` | setup A/B com ticket ≤ teto / `ACTIONABLE: true` | `6 10,12,14,16,18 * * 1-5` |
| Meme | `scouts/meme/out/latest.md` | `ACTIONABLE: true` (2º pool confirma) | `5,35 9-18 * * 1-5` |
| Polymarket | `scouts/polymarket/out/latest.md` | \|edge\| ≥ ~8% ou risco forte marcado | `6 10,12,14,16,18 * * 1-5` |
| On-chain BTC | `scouts/onchain-btc/out/latest.md` | sinal de entrada/saída ≠ inexistente | `40 8,18 * * 1-5` |
