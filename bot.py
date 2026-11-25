from __future__ import annotations

import json, os, time
from datetime import datetime, timezone
from pathlib import Path

from data_feed import coinbase_candles, features
from strategy import probability_up, selective_trade, adaptive_profile, chart_read, locked_decision, position_size, low_volatility_state, apply_low_vol_quota
from polymarket_client import PolymarketClient
from polymarket_trading import PolymarketTradingClient
from multi_db import (
    log_market_snapshot, register_market_round, get_open_market_trade,
    open_market_trade, settle_market_trade, open_trades, market_stats,
    daily_realized_pnl, open_exposure, observe_candidate, candidate_state,
    clear_candidate, has_market_trade, recent_quote_momentum, record_price_tick,
    tick_twap, settlement_twap_projection, update_round_activity, low_vol_activity_state, mark_round_traded,
)
from utils import polymarket_fee_estimate


ROOT = Path(__file__).resolve().parent
CFG_PATH = ROOT / "config.json"
CFG = json.loads(CFG_PATH.read_text())
CFG_MTIME = CFG_PATH.stat().st_mtime
KEY = "polymarket_5m"


def reload_config():
    global CFG, CFG_MTIME
    try:
        mt = CFG_PATH.stat().st_mtime
        if mt != CFG_MTIME:
            CFG = json.loads(CFG_PATH.read_text())
            CFG_MTIME = mt
            print("[CONFIG] reloaded")
    except Exception as e:
        print("[CONFIG ERROR]", e)


def coinbase_proxy_open(df, start_ts):
    """Return the Coinbase 1-minute OPEN for the exact Polymarket round start.

    Do not use the nearest candle: near a 5-minute rollover that can accidentally
    reuse the previous minute and leave the chart showing the prior round target.
    Returning None makes the bot wait for the correct candle instead of publishing
    a stale target.
    """
    if df is None or df.empty:
        return None
    x = df.copy()
    x["time"] = x["time"].astype(float).astype(int)
    start = int(float(start_ts))
    exact = x[x["time"] == start]
    if exact.empty:
        return None
    exact = exact.sort_values("time")
    return float(exact.iloc[0]["open"])


def risk_allows():
    rc = CFG.get("risk_controls", {})
    halt = ROOT / rc.get("halt_file", "BOT_HALT")
    if halt.exists():
        return False, "Emergency halt file exists"
    if daily_realized_pnl() <= -abs(float(rc.get("daily_loss_limit", 25))):
        return False, "Daily loss limit reached"
    if open_exposure() >= float(rc.get("max_open_exposure", 50)):
        return False, "Open exposure cap reached"
    return True, "OK"


def settle(poly):
    for tr in open_trades():
        if tr.get("market_key") != KEY:
            continue
        try:
            result = poly.resolution_result(tr["market_id"])
            if result:
                out = settle_market_trade(KEY, tr["market_id"], result)
                if out:
                    print(f"[SETTLED] {tr['market_id']} {result} pnl=${out['pnl']:.2f}")
        except Exception as e:
            print("[SETTLEMENT ERROR]", e)


def confirmation_gate(market_id, decision):
    dc = CFG.get("decision_confirmation", {})
    required = max(1, int(dc.get("required_scans", 3)))
    if decision.get("low_vol_quota"):
        required = max(1, int(CFG.get("low_vol_activity", {}).get("quota_required_scans", 1)))
    action = str(decision.get("action") or "PASS").upper()
    if action in ("YES", "NO"):
        count = observe_candidate(KEY, market_id, action, max_gap_seconds=float(dc.get("max_gap_seconds", 7)))
        decision["watch_side"] = action
        decision["confirmation_count"] = count
        decision["confirmation_required"] = required
        if count < required:
            return {
                **decision,
                "action": "PASS",
                "locked": False,
                "threshold_mode": f"CONFIRMING {count}/{required}",
                "reason": f"{'UP' if action=='YES' else 'DOWN'} qualifies, waiting for {required-count} more confirmation check(s)."
            }
        return decision

    state = candidate_state(KEY)
    side = str(state.get("candidate_side") or "").upper()
    count = int(state.get("candidate_count") or 0)
    if side in ("YES", "NO") and count:
        decision["watch_side"] = side
        decision["confirmation_count"] = count
        decision["confirmation_required"] = required
        decision["threshold_mode"] = f"SCANNING {count}/{required}"
    return decision


