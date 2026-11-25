from __future__ import annotations
import requests
import pandas as pd
import numpy as np

UA = {"User-Agent":"marketpilot-v7/1.0"}


def coinbase_candles(minutes=120):
    url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    r = requests.get(url, params={"granularity":60}, headers=UA, timeout=10)
    r.raise_for_status()
    rows = r.json()
    df = pd.DataFrame(rows, columns=["time","low","high","open","close","volume"])
    df = df.sort_values("time").tail(minutes).reset_index(drop=True)
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna()


def _rsi(series, period=14):
    d = series.diff()
    gain = d.clip(lower=0).rolling(period).mean()
    loss = (-d.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    try:
        return float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0
    except Exception:
        return 50.0


def features(df):
    c = df["close"].astype(float)
    v = df["volume"].astype(float)
    logret = np.log(c).diff()

    def ret(n):
        if len(c) <= n:
            return 0.0
        return float(c.iloc[-1] / c.iloc[-1-n] - 1.0)

    vol15 = float(logret.tail(15).std(ddof=0) or 0.0)
    vol5 = float(logret.tail(5).std(ddof=0) or 0.0)
    ema3s = c.ewm(span=3).mean()
    ema8s = c.ewm(span=8).mean()
    ema13s = c.ewm(span=13).mean()
    ema3 = float(ema3s.iloc[-1])
    ema8 = float(ema8s.iloc[-1])
    ema13 = float(ema13s.iloc[-1])
    vr = float(v.tail(3).mean() / max(v.tail(15).mean(), 1e-12))
    ema_slope = float(ema8s.iloc[-1] / ema8s.iloc[-4] - 1.0) if len(ema8s) >= 4 else 0.0
    range5 = float((df["high"].tail(5).max() - df["low"].tail(5).min()) / max(c.iloc[-1], 1e-9))

    return {
        "spot": float(c.iloc[-1]),
        "mom1": ret(1),
        "mom3": ret(3),
        "mom5": ret(5),
        "mom10": ret(10),
        "vol5": vol5,
        "vol15": vol15,
        "trend": ema3 / ema8 - 1.0,
        "ema_fast_slow": ema8 / ema13 - 1.0,
        "ema_slope": ema_slope,
        "rsi14": _rsi(c, 14),
        "range5": range5,
        "volume_ratio": vr,
    }


def coinbase_spot():
    r = requests.get("https://api.exchange.coinbase.com/products/BTC-USD/ticker", headers=UA, timeout=8)
    r.raise_for_status()
    return float(r.json()["price"])
