"""Market data adapters.

To add a new exchange or data source, subclass `DataAdapter` and implement
`fetch_candles()`. Your scanner and paper trader only need a DataAdapter
instance — they don't care where the data comes from.
"""

from .base import DataAdapter, Candle
from .hyperliquid import HyperliquidAdapter

__all__ = ["DataAdapter", "Candle", "HyperliquidAdapter"]