def maybe_open_paper(market_id, decision):
    if decision.get("action") not in ("YES", "NO"):
        return None
    if has_market_trade(KEY, market_id):
        return get_open_market_trade(KEY, market_id)
    ok, why = risk_allows()
    if not ok:
        print("[RISK HALT]", why)
        return None
    bankroll = market_stats(KEY, float(CFG.get("paper_starting_bankroll", 1000)))['bankroll']
    contracts = position_size(bankroll, decision["entry_price"], decision, CFG)
    if contracts <= 0:
        return None
    open_market_trade(
        KEY, "Polymarket", market_id, decision["action"], decision["entry_price"], contracts,
        decision["model_probability"], decision["net_edge"], polymarket_fee_estimate(decision["entry_price"], 1.0, float(CFG.get("polymarket_fee_rate", 0.07))),
        strategy_type="DIRECTIONAL"
    )
    clear_candidate(KEY)
    mark_round_traded(KEY, market_id)
    print(f"[PAPER] BUY {decision['action']} {contracts:.2f} @ {decision['entry_price']:.3f}")
    return get_open_market_trade(KEY, market_id)


def live_unlocked():
    pcfg = CFG.get("polymarket_execution", {})
    return bool(pcfg.get("live_trading_enabled")) and os.getenv("POLYMARKET_LIVE_CONFIRM", "") == "I_UNDERSTAND_POLYMARKET_LIVE_TRADING"


def maybe_live_buy(trader, live, decision):
    pcfg = CFG.get("polymarket_execution", {})
    if str(pcfg.get("mode", "paper")).lower() != "live":
        return
    if decision.get("action") not in ("YES", "NO"):
        return
    if has_market_trade(KEY, live["slug"]):
        return
    if float(live["seconds_left"]) < float(pcfg.get("minimum_seconds_left_to_submit", 45)):
        return
    if not live_unlocked():
        raise RuntimeError("Live mode is locked. See README.md before enabling it.")
    if not trader.credentials_present():
        raise RuntimeError("Polymarket live credentials are missing from .env")
    ok, why = risk_allows()
    if not ok:
        print("[LIVE RISK HALT]", why)
        return

    side = decision["action"]
    asset_id = live["up_token_id"] if side == "YES" else live["down_token_id"]
    entry = float(decision["entry_price"])
    edge = max(0.0, float(decision.get("net_edge") or 0.0))
    slip = min(float(pcfg.get("max_slippage_cents", 2.0))/100.0, max(0.0, edge-0.02))
    max_price = min(0.99, entry + slip)
    bankroll = max(1.0, float(CFG.get("paper_starting_bankroll", 1000)))
    dollars = min(float(pcfg.get("live_max_order_dollars", 1.0)), bankroll * float(CFG.get("risk_per_trade_pct", .0035)))
    dollars = max(0.01, round(dollars, 2))
    resp = trader.buy_market(asset_id=asset_id, dollars=dollars, max_price=max_price, order_type=pcfg.get("order_type", "FAK"))
    print("[LIVE ORDER]", resp)
    if trader.response_matched(resp):
        approx_shares = max(0.01, dollars / max(entry, 0.01))
        open_market_trade(KEY, "Polymarket", live["slug"], side, entry, approx_shares,
                          float(decision.get("model_probability") or .5), float(decision.get("net_edge") or 0),
                          polymarket_fee_estimate(entry, 1.0, float(CFG.get("polymarket_fee_rate", 0.07))), strategy_type="LIVE_DIRECTIONAL")
        clear_candidate(KEY)
        mark_round_traded(KEY, live["slug"])


