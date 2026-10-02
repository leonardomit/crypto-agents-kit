#!/usr/bin/env bash
# Polymarket Scout — lista mercados ativos via Gamma API (público, sem secret).
# Uso: polymarket-scout-markets.sh [limit]
set -euo pipefail
LIMIT="${1:-50}"
URL="https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=${LIMIT}"
curl -sS "$URL" | jq '[.[] | {
  question: .question,
  yes: (if (.outcomePrices|type)=="string" then (.outcomePrices|fromjson)[0] else .outcomePrices[0] end),
  volume24hr: .volume24hr,
  liquidity: .liquidity,
  slug: .slug,
  url: ("https://polymarket.com/event/" + (.slug // ""))
}] | sort_by(-(.volume24hr // 0)) | .[0:20]'
