"""Long/short signal evaluation on closed candles.

A starting rule set, not a validated strategy. A signal needs trend strength
(ADX gate) and at least two of three directional votes: EMA crossover, RSI
momentum, and MACD histogram. Otherwise the result is no trade.
"""

from __future__ import annotations

from dataclasses import dataclass

from .indicators import adx_last, atr_last, ema, macd_last, rsi_last

MIN_CANDLES = 60


@dataclass(frozen=True)
class Signal:
    direction: str | None   # "long", "short", or None
    votes_long: int
    votes_short: int
    adx: float
    atr: float
    reasons: tuple[str, ...]


def evaluate(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    fast: int = 9,
    slow: int = 21,
    adx_min: float = 20.0,
    min_votes: int = 2,
) -> Signal:
    if min(len(highs), len(lows), len(closes)) < MIN_CANDLES:
        return Signal(None, 0, 0, 0.0, 0.0, (f"need at least {MIN_CANDLES} closed candles",))

    adx = adx_last(highs, lows, closes)
    atr = atr_last(highs, lows, closes)
    if adx < adx_min:
        return Signal(None, 0, 0, adx, atr, (f"ADX {adx:.1f} below {adx_min} (no trend)",))

    fast_e, slow_e = ema(closes, fast), ema(closes, slow)
    rsi = rsi_last(closes)
    hist = macd_last(closes).histogram

    votes_long = votes_short = 0
    reasons: list[str] = []
    if fast_e[-1] > slow_e[-1]:
        votes_long += 1
        reasons.append("EMA fast > slow")
    elif fast_e[-1] < slow_e[-1]:
        votes_short += 1
        reasons.append("EMA fast < slow")
    if rsi > 55:
        votes_long += 1
        reasons.append(f"RSI {rsi:.1f} > 55")
    elif rsi < 45:
        votes_short += 1
        reasons.append(f"RSI {rsi:.1f} < 45")
    if hist > 0:
        votes_long += 1
        reasons.append("MACD histogram > 0")
    elif hist < 0:
        votes_short += 1
        reasons.append("MACD histogram < 0")

    direction = None
    if votes_long >= min_votes and votes_long > votes_short:
        direction = "long"
    elif votes_short >= min_votes and votes_short > votes_long:
        direction = "short"
    else:
        reasons.append(f"insufficient agreement (long {votes_long}, short {votes_short})")

    return Signal(direction, votes_long, votes_short, adx, atr, tuple(reasons))
