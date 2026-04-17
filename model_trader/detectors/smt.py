"""SMT (Smart Money Technique) divergence detector.

Compares swing highs/lows between correlated assets to detect divergence.
"""

from __future__ import annotations
from typing import TypedDict


class SMTSignal(TypedDict):
    type: str       # 'bullish' or 'bearish'
    strength: str   # 'strong' or 'weak'


def detect_smt(
    asset1_swings: list[dict], asset2_swings: list[dict]
) -> list[SMTSignal]:
    signals: list[SMTSignal] = []

    # Compare swing highs (bearish SMT)
    a1_highs = [s for s in asset1_swings if s["type"] == "high"][-5:]
    a2_highs = [s for s in asset2_swings if s["type"] == "high"][-5:]

    if len(a1_highs) >= 2 and len(a2_highs) >= 2:
        a1_hh = a1_highs[-1]["price"] > a1_highs[-2]["price"]
        a2_hh = a2_highs[-1]["price"] > a2_highs[-2]["price"]

        if a1_hh and not a2_hh:
            strength = (
                "strong"
                if abs(a1_highs[-1]["index"] - a2_highs[-1]["index"]) < 3
                else "weak"
            )
            signals.append(SMTSignal(type="bearish", strength=strength))
        elif not a1_hh and a2_hh:
            signals.append(SMTSignal(type="bearish", strength="weak"))

    # Compare swing lows (bullish SMT)
    a1_lows = [s for s in asset1_swings if s["type"] == "low"][-5:]
    a2_lows = [s for s in asset2_swings if s["type"] == "low"][-5:]

    if len(a1_lows) >= 2 and len(a2_lows) >= 2:
        a1_ll = a1_lows[-1]["price"] < a1_lows[-2]["price"]
        a2_ll = a2_lows[-1]["price"] < a2_lows[-2]["price"]

        if a1_ll and not a2_ll:
            strength = (
                "strong"
                if abs(a1_lows[-1]["index"] - a2_lows[-1]["index"]) < 3
                else "weak"
            )
            signals.append(SMTSignal(type="bullish", strength=strength))

    return signals
