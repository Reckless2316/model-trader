"""Paper trading engine: simulate trades, track exits, compute metrics.

The PaperTrader persists to a JSON journal so state survives restarts.
Filters (duplicate detection, invalidated level tracking) plug into the
monitor loop to prevent common failure modes (scalp duplicates, cascades).
"""

from .trader import PaperTrader, Trade
from .filters import is_duplicate_setup, is_invalidated_level
from .metrics import calculate_metrics

__all__ = [
    "PaperTrader",
    "Trade",
    "is_duplicate_setup",
    "is_invalidated_level",
    "calculate_metrics",
]
