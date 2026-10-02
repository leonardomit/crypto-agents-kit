# Hermes Meme Scout (Sol / Base / Arbitrum)

- Alert-only. HTTP/script (DexScreener). Sem wallet, trade, seed ou browser.
- Cadência: a cada 30 min, dias úteis 9–18 BRT (`0,30 9-17` + `0 18`).
- `run-meme-scout.sh` → `scripts/meme-scan.sh` → `raw.json` → `make_meme_digest.py` → `latest.md`.
- ACTIONABLE true só com liq≥US$25k, vol24h≥US$50k e |Δ1h|≥8%. Senão silêncio pro orquestrador.
- Size sugerido ≤US$25. Push para o orquestrador só via rotina "meme scout → push" se actionable.