def run_once(poly, trader):
    settle(poly)
    df = coinbase_candles(minutes=90)
    feat = features(df)
    low_vol = low_volatility_state(feat, CFG)
    live = poly.current_btc_updown(5)
    market_id = live["slug"]
    skipped = register_market_round(KEY, market_id)
    update_round_activity(KEY, market_id, low_vol=low_vol["is_low_vol"], traded=has_market_trade(KEY, market_id))
    activity = low_vol_activity_state(KEY, int(CFG.get("low_vol_activity", {}).get("window_rounds", 10)))
    reference = float(feat["spot"])
    record_price_tick(time.time(), reference)

    official_target = poly.official_price_to_beat(live.get("market") or {})
    local_twap_target = tick_twap(live["start_ts"], window_seconds=60)
    candle_target = coinbase_proxy_open(df, live["start_ts"])
    if official_target is not None:
        target = official_target
        target_quality = "Official Polymarket/Chainlink priceToBeat from Gamma metadata"
    elif local_twap_target is not None:
        target = local_twap_target
        target_quality = "Local Coinbase ~2s 60-second TWAP proxy before round open"
    else:
        target = candle_target
        target_quality = "Coinbase exact round-start 1m open fallback"
    if target is None:
        print(f"BTC 5m | {live['seconds_left']:5.0f}s | waiting for round target | {market_id}")
        return

    # During the final settlement minute, model the partly-known 60s average
    # instead of pretending the latest BTC tick alone determines the outcome.
    projected_twap = None
    if float(live["seconds_left"]) <= 60:
        projected_twap = settlement_twap_projection(
            live["end_ts"], time.time(), reference, window_seconds=60
        )
    model_reference = float(projected_twap) if projected_twap is not None else reference

    quotes = {k: live.get(k) for k in ["yes_bid","yes_ask","no_bid","no_ask","spread","book_imbalance"]}
    quotes["quote_momentum"] = recent_quote_momentum(
        KEY, market_id, quotes.get("yes_bid"), quotes.get("yes_ask"), lookback=5
    )
    cr = chart_read(feat)
    existing = get_open_market_trade(KEY, market_id)
    if existing:
        decision = locked_decision(existing, cr)
        p_yes = float(existing.get("model_probability") or .5) if existing.get("side") == "YES" else 1-float(existing.get("model_probability") or .5)
    else:
        profile = adaptive_profile(CFG["market_profiles"][KEY], CFG, skipped)
        profile = apply_low_vol_quota(profile, CFG, activity, low_vol)
        p_yes = probability_up(feat, model_reference, target, live["seconds_left"], horizon_minutes=5)
        decision = selective_trade(
            p_yes, quotes, CFG, profile, feat, model_reference, target, live["seconds_left"],
            fee_model="polymarket", fixed_cost_buffer=float(CFG.get("polymarket_cost_buffer", .02))
        )
        decision["adaptive"] = bool(profile.get("adaptive"))
        decision["low_vol_quota"] = bool(profile.get("low_vol_quota", False))
        decision["threshold_mode"] = profile.get("threshold_mode", "SELECTIVE")
        decision["strategy_type"] = "DIRECTIONAL"
        decision = confirmation_gate(market_id, decision)

        if str(CFG.get("polymarket_execution", {}).get("mode", "paper")).lower() == "paper":
            tr = maybe_open_paper(market_id, decision)
            if tr:
                decision = locked_decision(tr, cr)
        else:
            maybe_live_buy(trader, live, decision)
            tr = get_open_market_trade(KEY, market_id)
            if tr:
                decision = locked_decision(tr, cr)

    now = datetime.now(timezone.utc).isoformat()
    log_market_snapshot(
        ts=now, market_key=KEY, platform="Polymarket", timeframe="5m", market_id=market_id,
        seconds_left=live["seconds_left"], target=target,
        target_quality=target_quality + ("; final-minute TWAP projection active" if projected_twap is not None else ""),
        reference=reference, reference_source="Coinbase BTC-USD",
        yes_bid=quotes.get("yes_bid"), yes_ask=quotes.get("yes_ask"),
        no_bid=quotes.get("no_bid"), no_ask=quotes.get("no_ask"),
        p_yes=p_yes, action=decision.get("action"), net_edge=decision.get("net_edge"),
        reason=decision.get("reason"), chart_read=decision.get("chart_read"), chart_score=decision.get("chart_score"),
        locked=1 if decision.get("locked") else 0, adaptive=1 if decision.get("adaptive") else 0,
        skipped_rounds=skipped, threshold_mode=decision.get("threshold_mode"), strategy_type="DIRECTIONAL",
        pair_cost=None, maker_pair_cost=None, maker_pair_edge=None, book_imbalance=quotes.get("book_imbalance"),
        watch_side=decision.get("watch_side"), confirmation_count=decision.get("confirmation_count"),
        confirmation_required=decision.get("confirmation_required")
    )
    label = "UP" if decision.get("action") == "YES" else "DOWN" if decision.get("action") == "NO" else decision.get("threshold_mode", "WATCH")
    quota = f" | low-vol {activity['traded']}/{activity['rounds']} traded" if low_vol.get("is_low_vol") else ""
    print(f"BTC 5m | {live['seconds_left']:5.0f}s | BTC={reference:.2f} target={target:.2f} | P(up)={p_yes:.1%} | {label}{quota}")


def main():
    poly = PolymarketClient()
    trader = PolymarketTradingClient()
    print("MarketPilot — Polymarket BTC 5-Minute Only")
    print("Primary flow: WATCH -> CONFIRMING -> BUY -> LOCKED -> SETTLED")
    print("Execution mode:", CFG.get("polymarket_execution", {}).get("mode", "paper"))
    print("Ctrl+C to stop.\n")
    while True:
        try:
            reload_config()
            run_once(poly, trader)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print("[ERROR]", e)
        time.sleep(max(1, int(CFG.get("poll_seconds", 2))))


if __name__ == "__main__":
    main()
