"""Technical indicators on closed candles (pure Python, Wilder smoothing where standard).

Inputs are plain sequences of floats ordered oldest -> newest. Callers must pass
only closed candles; the engine never evaluates a forming candle.
"""

from __future__ import annotations

from dataclasses import dataclass


def ema(values: list[float], period: int) -> list[float]:
    if period < 1 or len(values) < period:
        raise ValueError("need at least `period` values")
    alpha = 2.0 / (period + 1)
    out = [sum(values[:period]) / period]  # seed with SMA
    for v in values[period:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    # Pad the front so the output aligns with the input index.
    return [out[0]] * (period - 1) + out


def rsi_last(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        raise ValueError("need at least period+1 closes")
    diffs = [b - a for a, b in zip(closes, closes[1:])]
    gains = [max(d, 0.0) for d in diffs]
    losses = [max(-d, 0.0) for d in diffs]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _true_ranges(highs, lows, closes) -> list[float]:
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return trs


def atr_last(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        raise ValueError("need at least period+1 candles")
    trs = _true_ranges(highs, lows, closes)
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = (value * (period - 1) + tr) / period
    return value


@dataclass(frozen=True)
class MacdResult:
    macd: float
    signal: float
    histogram: float


def macd_last(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> MacdResult:
    if len(closes) < slow + signal:
        raise ValueError("not enough closes for MACD")
    fast_e, slow_e = ema(closes, fast), ema(closes, slow)
    line = [f - s for f, s in zip(fast_e, slow_e)]
    sig = ema(line[slow - 1:], signal)
    m, s = line[-1], sig[-1]
    return MacdResult(macd=m, signal=s, histogram=m - s)


def adx_last(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    n = len(closes)
    if n < 2 * period + 1:
        raise ValueError("need at least 2*period+1 candles for ADX")
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))

    s_tr, s_pdm, s_mdm = sum(trs[:period]), sum(plus_dm[:period]), sum(minus_dm[:period])
    dx_values = []

    def dx(tr, pdm, mdm):
        if tr == 0:
            return 0.0
        pdi, mdi = 100.0 * pdm / tr, 100.0 * mdm / tr
        denom = pdi + mdi
        return 0.0 if denom == 0 else 100.0 * abs(pdi - mdi) / denom

    dx_values.append(dx(s_tr, s_pdm, s_mdm))
    for i in range(period, len(trs)):
        s_tr = s_tr - s_tr / period + trs[i]
        s_pdm = s_pdm - s_pdm / period + plus_dm[i]
        s_mdm = s_mdm - s_mdm / period + minus_dm[i]
        dx_values.append(dx(s_tr, s_pdm, s_mdm))

    value = sum(dx_values[:period]) / period
    for d in dx_values[period:]:
        value = (value * (period - 1) + d) / period
    return value
