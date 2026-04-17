"""Data adapter interface.

Subclass `DataAdapter` for any exchange, data provider, or historical source.
The only required method is `fetch_candles()`. The returned candle dicts must
have these keys: timestamp (ms), open, high, low, close, volume.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict


class Candle(TypedDict):
    timestamp: int  # Unix ms
    open: float
    high: float
    low: float
    close: float
    volume: float


class DataAdapter(ABC):
    """Base class for all market data adapters.

    Implementations should be stateless or hold only read-only config.
    Do not cache candles here — let callers cache if they need to.
    """

    @abstractmethod
    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> list[Candle]:
        """Return the most recent `limit` candles for `symbol` at `timeframe`.

        Args:
            symbol: Exchange-specific ticker (e.g. "BTC", "ES", "EURUSD").
            timeframe: "1m", "5m", "15m", "1h", "4h", "1d".
            limit: Max candles to return. Most recent last.

        Returns:
            List of Candle dicts, oldest first.
        """
        ...

    def fetch_historical(
        self,
        symbol: str,
        timeframe: str,
        days: int,
    ) -> list[Candle]:
        """Fetch historical data covering the last `days` days.

        Default implementation calls fetch_candles with a large limit.
        Override if your adapter supports pagination for longer lookbacks.
        """
        _tf_minutes = {
            "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "2h": 120, "4h": 240, "1d": 1440,
        }
        mins = _tf_minutes.get(timeframe, 5)
        limit = (days * 1440) // mins + 1
        return self.fetch_candles(symbol, timeframe, limit=limit)
