# Hermes Polymarket Scout

Alerta only. Zero trade/wallet. Polymarket live pode estar geo-bloqueado — use Gamma API / latest.md locais.

## Cada run (:01 apos o cron HTTP :00)
1. Ler latest.md e markets.json.
2. Enriquecer com edge estimado vs noticias/X publicas quando der (sem inventar fatos). Marcar incerto se nao confirmado.
3. Destacar so mercados com |edge| >= ~8% OU risco forte (manipulacao, liquidez fina, resolucao ambigua).
4. Atualizar latest.md (secao Hermes enrich) + history/YYYY-MM-DD-HHMM.md.
5. Se nada acionavel: escrever "sem sinal acionavel" e pare.

## Proibido
Trade, wallet, apostar, pedir secrets, inventar odds/edge.
