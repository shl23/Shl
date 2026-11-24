import math

import pytest

from trader.indicators import adx_last, atr_last, ema, macd_last, rsi_last


def test_ema_of_constant_series_is_constant():
    out = ema([5.0] * 30, 9)
    assert len(out) == 30
    assert all(math.isclose(v, 5.0) for v in out)


def test_ema_reacts_faster_than_slow_ema_on_uptrend():
    closes = [float(i) for i in range(1, 80)]
    assert ema(closes, 9)[-1] > ema(closes, 21)[-1]


def test_rsi_all_gains_is_100_and_all_losses_is_0():
    assert rsi_last([float(i) for i in range(1, 30)]) == 100.0
    assert rsi_last([float(100 - i) for i in range(30)]) == pytest.approx(0.0, abs=1e-9)


def test_rsi_alternating_is_near_50():
    closes = [100.0 + (1 if i % 2 else -1) for i in range(60)]
    assert rsi_last(closes) == pytest.approx(50.0, abs=5.0)


def test_atr_constant_range():
    highs = [10.0 + i * 0 + 1 for i in range(40)]
    lows = [10.0 - 1 for _ in range(40)]
    closes = [10.0] * 40
    assert atr_last(highs, lows, closes) == pytest.approx(2.0)


def test_macd_flat_series_is_zero():
    res = macd_last([50.0] * 60)
    assert res.macd == pytest.approx(0.0, abs=1e-9)
    assert res.histogram == pytest.approx(0.0, abs=1e-9)


def test_macd_positive_histogram_on_accelerating_uptrend():
    closes = [100.0 + 0.5 * i * i / 10 for i in range(80)]
    assert macd_last(closes).macd > 0


def test_adx_high_on_strong_trend_and_low_on_chop():
    n = 80
    highs = [100.0 + i for i in range(n)]
    lows = [99.0 + i for i in range(n)]
    closes = [99.5 + i for i in range(n)]
    assert adx_last(highs, lows, closes) > 50

    chop_h = [101.0 + (1 if i % 2 else -1) * 0.2 for i in range(n)]
    chop_l = [99.0 + (1 if i % 2 else -1) * 0.2 for i in range(n)]
    chop_c = [100.0 + (1 if i % 2 else -1) * 0.2 for i in range(n)]
    assert adx_last(chop_h, chop_l, chop_c) < 25


def test_insufficient_data_raises():
    with pytest.raises(ValueError):
        rsi_last([1.0] * 5)
    with pytest.raises(ValueError):
        adx_last([1.0] * 10, [1.0] * 10, [1.0] * 10)
