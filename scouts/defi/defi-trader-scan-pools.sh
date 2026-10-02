#!/usr/bin/env bash
# Crypto/DeFi Trader — top yields via DefiLlama (público, sem secret).
# Uso: defi-trader-scan-pools.sh [limit] [min_tvl_usd]
# Chains default: Ethereum Base Arbitrum Optimism
set -euo pipefail
LIMIT="${1:-15}"
MIN_TVL="${2:-1000000}"
CHAINS_REGEX='^(Ethereum|Base|Arbitrum|Optimism)$'
curl -sS 'https://yields.llama.fi/pools' | jq --argjson limit "$LIMIT" --argjson minTvl "$MIN_TVL" --arg re "$CHAINS_REGEX" '
  [.data[]
    | select((.chain // "") | test($re))
    | select((.tvlUsd // 0) >= $minTvl)
    | select((.apy // 0) > 0)
    | {
        project: .project,
        chain: .chain,
        symbol: .symbol,
        apy: .apy,
        apyBase: .apyBase,
        apyReward: .apyReward,
        tvlUsd: .tvlUsd,
        pool: .pool,
        url: ("https://defillama.com/yields/pool/" + (.pool // ""))
      }
  ]
  | sort_by(-.apy)
  | .[0:$limit]
'
