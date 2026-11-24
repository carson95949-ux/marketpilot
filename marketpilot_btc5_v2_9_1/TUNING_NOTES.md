# MarketPilot BTC 5M V2.5 tuning notes

This build is intentionally more active than V2.4.2 while retaining hard floors.

## Why these changes

- **Quote-first microstructure:** recent Polymarket research finds quote updates carry much more price discovery than trades, so V2.5 uses two-sided order-book pressure and recent YES-midquote movement rather than inferred trade direction.
- **Correct fee curve:** Polymarket crypto takers currently pay `0.07 * contracts * p * (1-p)` and makers pay zero. V2.5 uses that fee estimate per entry instead of a flat 2-cent buffer.
- **Faster confirmation:** two consecutive qualifying scans are enough. A confirmed trade still remains locked until settlement.
- **Adaptive activity:** one skipped round starts gradual threshold relaxation, but a 5% net-edge hard floor and 55% probability floor remain.
- **Wider timing window:** the bot can qualify from about 4:30 remaining down to 0:35 remaining (with a small extra edge requirement at the extreme early/late edges), subject to all other filters.

## What V2.5 does not claim

No public evidence proves these exact thresholds are optimal. The correct next step is to collect hundreds of settled 5-minute rounds and optimize on chronological training data while keeping a later untouched test set.

## TWAP-aware target and late-round model

While the bot is running it stores lightweight BTC samples. At each new round it prefers, in order: (1) official Gamma `eventMetadata.priceToBeat` when available, (2) a local 60-second pre-open time-weighted Coinbase proxy, and (3) the exact round-start 1-minute candle open as fallback. In the final 60 seconds, it also estimates the partially completed settlement-minute TWAP and uses that projected average as the model reference. This remains a proxy for Chainlink, not the official oracle.
