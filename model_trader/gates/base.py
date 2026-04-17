"""Scanner base class and result types.

The gate pattern: a scanner walks through sequential checks. Each gate is a
binary pass/fail. If any gate fails, the setup is SKIP or WAIT. Only when
all gates pass does the scanner produce a TAKE signal.

Status meanings:
    TAKE     - all gates passed, this is a valid entry
    WAIT     - setup is forming but not ready (e.g. waiting for LTF trigger)
    SKIP     - setup is invalidated (e.g. competing draws, broken structure)
    NO_SETUP - nothing of interest on this symbol right now
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SetupStatus(str, Enum):
    TAKE = "TAKE"
    WAIT = "WAIT"
    SKIP = "SKIP"
    NO_SETUP = "NO_SETUP"


@dataclass
class SetupResult:
    """The output of evaluating one symbol through the scanner.

    Only TAKE results are actionable. entry/stop/target must be set for TAKE.
    `extras` is a free-form dict for strategy-specific state you want to log
    or pass to the paper trader (draw type, variation name, SMT status, etc.).
    """

    symbol: str
    status: SetupStatus = SetupStatus.NO_SETUP
    direction: str | None = None        # "long" or "short"
    reason: str = ""                     # Human-readable why (esp. for SKIP/WAIT)
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    gates_passed: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "status": self.status.value,
            "direction": self.direction,
            "reason": self.reason,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "gates_passed": self.gates_passed,
            "extras": self.extras,
            "timestamp": self.timestamp,
        }


class ScannerBase(ABC):
    """Subclass this to implement a trader's strategy.

    In __init__, store your config and data adapter. In evaluate(), run your
    gates in order. Return a SetupResult with the appropriate status.

    See docs/designing-gates.md for guidance on mapping a trader's rules to
    a gate sequence.
    """

    def __init__(self, config: dict, data_adapter):
        self.config = config
        self.data = data_adapter
        self.symbols = config.get("symbols", [])
        self.timeframes = config.get("timeframes", ["1m", "5m", "15m", "1h", "4h"])
        self.correlations = config.get("correlations", {})

    @abstractmethod
    def evaluate(self, symbol: str) -> SetupResult:
        """Run the full gate pipeline for one symbol.

        Implementations should:
        1. Fetch candle data for each timeframe
        2. Run gates in order, returning early on failure
        3. Only produce TAKE if all gates pass and entry/stop/target are set
        """
        ...

    def scan_all(self) -> list[SetupResult]:
        """Evaluate every symbol in the config."""
        return [self.evaluate(s) for s in self.symbols]

    def fetch_data(self, symbol: str, extra_timeframes: list[str] | None = None) -> dict:
        """Helper: fetch all configured timeframes for a symbol into a dict.

        Returns {tf: [candles]}. Missing timeframes become empty lists so
        downstream code can check `data.get(tf)` safely.
        """
        tfs = list(self.timeframes)
        if extra_timeframes:
            tfs.extend(t for t in extra_timeframes if t not in tfs)

        data: dict[str, list[dict]] = {}
        for tf in tfs:
            try:
                data[tf] = self.data.fetch_candles(symbol, tf)
            except Exception as e:
                data[tf] = []
                print(f"  [fetch warning] {symbol} {tf}: {e}", flush=True)
        return data

    def fetch_correlation(self, symbol: str, timeframes: list[str]) -> dict:
        """Helper: fetch correlation pair data if configured."""
        pair = self.correlations.get(symbol)
        if not pair:
            return {}
        corr: dict[str, list[dict]] = {}
        for tf in timeframes:
            try:
                corr[tf] = self.data.fetch_candles(pair, tf)
            except Exception:
                corr[tf] = []
        return corr
