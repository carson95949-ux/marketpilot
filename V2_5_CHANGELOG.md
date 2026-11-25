# MarketPilot BTC 5M V2.5 — Active Balanced

## Main objective
Increase the number of qualified executions without forcing a trade every round.

## Strategy changes
- Baseline net-edge threshold: 7.0% after estimated Polymarket taker fee.
- Adaptive mode begins after one skipped round and can relax toward 5.5% net edge.
- Hard net-edge floor: 5.0%.
- Baseline side probability: 58%; adaptive floor 56%; hard floor 55%.
- Confirmation: 2 consecutive qualifying scans instead of 3.
- Entry window: 35–270 seconds remaining, with a small extra edge requirement at the extreme early/late edges.
- Momentum alignment: 2/5 baseline, 1/5 only after adaptive relaxation.
- Spread limit: 4 cents baseline.
- Uses the current Polymarket crypto taker-fee curve instead of a flat 2-cent buffer.
- Uses both UP and DOWN books to calculate binary order-book pressure.
- Uses recent YES midquote movement as an additional confirmation signal.
- Smaller time-of-day penalties; spread, edge, price separation, chart structure and book quality matter more.

## TWAP-aware changes
- Prefers official Gamma `eventMetadata.priceToBeat` if it is already available.
- Otherwise builds a local 60-second pre-open BTC proxy from the bot's own frequent price samples.
- Falls back to the exact round-start Coinbase 1-minute candle open if needed.
- During the final settlement minute, projects the partially known 60-second average rather than using the last BTC tick alone.

## Measurement
The website now shows Trade Frequency = rounds entered / rounds observed alongside win rate and P&L.

## Important
These settings are research defaults, not proof of profitability. Use paper mode to collect a large sample and optimize chronologically rather than fitting to a few recent wins.
