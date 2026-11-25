# MarketPilot BTC 5M V2.6 — Low-Vol 8/10 Activity Controller

## Goal
When BTC is in a calmer short-term regime, MarketPilot now targets **at least 8 traded rounds out of each rolling 10 low-volatility rounds**.

## How it works
- Low volatility is detected from the relationship between recent 5-minute and 15-minute 1-minute-return volatility, plus the size of the latest 1-minute move.
- MarketPilot keeps a rolling history of completed low-volatility rounds.
- Up to **2 skips per rolling 10 low-vol rounds** are allowed under the normal/selective rules.
- Once 2 skips are already present, the next low-vol rounds enter **LOW-VOL QUOTA** mode.
- LOW-VOL QUOTA uses a faster **1-scan confirmation** and relaxes thresholds toward a still-positive expected-value floor.
- A completed trade moves the rolling window back toward the 8/10 target.

## LOW-VOL QUOTA floors
- Minimum estimated net edge after modeled Polymarket taker fee: **3.5%**
- Minimum selected-side probability: **53%**
- Maximum spread: **5 cents**
- Minimum chart score: **0** (chart may be neutral, but not used as a forced directional signal)
- Minimum momentum alignment: **0/5**
- Minimum target separation: **0.05 sigma**
- Entry window: roughly **4:40 to 0:25 remaining**
- Confirmation: **1 qualifying scan** while quota mode is active

## Hard exceptions
The 8/10 target is not an unconditional forced-bet rule. MarketPilot can still skip when:
- an executable UP or DOWN quote is missing;
- the order book is broken or the spread exceeds the quota cap;
- neither side has positive modeled edge above the quota floor after fees;
- a daily loss or exposure halt is active;
- the market is not classified as low volatility.

This means the controller **targets** 8/10 in calm markets, but does not fabricate liquidity or accept negative expected value just to hit the quota.
