"""model-trader: turn a trader's content into an executable screener and paper trader."""

__version__ = "0.1.0"

from .data import DataAdapter, HyperliquidAdapter
from .gates import ScannerBase, SetupResult, SetupStatus
from .paper_trader import PaperTrader
from .monitor import run_monitor

__all__ = [
    "DataAdapter",
    "HyperliquidAdapter",
    "ScannerBase",
    "SetupResult",
    "SetupStatus",
    "PaperTrader",
    "run_monitor",
]
