# Research

Ferramentas ad-hoc de pesquisa (read-only, HTTP público).

- `options/` — compara puts ~7d (ATM, −5%, −10%) de BTC/ETH em Deribit, Derive (Lyra) e Aevo:
  `cd options && ./fetch_options_data.sh && python3 opt_deribit.py && python3 opt_derive.py && python3 opt_aevo.py`
- `bridge/bridge_quotes.py` — cota bridge de US$20 USDC entre Arbitrum/Base/Ethereum/BSC/Solana em
  Across, LI.FI, Relay e deBridge → `quotes.json`. Usa endereço burn (`0x…dEaD`) só para cotação.
