from __future__ import annotations

import os
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from typing import Any

from dotenv import load_dotenv

load_dotenv()


class PolymarketTradingClient:
    """Thin wrapper around Polymarket's official `polymarket-client` SDK.

    The SDK handles account setup, CLOB authentication and EIP-712 order signing.
    This wrapper is intentionally lazy so paper mode can run even when no live
    credentials are configured.
    """

    def __init__(self):
        self._client = None

    @staticmethod
    def credentials_present() -> bool:
        required = [
            "SIGNER_PRIVATE_KEY",
            "POLYMARKET_WALLET_ADDRESS",
            "POLYMARKET_RELAYER_API_KEY",
            "POLYMARKET_RELAYER_API_KEY_ADDRESS",
        ]
        return all(bool(os.getenv(k, "").strip()) for k in required)

    @staticmethod
    def safety_unlocked() -> bool:
        return os.getenv("POLYMARKET_LIVE_CONFIRM", "").strip() == "I_UNDERSTAND_POLYMARKET_LIVE_TRADING"

    def connect(self):
        if self._client is not None:
            return self._client
        if not self.credentials_present():
            raise RuntimeError(
                "Polymarket live credentials are missing. Fill SIGNER_PRIVATE_KEY, "
                "POLYMARKET_WALLET_ADDRESS, POLYMARKET_RELAYER_API_KEY and "
                "POLYMARKET_RELAYER_API_KEY_ADDRESS in .env."
            )
        try:
            from polymarket import RelayerApiKey, SecureClient
        except Exception as exc:
            raise RuntimeError(
                "The official polymarket-client package is not installed. Run "
                "`py -m pip install -r requirements.txt`."
            ) from exc

        self._client = SecureClient.create(
            private_key=os.environ["SIGNER_PRIVATE_KEY"],
            wallet=os.environ["POLYMARKET_WALLET_ADDRESS"],
            api_key=RelayerApiKey(
                key=os.environ["POLYMARKET_RELAYER_API_KEY"],
                address=os.environ["POLYMARKET_RELAYER_API_KEY_ADDRESS"],
            ),
        )
        return self._client

    @staticmethod
    def _plain(obj: Any):
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            try:
                return obj.model_dump()
            except Exception:
                pass
        if is_dataclass(obj):
            try:
                return asdict(obj)
            except Exception:
                pass
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
        return {"raw": str(obj)}

    def validate_connection(self):
        client = self.connect()
        return {
            "wallet": str(getattr(client, "wallet", "")),
            "wallet_type": str(getattr(client, "wallet_type", "")),
        }

    def buy_market(
        self,
        asset_id: str,
        dollars: float,
        max_price: float,
        order_type: str = "FAK",
    ):
        """Buy one Polymarket outcome with a hard all-in spend cap and price cap.

        `amount` is the requested pre-fee USD notional. `max_spend` is set to the
        same dollar amount so fees cannot push the order above the configured cap.
        `max_price` prevents crossing above the bot's allowed price.
        """
        client = self.connect()
        dollars = max(0.01, float(dollars))
        max_price = min(0.99, max(0.01, float(max_price)))
        ot = str(order_type or "FAK").upper()
        if ot not in ("FAK", "FOK"):
            raise ValueError("Polymarket order_type must be FAK or FOK")

        response = client.place_market_order(
            asset_id=str(asset_id),
            side="BUY",
            amount=f"{dollars:.2f}",
            max_spend=f"{dollars:.2f}",
            max_price=f"{max_price:.4f}",
            order_type=ot,
        )
        return self._plain(response)

    @staticmethod
    def response_matched(resp: dict) -> bool:
        success = resp.get("success")
        if success is False:
            return False
        status = str(resp.get("status") or resp.get("order_status") or "").lower()
        trade_ids = resp.get("tradeIDs") or resp.get("trade_ids") or []
        return status in ("matched", "filled", "partially_filled") or bool(trade_ids)

    @staticmethod
    def response_error(resp: dict) -> str:
        return str(resp.get("errorMsg") or resp.get("error_msg") or resp.get("message") or "")
