# MarketPilot BTC 5M — V2.8

- 30-minute one-time free trial per MarketPilot account
- $4.99 one-time unlock
- Email/password accounts
- Stripe test checkout + production webhook support
- One My Account page for access and Polymarket connection
- Polymarket Session Key flow no longer needs Windows eth-account/eth-abi packages
- Render publishing files included

Run locally: `install_windows.bat`, then `START_MARKETPILOT.bat`.

See `PUBLISH.md` before putting it online. Stripe currently restricts/prohibits gambling and some related businesses, so test mode can be used for development but live Stripe should only be enabled after explicit approval.


## V2.4.1 round-target fix

The BTC 5-minute Price To Beat line is now round-aware. MarketPilot only accepts the Coinbase one-minute opening candle that exactly matches the active Polymarket 5-minute window. At rollover, the browser clears the prior target immediately and waits for the new round target, rather than reusing the nearest/previous candle.

The displayed target remains a Coinbase round-open proxy. Polymarket itself resolves the market using its specified Chainlink BTC/USD TWAP source.

## V2.4.2 bankroll defaults

The default bankroll plan is slightly more aggressive than V2.4.1:
- 0.60% bankroll risk per confirmed trade
- 3% daily loss stop
- up to 1% suggested open premium in the planner
- 90% bankroll reserve target
- bot max contracts increased from 10 to 15

Live Polymarket order caps remain conservative by default until you intentionally change them.


## V2.5 active-balanced tuning

V2.5 is tuned to execute more often without forcing a trade every 5-minute round.

Changes include:
- 2-scan confirmation instead of 3.
- Wider entry window: roughly 35 to 270 seconds remaining, with a small extra edge requirement at the extreme early/late edges.
- Baseline net-edge requirement reduced to 7%, with an adaptive floor of 5.5%.
- Adaptive mode starts after one skipped round.
- Momentum alignment reduced from 3/5 to 2/5 (and 1/5 only in adaptive mode).
- Chart and target-separation thresholds relax modestly after skipped rounds.
- Uses Polymarket's crypto taker fee curve (`0.07 * p * (1-p)`) rather than a flat 2-cent cost assumption.
- Uses both UP and DOWN order books for pressure, plus recent YES-quote momentum as confirmation.
- Time-of-day penalties are smaller because BTC trades continuously; liquidity/spread/edge remain the main gates.

The hard floor still prevents a trade solely because prior rounds were skipped. This is a research configuration, not a profitability guarantee.


## V2.6 low-volatility activity controller

When BTC is in a calmer short-term regime, MarketPilot now tracks the last 10 completed low-volatility rounds and targets at least **8 trades out of 10**. After the rolling window has already used its two allowed skips, new calm rounds enter **LOW-VOL QUOTA** mode with a faster one-scan confirmation and relaxed—but still positive-EV—thresholds. Missing executable quotes, negative modeled edge, or risk halts can still cause a skip. See `V2_6_CHANGELOG.md` for the exact floors.


## V2.7 engagement features
- Optional target-cross sound cues: distinct above/below tones, rate-limited to avoid rapid repeats.
- Win chime still fires only on a newly settled profitable paper trade.
- Stronger Connect Polymarket CTA at the bottom of the tool.
- Help & AI drawer with quick explanations and optional OpenAI Responses API integration.
- My Account community leaderboard: always visible; opted-in members can rank after 1 settled paper trade, using normalized paper ROI rather than bankroll size or wager volume.

### Ask AI setup (optional)
Built-in help works without an API key. To enable model-backed answers, add `OPENAI_API_KEY` to `.env`. `OPENAI_MODEL` defaults to `gpt-6-luna` and can be overridden.


## V2.8 cleaner tabs + demo leaderboard
- Main tool now uses three tabs: Trade, Performance, Rules & Bankroll.
- My Account now uses Overview, Polymarket, Rankings.
- Demo leaderboard preview includes clearly labeled sample pilots and sample ROI/win-rate data.
- Demo rows are not stored as users and automatically disappear after five real eligible ranked members.
- Set `MARKETPILOT_DEMO_LEADERBOARD=false` to disable the demo preview immediately.

See `V2_8_CHANGELOG.md` for details.


## V2.9 update
Win settlements now trigger an optional browser-generated cash-register sound, recent trading records poll rapidly around settlement, and the bankroll planner uses the aggressive 1% risk profile. Paper sizing has a separate cap from live real-money execution.
