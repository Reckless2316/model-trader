"""Candle builders for deterministic tests."""

from __future__ import annotations

TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def candle(ts: int, o: float, h: float, l: float, c: float, v: float = 1.0) -> dict:
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}


def flat_series(timeframe: str, count: int, *, start_ms: int = 0, price: float = 100.0) -> list[dict]:
    step = TF_MS[timeframe]
    return [candle(start_ms + i * step, price, price + 0.5, price - 0.5, price) for i in range(count)]


def from_closes(closes: list[float], *, timeframe: str = "5m", start_ms: int = 0, wick: float = 0.1) -> list[dict]:
    step = TF_MS[timeframe]
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append(candle(start_ms + i * step, o, max(o, c) + wick, min(o, c) - wick, c))
        prev = c
    return out
