# MarketPilot V2.9

- Replaced the generic paper-win chime with an optional cash-register-style “cha-ching” sound generated locally in the browser.
- Turning sound on now uses a neutral confirmation beep so it cannot be mistaken for a win.
- Added fast settlement-window polling: the browser checks about every 450 ms from the final 5 seconds through 20 seconds after close, while avoiding overlapping requests.
- Bot polling increased from 2 seconds to 1 second so newly settled records can reach the UI faster.
- Aggressive bankroll profile: 1.00% risk/trade, 5% daily stop guidance, 2% max-open guidance, 80% reserve.
- Fixed paper sizing so it no longer inherits the $1 live-order cap. Paper sizing now uses its own $25 cap and up to 30 contracts.
- Live execution remains independently capped by polymarket_execution.live_max_order_dollars.
