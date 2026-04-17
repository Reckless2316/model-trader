"""Reusable price-action detectors — the building blocks every strategy uses.

Each detector takes a list of OHLCV candle dicts and returns structured
events (swings, gaps, patterns). Detectors are pure functions — no side
effects, no IO. Your scanner composes these into a gate pipeline.
"""

from .fvg import detect_fvg, update_fvg_states, FVG
from .swings import detect_swings, Swing
from .failure_swings import detect_failure_swings, FailureSwing
from .cisd import detect_cisd, detect_cisd_breaker, CISDSignal, Breaker
from .smt import detect_smt, SMTSignal
from .displacement import detect_displacement, Displacement

__all__ = [
    "detect_fvg",
    "update_fvg_states",
    "FVG",
    "detect_swings",
    "Swing",
    "detect_failure_swings",
    "FailureSwing",
    "detect_cisd",
    "detect_cisd_breaker",
    "CISDSignal",
    "Breaker",
    "detect_smt",
    "SMTSignal",
    "detect_displacement",
    "Displacement",
]
