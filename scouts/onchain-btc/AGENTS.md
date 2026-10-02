# Hermes On-Chain BTC Report

Missao: relatorio on-chain/mercado alerta only a partir de snapshot.json / HTTP publico.
Sem trade, sem wallet, sem inventar metricas.

## Cada run
1. Ler snapshot.json e latest.md.
2. Completar via HTTP publico (CoinGecko, F&G, DefiLlama, mempool). Se MVRV/NUPL/SOPR nao vierem: Dado atual nao confirmado.
3. Atualizar latest.md PT-BR: timestamp BRT; metricas; 3 frases decisao; score /10; sinais Fraco/Moderado/Forte ou inexistente.
4. Copiar para history/YYYY-MM-DD-HHMM.md.
5. Final: score, sinal, path.

## Proibido
Inventar numeros. Trade. Wallet. Secrets.
