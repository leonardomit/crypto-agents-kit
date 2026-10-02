# Regras do Trader (hard rules)

Nasceram de incidentes reais (ex.: tx enviada a um endereço de router sem bytecode na Arbitrum = fundos perdidos).

1. **Default é simulação.** Live só com `DRY_RUN=0` **e** `--execute`.
2. **Teto por posição**: `min(BANKROLL_USD × MAX_POSITION_PCT%, MAX_POSITION_USD)` — default US$25.
   `lib_caps.assert_size_ok()` aborta acima disso.
3. **Bytecode check**: `assert_live_to()` exige `eth_getCode(to)` não-vazio e endereço fora do `DENYLIST`
   (`tokens.py`) antes de qualquer tx.
4. **Approve exato** do valor — nunca unlimited. `swap_v3_path.py` reseta allowance para 0 se maior.
5. **Aave**: resolver o Pool via `PoolAddressesProvider.getPool()`; nunca confiar em endereço hardcoded de Pool.
6. **Solana**: antes do send, todos os program IDs de topo da tx precisam estar na allowlist
   (Jupiter, Token, Token-2022, ATA, System, ComputeBudget). Reserva ~0.005 SOL para rent.
7. **Chave privada** só via env/secret manager. Nunca impressa, nunca logada, nunca no chat.
8. Sem bridge automático. Sem segundo swap/mint sem pedido/sinal novo.
9. Script falhou → **para e avisa**. Nada de fallback via browser/MetaMask.
10. Gate do agente (`TRADER_MODE`): `manual` = humano aprova cada trade; `auto` = só ≤ teto e com 1–9 ok.

## Defaults de stop (relatórios)

| Tipo | SL | SG | Fixo | Móvel | Técnico |
|---|---|---|---|---|---|
| LP Uni v3 | −20% | fees ≥ +15% ou rebalance | — | — | out-of-range |
| Trade | −20–25% | +30–50% | entrada × (1 − SL) | trail −10% após +15% | invalidação da tese |
| Meme | −8–12% | +15–25% | — | — | timebox 4–12h |
