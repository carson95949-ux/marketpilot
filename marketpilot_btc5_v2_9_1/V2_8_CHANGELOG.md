# MarketPilot V2.8

## Cleaner navigation
- Main tool reduced to three tabs: Trade, Performance, Rules & Bankroll.
- Trade tab contains only the live decision, core quotes, entry zone, chart, and Polymarket CTA.
- Performance tab contains paper P&L, win rate, trade frequency, and recent trades.
- Rules tab contains the four core rules and bankroll planner.
- My Account reduced to Overview, Polymarket, and Rankings tabs.
- Account hash links such as `/account#polymarket` now open the correct tab directly.

## Demo leaderboard
- Added six clearly labeled DEMO pilots with sample ROI, win rate, and trade counts.
- Demo data is visual preview data only and is not inserted into the user database.
- Demo rows automatically disappear once at least five real opted-in users are eligible for ranking.
- Set `MARKETPILOT_DEMO_LEADERBOARD=false` to turn the demo preview off immediately.

The demo leaderboard must not be represented as real customer performance.
