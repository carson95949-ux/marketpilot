from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import requests

UA = {"User-Agent": "edgepulse-market-intelligence/1.0"}
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"


class PolymarketClient:
    """Public-data client for Polymarket BTC Up/Down markets."""

    def _get(self, url, params=None, timeout=10):
        r = requests.get(url, params=params, headers=UA, timeout=timeout)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _window_epoch(minutes: int, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        span = minutes * 60
        return int(now.timestamp()) // span * span

    def _fetch_slug(self, slug: str):
        # Current Polymarket docs expose public event lookup by slug.
        try:
            event = self._get(f"{GAMMA}/events/slug/{slug}")
            markets = event.get("markets") or []
            if markets:
                market = markets[0]
                market["_event"] = event
                return market
        except Exception:
            pass
        # Compatibility fallback for older Gamma market-by-slug deployments.
        try:
            market = self._get(f"{GAMMA}/markets/slug/{slug}")
            if market:
                return market
        except Exception:
            pass
        return None

    def current_btc_updown(self, minutes: int):
        if minutes not in (5, 15):
            raise ValueError("minutes must be 5 or 15")

        now = datetime.now(timezone.utc)
        base = self._window_epoch(minutes, now)
        span = minutes * 60

        # Try current window first, then adjacent windows to tolerate clock/API lag.
        candidates = []
        for offset in (0, -1, 1, -2):
            start_ts = base + offset * span
            slug = f"btc-updown-{minutes}m-{start_ts}"
            m = self._fetch_slug(slug)
            if not m:
                continue

            end_ts = start_ts + span
            for key in ("endDate", "end_date_iso", "endDateIso"):
                if m.get(key):
                    try:
                        end_ts = int(datetime.fromisoformat(str(m[key]).replace("Z", "+00:00")).timestamp())
                        break
                    except Exception:
                        pass

            seconds_left = end_ts - int(now.timestamp())
            if -20 <= seconds_left <= span + 90:
                candidates.append((abs(seconds_left - span / 2), m, start_ts, end_ts, seconds_left, slug))

        if not candidates:
            raise RuntimeError(f"No current Polymarket BTC {minutes}m market found.")

        candidates.sort(key=lambda x: x[0])
        _, market, start_ts, end_ts, seconds_left, slug = candidates[0]
        q = self.quotes(market)
        return {
            "market": market,
            "slug": slug,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "seconds_left": seconds_left,
            **q,
        }

    @staticmethod
    def _parse_jsonish(value):
        if isinstance(value, (list, dict)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return value
        return value

    def token_map(self, market):
        ids = self._parse_jsonish(market.get("clobTokenIds"))
        outcomes = self._parse_jsonish(market.get("outcomes"))

        # Gamma legacy shape: clobTokenIds + outcomes are parallel arrays.
        if isinstance(ids, list) and isinstance(outcomes, list) and len(ids) >= 2:
            mapping = {str(o).strip().lower(): str(t) for o, t in zip(outcomes, ids)}
            up = mapping.get("up") or mapping.get("yes") or str(ids[0])
            down = mapping.get("down") or mapping.get("no") or str(ids[1])
            return up, down

        # Newer/public-client style can expose nested outcomes.
        o = market.get("outcomes")
        if isinstance(o, dict):
            up_obj = o.get("up") or o.get("yes") or {}
            dn_obj = o.get("down") or o.get("no") or {}
            up = up_obj.get("tokenId") or up_obj.get("token_id")
            dn = dn_obj.get("tokenId") or dn_obj.get("token_id")
            if up and dn:
                return str(up), str(dn)

        raise RuntimeError("Polymarket token IDs are unavailable for this market.")

    def book(self, token_id: str):
        return self._get(f"{CLOB}/book", params={"token_id": token_id}, timeout=8)

    @staticmethod
    def _best(book, side):
        levels = book.get(side) or []
        prices = []
        for level in levels:
            try:
                prices.append(float(level.get("price")))
            except Exception:
                pass
        if not prices:
            return None
        return min(prices) if side == "asks" else max(prices)

    @staticmethod
    def _top_depth(book, side, levels=3):
        rows=[]
        for level in (book.get(side) or []):
            try:
                rows.append((float(level.get("price")), float(level.get("size") or 0)))
            except Exception:
                pass
        rows.sort(key=lambda x:x[0], reverse=(side=="bids"))
        return sum(size for _,size in rows[:max(1,int(levels))])

    @classmethod
    def _book_imbalance(cls, book, levels=3):
        bid=cls._top_depth(book,"bids",levels)
        ask=cls._top_depth(book,"asks",levels)
        total=bid+ask
        return 0.0 if total<=0 else (bid-ask)/total

    def quotes(self, market):
        up_id, down_id = self.token_map(market)
        up_book = self.book(up_id)
        down_book = self.book(down_id)
        up_bid = self._best(up_book, "bids")
        up_ask = self._best(up_book, "asks")
        down_bid = self._best(down_book, "bids")
        down_ask = self._best(down_book, "asks")
        spread = None
        if up_bid is not None and up_ask is not None:
            spread = max(0.0, up_ask - up_bid)
        levels = 3
        up_bid_depth = self._top_depth(up_book, "bids", levels)
        up_ask_depth = self._top_depth(up_book, "asks", levels)
        down_bid_depth = self._top_depth(down_book, "bids", levels)
        down_ask_depth = self._top_depth(down_book, "asks", levels)
        up_imbalance = self._book_imbalance(up_book, levels)
        down_imbalance = self._book_imbalance(down_book, levels)
        # Bullish binary pressure: YES bid pressure minus NO bid pressure.
        # Using both books is less brittle than reading the UP book alone.
        book_imbalance = max(-1.0, min(1.0, 0.5 * (up_imbalance - down_imbalance)))
        return {
            "up_token_id": up_id,
            "down_token_id": down_id,
            "yes_bid": up_bid,
            "yes_ask": up_ask,
            "no_bid": down_bid,
            "no_ask": down_ask,
            "spread": spread,
            "yes_bid_depth": up_bid_depth,
            "yes_ask_depth": up_ask_depth,
            "no_bid_depth": down_bid_depth,
            "no_ask_depth": down_ask_depth,
            "yes_book_imbalance": up_imbalance,
            "no_book_imbalance": down_imbalance,
            "book_imbalance": book_imbalance,
        }


    def official_price_to_beat(self, market):
        """Return Gamma/Polymarket's official priceToBeat when already published."""
        containers=[market, market.get("_event") if isinstance(market,dict) else None]
        for obj in containers:
            if not isinstance(obj,dict):
                continue
            meta=self._parse_jsonish(obj.get("eventMetadata"))
            if isinstance(meta,dict):
                for key in ("priceToBeat","price_to_beat"):
                    try:
                        v=float(meta.get(key))
                        if v>1000:
                            return v
                    except Exception:
                        pass
        return None

    def market_by_slug(self, slug: str):
        return self._fetch_slug(slug)

    def resolution_result(self, slug: str):
        """Return YES/NO for a resolved Up/Down market, or None while unresolved."""
        m = self._fetch_slug(slug)
        if not m:
            return None
        outcomes = self._parse_jsonish(m.get("outcomes"))
        prices = self._parse_jsonish(m.get("outcomePrices"))
        if isinstance(outcomes, list) and isinstance(prices, list) and len(outcomes) == len(prices):
            vals = []
            for i, p in enumerate(prices):
                try: vals.append((float(p), str(outcomes[i]).strip().lower()))
                except Exception: pass
            if vals:
                vals.sort(reverse=True)
                top_p, top_name = vals[0]
                if top_p >= 0.99:
                    if top_name in ("up", "yes"):
                        return "YES"
                    if top_name in ("down", "no"):
                        return "NO"
        # Some Gamma payloads expose a direct result/winner field.
        for key in ("result", "winner", "winningOutcome", "resolvedOutcome"):
            v = str(m.get(key) or "").strip().lower()
            if v in ("up", "yes"): return "YES"
            if v in ("down", "no"): return "NO"
        return None
