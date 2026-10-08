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
| Meme | `scouts/meme/out/latest.md` | `ACTIONABLE: true` (2º pool ≥US$100k confirma, ≥ metade da força, preço a ≤3%; execução ≥US$100k) | `5,35 9-18 * * 1-5` |
| Polymarket | `scouts/polymarket/out/latest.md` | \|edge\| ≥ 8 pp (ver regras abaixo) ou risco forte marcado | `6 10,12,14,16,18 * * 1-5` |
| On-chain BTC | `scouts/onchain-btc/out/latest.md` | sinal de entrada/saída ≠ inexistente | `40 8,18 * * 1-5` |

## Regras de push do Polymarket (desde 10/2026)

- Push **só** quando |edge| ≥ 8 pontos percentuais (pp). "Perto de 8" não conta.
- Mercado **novo** no digest também precisa de edge estimado ≥ 8 pp — novidade sozinha não é alerta.
- A data da fonte (notícia, pesquisa, print) tem que cair **dentro da janela do mercado**; fonte antiga ou de
  outro período não sustenta edge.
- Pesquisa/intenção de voto, share do 1º turno e manchete que cita o próprio mercado **não** são P(vitória).
- Mercado `resolved`/`proposed`/`disputed` não é edge aberto. Detalhes no skill
  [`skills/polymarket-scout/SKILL.md`](../skills/polymarket-scout/SKILL.md).

## Meme Scout — barra de ACTIONABLE (desde 02/10/2026)

1. liq ≥ US$25k, vol24h ≥ US$50k e |Δ1h| ≥ 8% no pool do sinal;
2. **confirmação cruzada**: outro pool do mesmo token com liquidez ≥ US$100k, ≥ metade da força do movimento e
   preço a no máximo 3% do pool do sinal;
3. pool de execução (o mais líquido do token na chain) com liquidez ≥ US$100k — o link aponta para ele;
4. só para long: preço ≤ 5% abaixo da máxima 1h estimada (snapshots `history/raw-*.json` dos últimos 60 min);
5. fade/short: só rótulo informativo "Short disponível" (perp líquido na Hyperliquid) — não muda ACTIONABLE.
Cada execução salva o raw em `out/history/raw-YYYYMMDD-HHMM.json`; `make_meme_digest.py --replay <arquivo>` reprocessa sem gravar.
