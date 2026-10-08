---
name: polymarket-scout
description: Use when enriching the Polymarket Scout cron.
version: 1.0.0
---

# Polymarket Scout

Alert only. Zero trade, wallet, or secrets. Do not invent odds or edge.

## Each run

1. Read `scouts/polymarket/out/latest.md` and `markets.json`.
2. Treat that digest as biased: `scouts/polymarket/polymarket-scout-markets.sh` fetches 50 markets without `order=volume24hr`, then sorts. Also pull Gamma `markets?order=volume24hr&ascending=false` and the standing slugs (Brazil election, Fed October, Iran invade, 3rd place).
3. Compare to public news. Mark uncertain if unconfirmed. Highlight only `|edge| ≳ 8 pp` or strong risk (manipulation, thin liquidity, ambiguous resolution).
4. Update `latest.md` section Hermes enrich and `history/YYYY-MM-DD-HHMM.md`.
5. If nothing actionable, write `sem sinal acionavel` and stop.

## Sources that work in cron

- Gamma: `curl` + `jq`. Public, no key.
- Google News RSS via `curl` to scratch, then a `.py` file. Cron blocks `python -c` and heredocs. Do not append `python -c` to a curl: Tirith blocks the whole command.
- Sort RSS items by `pubDate` before calling one the newest. Google News feed order is not chronological.
- When checking whether news is newer than the last run, reuse that run's query string. A quoted variant can return zero items and look like silence.
- The same query can drop a previously seen newer item and return an older newest `pubDate`. That is feed variance, not silence and not a new fact. Compare `pubDate` to the last cited item.
- Cron Tirith also blocks bash functions and `for` loops. One straight `curl` per command; parse with `jq` or a `.py` file.
- Firecrawl search/extract often 403. GDELT often times out. CME FedWatch often 403, and a curl HTTP/2 error is the same: no number. Do not treat those failures as facts.
- A secondary page quoting CME FedWatch is not a live print. Read the date before calling the gap edge. A September figure is not today's probability.
- `volume24hr` can drop by tens of thousands between slug fetches a few minutes apart while bid, ask, last, and liquidity stay put. That is not a price crash and not a book blowout.
- X search without citations is not a fact. Cited URLs whose post bodies were not read are not facts either. Do not import the summary.

## Edge rules

- Poll share, valid-vote share, and runoff simulation are not P(win). A naive gap near 8 pp is still invalid. Do not escalate it.
- A headline that cites prediction markets is not an independent probability.
- `resolved` / `proposed` markets are not open edge.
- Live esports price swings are not edge without an external probability.
- A daily Bitcoin up/down market that names the Binance 1m candle closing at noon ET is not the candle Binance labels 12:00 (that one opens at 12:00 and closes at 12:01). If those two closes point opposite ways, do not turn the price gap into edge. `disputed` plus a wide book is ambiguous resolution, not a trade. Refetch the slug before writing: the book can blow out within minutes.
- Do not treat `oneDayPriceChange` as the delta versus the previous scout print. It can flip, or go null, between fetches while bid, ask, and last stay put. A missing field is not a crash in the price.
- A later day's rule text that says 12:01 ET does not rewrite an earlier market that still says 12:00 ET. Do not settle one dispute with the other day's wording.
- `markets?slug=` can return `[]` after a market closes. Check `events?slug=` before calling it gone. That events response is a JSON array; read `.[0]`, not the object root. An event embed can show a short `umaResolutionStatuses` list while `umaResolutionStatus` is `resolved`. Use `closed`, `acceptingOrders`, and the status field. Do not count characters of a JSON string as chain length.
- A Brazil presidential win market can show `endDate` on the first-round timestamp while the description still includes the runoff. Open + rule text wins; do not treat that `endDate` as a missed resolution.
- First-round vote share is not P(win the election). Do not turn a post-round price jump into edge.
- Scratch parsers: write a new `.py` filename. `write_file` refuses to overwrite a file this run has not fully read.
