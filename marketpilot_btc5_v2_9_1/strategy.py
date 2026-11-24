from __future__ import annotations
import math
from copy import deepcopy
from datetime import datetime, timezone
from utils import sigmoid, clamp, kalshi_fee_estimate, polymarket_fee_estimate


def probability_up(feat, reference_price, target_price, seconds_left, horizon_minutes=15):
    target = max(float(target_price), 1e-9)
    ref = float(reference_price)
    distance = ref / target - 1.0
    vol = max(float(feat["vol15"]), 0.00012)
    horizon_seconds = max(float(horizon_minutes) * 60.0, 60.0)
    time_scale = max(math.sqrt(max(seconds_left, 20.0) / horizon_seconds), 0.16)

    distance_z = distance / (vol * time_scale)
    momentum_z = (
        0.34 * feat["mom1"] + 0.30 * feat["mom3"] +
        0.18 * feat["mom5"] + 0.10 * feat["trend"] +
        0.08 * feat.get("ema_slope", 0.0)
    ) / vol
    volume_impulse = clamp(feat["volume_ratio"] - 1.0, -1.5, 1.5)
    rsi_bias = clamp((float(feat.get("rsi14", 50.0)) - 50.0) / 25.0, -1.0, 1.0)

    momentum_weight = 0.40 if horizon_minutes <= 5 else 0.47
    score = 1.06 * distance_z + momentum_weight * momentum_z + 0.06 * volume_impulse + 0.08 * rsi_bias
    return clamp(sigmoid(score), 0.01, 0.99)


def chart_read(feat):
    """Translate the underlying 1m BTC chart into a directional read, not an image classification."""
    vol = max(float(feat.get("vol15", 0.0)), 0.00012)
    mom = (
        0.30 * feat.get("mom1", 0.0) +
        0.28 * feat.get("mom3", 0.0) +
        0.18 * feat.get("mom5", 0.0) +
        0.12 * feat.get("trend", 0.0) +
        0.12 * feat.get("ema_slope", 0.0)
    ) / vol
    rsi = float(feat.get("rsi14", 50.0))
    rsi_component = clamp((rsi - 50.0) / 20.0, -1.5, 1.5)
    ema_component = clamp(float(feat.get("ema_fast_slow", 0.0)) / vol, -2.0, 2.0)
    volume = clamp(float(feat.get("volume_ratio", 1.0)) - 1.0, -1.0, 1.0)
    score = 34.0 * clamp(mom, -2.0, 2.0) + 17.0 * rsi_component + 18.0 * ema_component + 6.0 * volume
    score = clamp(score, -100.0, 100.0)
    if score >= 35:
        label = "STRONG BULLISH"
    elif score >= 14:
        label = "BULLISH"
    elif score <= -35:
        label = "STRONG BEARISH"
    elif score <= -14:
        label = "BEARISH"
    else:
        label = "NEUTRAL"
    return {
        "label": label,
        "score": float(score),
        "rsi": rsi,
        "volume_ratio": float(feat.get("volume_ratio", 1.0)),
        "momentum": float(mom),
    }


