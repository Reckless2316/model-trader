"""Hyperliquid public API adapter.

Reference implementation. No API key needed — Hyperliquid's info endpoint
is fully public. Supports both native perps (e.g. "BTC") and synthetic
perps deployed by builders (e.g. "xyz:GOLD", "xyz:SP500").
"""

from __future__ import annotations

import time
import requests

from .base import DataAdapter, Candle


API_URL = "https://api.hyperliquid.xyz/info"

# Map standard timeframe strings to Hyperliquid's interval values
_TF_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h", "8h": "8h", "12h": "12h",
    "1d": "1d", "3d": "3d", "1w": "1w",
}

_TF_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "8h": 28_800_000, "12h": 43_200_000, "1d": 86_400_000,
    "3d": 259_200_000, "1w": 604_800_000,
}


class HyperliquidAdapter(DataAdapter):
    """Fetches OHLCV data from Hyperliquid's public info endpoint."""

    def __init__(self, timeout: float = 10.0, session: requests.Session | None = None):
        self.timeout = timeout
        self.session = session or requests.Session()

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> list[Candle]:
        interval = _TF_MAP.get(timeframe, timeframe)
        interval_ms = _TF_MS.get(interval, 300_000)

        end_ms = int(time.time() * 1000)
        start_ms = end_ms - (limit * interval_ms)

        return self._fetch_range(symbol, interval, start_ms, end_ms, limit)

    def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        days: int,
    ) -> list[Candle]:
        interval = _TF_MAP.get(timeframe, timeframe)
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - (days * 86_400_000)
        return self._fetch_range(symbol, interval, start_ms, end_ms, limit=None)

    def _fetch_range(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        limit: int | None,
    ) -> list[Candle]:
        """Paginate through candleSnapshot (max ~500 per response)."""
        candles: list[Candle] = []
        cursor = start_ms

        while cursor < end_ms:
            resp = self.session.post(
                API_URL,
                json={
                    "type": "candleSnapshot",
                    "req": {
                        "coin": symbol,
                        "interval": interval,
                        "startTime": cursor,
                        "endTime": end_ms,
                    },
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break

            for row in batch:
                candles.append({
                    "timestamp": row["t"],
                    "open": float(row["o"]),
                    "high": float(row["h"]),
                    "low": float(row["l"]),
                    "close": float(row["c"]),
                    "volume": float(row["v"]),
                })
            cursor = batch[-1]["T"] + 1

            if limit and len(candles) >= limit:
                break

        # Deduplicate by timestamp (pagination can overlap)
        seen: set[int] = set()
        unique: list[Candle] = []
        for c in candles:
            if c["timestamp"] not in seen:
                seen.add(c["timestamp"])
                unique.append(c)

        return unique[-limit:] if limit else unique
