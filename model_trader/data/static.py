"""In-memory data adapter for backtests over saved candles and for tests.

Hand it ``{symbol: {timeframe: [candles oldest-first]}}``. ``fetch_candles``
returns the most recent ``limit`` candles; ``fetch_historical`` returns all of
them (the backtest runner truncates per step, so no window math is needed).
"""

from __future__ import annotations

from .base import Candle, DataAdapter


class StaticAdapter(DataAdapter):
    def __init__(self, candles: dict[str, dict[str, list[Candle]]]):
        self.candles = candles

    def _series(self, symbol: str, timeframe: str) -> list[Candle]:
        try:
            return self.candles[symbol][timeframe]
        except KeyError as exc:
            raise KeyError(f"no {timeframe} candles for {symbol}") from exc

    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 200) -> list[Candle]:
        return list(self._series(symbol, timeframe)[-limit:])

    def fetch_historical(self, symbol: str, timeframe: str, days: int) -> list[Candle]:
        return list(self._series(symbol, timeframe))