def session_context(cfg, now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    hour = now_utc.hour + now_utc.minute / 60.0
    weekday = now_utc.weekday() < 5
    sf = cfg.get("session_filter", {})
    strong_start = float(sf.get("strong_weekday_utc_start", 14))
    strong_end = float(sf.get("strong_weekday_utc_end", 21))
    normal_start = float(sf.get("normal_weekday_utc_start", 12))
    normal_end = float(sf.get("normal_weekday_utc_end", 23))

    if not weekday:
        return {"label": "WEEKEND", "quality": "weak", "edge_penalty": float(sf.get("weekend_edge_penalty", 0.025))}
    if strong_start <= hour < strong_end:
        return {"label": "US LIQUIDITY WINDOW", "quality": "strong", "edge_penalty": 0.0}
    if normal_start <= hour < normal_end:
        return {"label": "NORMAL WEEKDAY", "quality": "normal", "edge_penalty": float(sf.get("normal_edge_penalty", 0.01))}
    return {"label": "OFF-HOURS", "quality": "weak", "edge_penalty": float(sf.get("weak_edge_penalty", 0.02))}


def adaptive_profile(base_profile, cfg, skipped_rounds):
    p = deepcopy(base_profile)
    ac = cfg.get("adaptive_trade_frequency", {})
    limit = int(ac.get("skip_round_limit", 2))
    if not ac.get("enabled", True) or int(skipped_rounds) < limit:
        p["adaptive"] = False
        p["threshold_mode"] = "SELECTIVE"
        return p

    rounds = min(int(skipped_rounds) - limit + 1, int(ac.get("max_relax_rounds", 3)))
    edge_step = float(ac.get("edge_relax_step", 0.008))
    prob_step = float(ac.get("probability_relax_step", 0.008))
    p["min_net_edge"] = max(float(p.get("adaptive_min_net_edge", p["min_net_edge"])), float(p["min_net_edge"]) - rounds * edge_step)
    p["min_side_probability"] = max(float(p.get("adaptive_min_side_probability", p["min_side_probability"])), float(p["min_side_probability"]) - rounds * prob_step)
    if rounds >= 2:
        p["min_alignment"] = max(int(p.get("adaptive_min_alignment", p.get("min_alignment", 0))), int(p.get("min_alignment", 0)) - 1)
    chart_step = float(ac.get("chart_relax_step", 0.0))
    dist_step = float(ac.get("distance_relax_step", 0.0))
    p["min_chart_score"] = max(float(p.get("adaptive_min_chart_score", p.get("min_chart_score", 0.0))), float(p.get("min_chart_score", 0.0)) - rounds * chart_step)
    p["min_distance_z"] = max(float(p.get("adaptive_min_distance_z", p.get("min_distance_z", 0.0))), float(p.get("min_distance_z", 0.0)) - rounds * dist_step)
    p["adaptive"] = True
    p["threshold_mode"] = "ADAPTIVE"
    return p



def low_volatility_state(feat, cfg):
    """Classify a calm BTC regime from relative short/medium 1m volatility.

    This intentionally uses ratios rather than a fixed BTC-dollar threshold so the
    classifier adapts as the underlying price level changes.
    """
    lc = cfg.get("low_vol_activity", {})
    vol15 = max(float(feat.get("vol15", 0.0)), 1e-9)
    vol5 = max(float(feat.get("vol5", 0.0)), 0.0)
    mom1 = abs(float(feat.get("mom1", 0.0)))
    vr = vol5 / vol15
    mr = mom1 / vol15
    is_low = bool(lc.get("enabled", True)) and vr <= float(lc.get("vol5_to_vol15_max", 1.05)) and mr <= float(lc.get("mom1_to_vol15_max", 1.35))
    return {"is_low_vol": is_low, "vol_ratio": vr, "mom1_ratio": mr}


def apply_low_vol_quota(profile, cfg, activity_state, low_vol_state):
    """Relax a profile only when the rolling low-vol trade quota is behind.

    The quota can make the bot more active, but it never bypasses the final net-edge
    check inside selective_trade and it cannot manufacture a missing executable quote.
    """
    p = deepcopy(profile)
    lc = cfg.get("low_vol_activity", {})
    if not lc.get("enabled", True) or not low_vol_state.get("is_low_vol", False):
        p["low_vol_quota"] = False
        return p

    skips = int(activity_state.get("skips", 0))
    max_skips = int(lc.get("max_skips", 2))
    if skips < max_skips:
        p["low_vol_quota"] = False
        p["low_vol_quota_skips"] = skips
        p["low_vol_quota_window"] = int(activity_state.get("rounds", 0))
        return p

    # At/over the allowed skip count, move directly to an active profile.
    p["min_net_edge"] = max(float(cfg.get("activity_profile", {}).get("hard_floor_net_edge", 0.0)), float(lc.get("quota_min_net_edge", 0.035)))
    p["min_side_probability"] = max(float(cfg.get("activity_profile", {}).get("hard_floor_side_probability", 0.0)), float(lc.get("quota_min_side_probability", 0.53)))
    p["max_spread"] = max(float(p.get("max_spread", 0.04)), float(lc.get("quota_max_spread", 0.05)))
    p["min_alignment"] = int(lc.get("quota_min_alignment", 0))
    p["min_chart_score"] = float(lc.get("quota_min_chart_score", 0.0))
    p["min_distance_z"] = float(lc.get("quota_min_distance_z", 0.05))
    p["min_volume_ratio"] = float(lc.get("quota_min_volume_ratio", 0.25))
    p["min_seconds_left"] = min(float(p.get("min_seconds_left", 35)), float(lc.get("quota_min_seconds_left", 25)))
    p["max_seconds_left"] = max(float(p.get("max_seconds_left", 270)), float(lc.get("quota_max_seconds_left", 280)))
    p["adaptive"] = True
    p["low_vol_quota"] = True
    p["low_vol_quota_skips"] = skips
    p["low_vol_quota_window"] = int(activity_state.get("rounds", 0))
    p["threshold_mode"] = "LOW-VOL QUOTA"
    return p

def _alignment(feat, side):
    desired = 1 if side == "YES" else -1
    vals = [feat.get("mom1", 0), feat.get("mom3", 0), feat.get("mom5", 0), feat.get("trend", 0), feat.get("ema_slope", 0)]
    return sum(1 for v in vals if (v > 0 and desired > 0) or (v < 0 and desired < 0))


def _distance_z(feat, reference_price, target_price, seconds_left, horizon_minutes):
    target = max(float(target_price), 1e-9)
    distance = abs(float(reference_price) / target - 1.0)
    vol = max(float(feat.get("vol15", 0)), 0.00012)
    horizon_seconds = max(float(horizon_minutes) * 60.0, 60.0)
    time_scale = max(math.sqrt(max(float(seconds_left), 20.0) / horizon_seconds), 0.16)
    return distance / (vol * time_scale)


def selective_trade(p_yes, quotes, cfg, profile, feat, reference_price, target_price,
                    seconds_left, fee_model="kalshi", fixed_cost_buffer=0.0, now_utc=None):
    ya = quotes.get("yes_ask")
    na = quotes.get("no_ask")
    spread = quotes.get("spread")
    book_imbalance = quotes.get("book_imbalance")
    try:
        book_imbalance = None if book_imbalance is None else float(book_imbalance)
    except Exception:
        book_imbalance = None
    quote_momentum = quotes.get("quote_momentum")
    try:
        quote_momentum = None if quote_momentum is None else float(quote_momentum)
    except Exception:
        quote_momentum = None
    micro = cfg.get("microstructure", {})
    cr = chart_read(feat)
    if ya is None or na is None:
        return {"action": "PASS", "reason": "Missing executable quote.", "chart_read": cr["label"], "chart_score": cr["score"]}
    if spread is not None and float(spread) > float(profile["max_spread"]):
        return {"action": "PASS", "reason": f"Spread too wide ({float(spread)*100:.1f}¢).", "chart_read": cr["label"], "chart_score": cr["score"]}

    secs = float(seconds_left)
    if not (float(profile["min_seconds_left"]) <= secs <= float(profile["max_seconds_left"])):
        return {"action": "PASS", "reason": f"Outside preferred entry window ({secs:.0f}s left).", "chart_read": cr["label"], "chart_score": cr["score"]}

    sess = session_context(cfg, now_utc)
    required_edge = float(profile["min_net_edge"]) + float(sess["edge_penalty"])
    # Widen the usable 5m window, but charge a small extra edge requirement at
    # the very beginning and very end where target discovery/execution are less forgiving.
    if secs > float(profile.get("early_window_seconds", 1e9)):
        required_edge += float(profile.get("early_window_edge_penalty", 0.0))
    if secs < float(profile.get("late_window_seconds", -1)):
        required_edge += float(profile.get("late_window_edge_penalty", 0.0))
    horizon = int(profile.get("horizon_minutes", 15))
    dz = _distance_z(feat, reference_price, target_price, secs, horizon)
    shock_ratio = float(feat.get("vol5", 0)) / max(float(feat.get("vol15", 0)), 1e-9)
    volume_ratio = float(feat.get("volume_ratio", 1.0))

    if volume_ratio < float(profile.get("min_volume_ratio", 0.0)):
        return {"action": "PASS", "reason": f"Underlying volume is too quiet ({volume_ratio:.2f}× baseline).", "chart_read": cr["label"], "chart_score": cr["score"]}
    if dz < float(profile.get("min_distance_z", 0.0)):
        return {"action": "PASS", "reason": "BTC is too close to the target for a clean setup.", "chart_read": cr["label"], "chart_score": cr["score"]}
    if shock_ratio > float(profile.get("max_shock_ratio", 99)) and dz < 1.0:
        return {"action": "PASS", "reason": "Recent volatility shock is too high for the current target distance.", "chart_read": cr["label"], "chart_score": cr["score"]}

    candidates = []
    min_chart = float(profile.get("min_chart_score", 10.0))
    maker_pref_spread = float(micro.get("maker_preference_spread", 0.018))
    for side, p, ask in [("YES", p_yes, float(ya)), ("NO", 1.0-p_yes, float(na))]:
        if fee_model == "kalshi":
            cost = kalshi_fee_estimate(ask, 1.0)
        elif fee_model == "polymarket":
            cost = polymarket_fee_estimate(ask, 1.0, float(cfg.get("polymarket_fee_rate", 0.07)))
        else:
            cost = max(0.0, float(fixed_cost_buffer))
        gross_edge = float(p) - ask
        net_edge = gross_edge - cost
        align = _alignment(feat, side)
        chart_ok = cr["score"] >= min_chart if side == "YES" else cr["score"] <= -min_chart
        book_support = None if book_imbalance is None else (book_imbalance if side == "YES" else -book_imbalance)
        side_required_edge = required_edge
        if book_support is not None and micro.get("enabled", True):
            soft = float(micro.get("soft_support_threshold", 0.10))
            if book_support >= soft:
                side_required_edge = max(0.0, side_required_edge - float(micro.get("book_support_bonus", 0.008)))
            elif book_support <= -soft:
                side_required_edge += float(micro.get("book_opposition_penalty", 0.012))

        quote_support = None if quote_momentum is None else (quote_momentum if side == "YES" else -quote_momentum)
        if quote_support is not None and micro.get("enabled", True):
            qthr = float(micro.get("quote_momentum_support_threshold", 0.01))
            if quote_support >= qthr:
                side_required_edge = max(0.0, side_required_edge - float(micro.get("quote_momentum_bonus", 0.0)))
            elif quote_support <= -qthr:
                side_required_edge += float(micro.get("quote_momentum_penalty", 0.0))

        # Never relax below the configured hard floor, even after adaptive/book/quote bonuses.
        side_required_edge = max(float(cfg.get("activity_profile", {}).get("hard_floor_net_edge", 0.0)), side_required_edge)
        book_ok = True if book_support is None else book_support > float(micro.get("hard_opposition_threshold", -0.42))
        allowed = (
            float(p) >= max(float(cfg.get("activity_profile", {}).get("hard_floor_side_probability", 0.0)), float(profile["min_side_probability"])) and
            max(float(profile["min_entry_price"]), float(micro.get("avoid_taker_longshots_below", 0.0))) <= ask <= float(profile["max_entry_price"]) and
            net_edge >= side_required_edge and
            align >= int(profile.get("min_alignment", 0)) and
            chart_ok and book_ok
        )
        if allowed:
            candidates.append({
                "action": side,
                "model_probability": float(p),
                "entry_price": ask,
                "gross_edge": gross_edge,
                "fee_estimate_per_contract": cost,
                "net_edge": net_edge,
                "required_edge": side_required_edge,
                "alignment": align,
                "book_imbalance": book_imbalance,
                "book_support": book_support,
                "quote_momentum": quote_momentum,
                "quote_support": quote_support,
                "execution_style": "MAKER_PREFERRED" if spread is not None and float(spread) >= maker_pref_spread else "TAKER_OK",
                "distance_z": dz,
                "session": sess["label"],
                "session_quality": sess["quality"],
                "chart_read": cr["label"],
                "chart_score": cr["score"],
                "adaptive": bool(profile.get("adaptive", False)),
                "threshold_mode": profile.get("threshold_mode", "SELECTIVE"),
                "reason": f"{profile.get('threshold_mode','SELECTIVE')} · {sess['label']} · chart {cr['label'].lower()} ({cr['score']:+.0f}) · {align}/5 momentum aligned · separation {dz:.2f}σ" + (f" · book {book_support:+.2f}" if book_support is not None else "") + (f" · quote move {quote_support*100:+.1f}¢." if quote_support is not None else ".")
            })

    if not candidates:
        mode = profile.get("threshold_mode", "SELECTIVE")
        return {
            "action": "PASS",
            "reason": f"{mode}: no side clears {required_edge*100:.1f}% net edge plus chart/momentum confirmation.",
            "model_probability": max(p_yes, 1-p_yes),
            "yes_probability": p_yes,
            "required_edge": required_edge,
            "distance_z": dz,
            "session": sess["label"],
            "session_quality": sess["quality"],
            "chart_read": cr["label"],
            "chart_score": cr["score"],
            "adaptive": bool(profile.get("adaptive", False)),
            "threshold_mode": mode,
            "book_imbalance": book_imbalance,
            "quote_momentum": quote_momentum,
            "execution_style": "MAKER_PREFERRED" if spread is not None and float(spread) >= maker_pref_spread else "TAKER_OK",
        }
    return max(candidates, key=lambda x: (x["net_edge"], x["model_probability"], abs(x["chart_score"])))


def pair_arbitrage_decision(quotes, cfg):
    """Executable two-sided arb: buy UP + DOWN only when net payout margin is positive."""
    pcfg = cfg.get("polymarket_hybrid", {})
    if not pcfg.get("enabled", True) or not pcfg.get("pair_arb_enabled", True):
        return None
    ya, na = quotes.get("yes_ask"), quotes.get("no_ask")
    if ya is None or na is None:
        return None
    ya, na = float(ya), float(na)
    # Approximate current crypto taker fee on each leg using the public p*(1-p) schedule.
    fee_yes = kalshi_fee_estimate(ya, 1.0)
    fee_no = kalshi_fee_estimate(na, 1.0)
    total = ya + na + fee_yes + fee_no
    profit = 1.0 - total
    if total <= float(pcfg.get("pair_max_total_cost", 0.985)) and profit >= float(pcfg.get("pair_min_profit_per_share", 0.01)):
        return {
            "action":"PAIR",
            "model_probability":0.5,
            "entry_price":ya,
            "hedge_price":na,
            "net_edge":profit,
            "gross_edge":1.0-(ya+na),
            "fee_estimate_per_contract":fee_yes+fee_no,
            "locked":True,
            "threshold_mode":"PAIR ARB",
            "strategy_type":"PAIR_ARB",
            "reason":f"PAIR ARB · Buy UP {ya*100:.1f}¢ + DOWN {na*100:.1f}¢. Estimated all-in cost {total*100:.1f}¢, locking about {profit*100:.1f}¢/share if both fills execute."
        }
    return None


def maker_pair_snapshot(quotes, cfg):
    """Non-executing maker opportunity estimate. Fill probability is NOT assumed."""
    pcfg = cfg.get("polymarket_hybrid", {})
    yb, nb = quotes.get("yes_bid"), quotes.get("no_bid")
    ya, na = quotes.get("yes_ask"), quotes.get("no_ask")
    if yb is None or nb is None:
        return {"maker_pair_cost":None,"maker_pair_edge":None,"maker_pair_ready":False}
    tick=float(pcfg.get("maker_tick_improve",0.01))
    y=float(yb); n=float(nb)
    if ya is not None: y=min(y+tick,max(y,float(ya)-tick))
    if na is not None: n=min(n+tick,max(n,float(na)-tick))
    total=y+n
    return {
        "maker_up_quote":y,"maker_down_quote":n,
        "maker_pair_cost":total,"maker_pair_edge":1.0-total,
        "maker_pair_ready":bool(total <= float(pcfg.get("maker_target_total_cost",0.94)))
    }


def locked_decision(trade, chart_info=None):
    side = str(trade["side"]).upper()
    if side == "PAIR" or int(trade.get("hedged") or 0):
        up = float(trade.get("entry_price") or 0.0) if side == "PAIR" or str(trade.get("side")).upper()=="YES" else float(trade.get("hedge_price") or 0.0)
        down = float(trade.get("hedge_price") or 0.0) if side == "PAIR" or str(trade.get("side")).upper()=="YES" else float(trade.get("entry_price") or 0.0)
        total = up + down
        return {
            "action":"PAIR",
            "model_probability":0.5,
            "entry_price":float(trade.get("entry_price") or 0.0),
            "hedge_price":float(trade.get("hedge_price") or 0.0),
            "net_edge":max(0.0,1.0-total-float(trade.get("cost_per_contract") or 0)-float(trade.get("hedge_cost_per_contract") or 0)),
            "chart_read":(chart_info or {}).get("label","LOCKED"),
            "chart_score":(chart_info or {}).get("score",0.0),
            "locked":True,"adaptive":False,"threshold_mode":"PAIR LOCK",
            "strategy_type":trade.get("strategy_type") or ("HEDGE_LOCK" if int(trade.get("hedged") or 0) else "PAIR_ARB"),
            "reason":f"PAIR LOCKED · Combined UP+DOWN cost {total*100:.1f}¢ before recorded costs. Outcome direction no longer changes the paired payout."
        }
    return {
        "action": side,
        "model_probability": float(trade.get("model_probability") or 0.5),
        "entry_price": float(trade.get("entry_price") or 0.0),
        "net_edge": float(trade.get("net_edge") or 0.0),
        "chart_read": (chart_info or {}).get("label", "LOCKED"),
        "chart_score": (chart_info or {}).get("score", 0.0),
        "locked": True,
        "adaptive": False,
        "threshold_mode": "LOCKED",
        "reason": f"CONFIRMED / LOCKED · BUY {'UP' if side == 'YES' else 'DOWN'} at {float(trade.get('entry_price') or 0)*100:.0f}¢. Signal stays locked until settlement.",
    }


def position_size(bankroll, entry_price, decision, cfg):
    # Paper sizing has its own cap. Do not reuse the live-order safety cap here.
    risk_dollars = max(0.0, float(bankroll) * float(cfg["risk_per_trade_pct"]))
    paper_cap = float(cfg.get("paper_max_order_dollars", risk_dollars or 0.0))
    if paper_cap > 0:
        risk_dollars = min(risk_dollars, paper_cap)
    ask = max(float(entry_price), 0.001)
    contracts = risk_dollars / ask
    contracts = min(contracts, float(cfg["max_contracts"]))
    return max(0.0, math.floor(contracts * 100) / 100.0)
