#!/usr/bin/env bash
# Baixa dados públicos de opções (Deribit, Derive/Lyra, Aevo) para os scripts opt_*.py.
# Uso: cd research/options && ./fetch_options_data.sh && python3 opt_deribit.py
set -euo pipefail
for c in BTC ETH; do
  curl -s "https://www.deribit.com/api/v2/public/get_instruments?currency=$c&kind=option&expired=false" > "deribit_inst_$c.json"
  curl -s "https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=$c&kind=option" > "deribit_book_$c.json"
  curl -s -X POST https://api.lyra.finance/public/get_instruments -H 'Content-Type: application/json' \
    -d "{\"currency\":\"$c\",\"instrument_type\":\"option\",\"expired\":false}" > "derive_inst_$c.json"
  curl -s "https://api.aevo.xyz/markets?asset=$c&instrument_type=OPTION" > "aevo_mk_$c.json"
done
echo ok
