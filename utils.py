from __future__ import annotations
import math
from decimal import Decimal, ROUND_DOWN

def f(x, default=None):
    if x is None or x == "":
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def sigmoid(x):
    x = clamp(x, -20.0, 20.0)
    return 1.0 / (1.0 + math.exp(-x))

def polymarket_fee_estimate(price: float, contracts: float = 1.0, fee_rate: float = 0.07) -> float:
    """Estimate Polymarket crypto taker fee in USDC.

    Current crypto fee curve: contracts * fee_rate * p * (1-p).
    Makers pay zero trading fee; actual protocol rounding is handled by Polymarket.
    """
    p = clamp(float(price), 0.0, 1.0)
    c = max(0.0, float(contracts))
    return float(fee_rate) * c * p * (1.0 - p)


def kalshi_fee_estimate(price: float, contracts: float = 1.0) -> float:
    """
    Approximate standard taker fee using 0.07 * C * P * (1-P).
    Actual fees/rounding can differ by product/account and Kalshi rules.
    Returns dollars.
    """
    p = clamp(float(price), 0.0, 1.0)
    c = max(0.0, float(contracts))
    return 0.07 * c * p * (1.0 - p)

def fmt_price(x: float) -> str:
    return f"{Decimal(str(x)).quantize(Decimal('0.0001'), rounding=ROUND_DOWN):.4f}"

def fmt_count(x: float) -> str:
    return f"{Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_DOWN):.2f}"
