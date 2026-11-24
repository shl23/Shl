from decimal import Decimal

import pytest

from trader.contracts import ContractSpec, OrderRejected, floor_to_step, is_multiple_of, validate_order

BTC = ContractSpec(
    symbol="BTC_USDT", tradable=True, price_unit=Decimal("0.1"), vol_unit=Decimal("1"),
    min_vol=Decimal("1"), max_vol=Decimal("400000"), contract_size=Decimal("0.0001"),
    min_leverage=1, max_leverage=500,
)


def test_from_api_parses_detail_payload():
    spec = ContractSpec.from_api({
        "symbol": "ETH_USDT", "state": 0, "apiAllowed": True, "priceUnit": 0.01, "volUnit": 1,
        "minVol": 1, "maxVol": 70000, "contractSize": 0.01, "minLeverage": 1, "maxLeverage": 500,
    })
    assert spec.tradable and spec.contract_size == Decimal("0.01")
    assert spec.price_unit == Decimal("0.01")


def test_from_api_marks_disabled_contract_not_tradable():
    spec = ContractSpec.from_api({
        "symbol": "X_USDT", "state": 1, "apiAllowed": True, "priceUnit": 1, "volUnit": 1,
        "minVol": 1, "maxVol": 10, "contractSize": 1, "minLeverage": 1, "maxLeverage": 10,
    })
    assert not spec.tradable


def test_floor_and_alignment_helpers():
    assert floor_to_step(Decimal("3.7"), Decimal("1")) == Decimal("3")
    assert floor_to_step(Decimal("0.37"), Decimal("0.1")) == Decimal("0.3")
    assert is_multiple_of(Decimal("60401.5"), Decimal("0.1"))
    assert not is_multiple_of(Decimal("60401.55"), Decimal("0.1"))


def test_notional_uses_contract_size():
    assert BTC.notional(Decimal("2"), Decimal("60000")) == Decimal("12.0")


def test_valid_order_passes():
    validate_order(BTC, Decimal("1"), Decimal("60000.0"), 10)


@pytest.mark.parametrize("kwargs,match", [
    (dict(vol=Decimal("0")), "positive"),
    (dict(vol=Decimal("0.5")), "multiple"),
    (dict(vol=Decimal("0")), "positive"),
    (dict(vol=Decimal("500000")), "above maximum"),
    (dict(vol=Decimal("1"), price=Decimal("60000.05")), "tick"),
    (dict(vol=Decimal("1"), price=Decimal("60000.0"), leverage=501), "leverage"),
])
def test_invalid_orders_rejected(kwargs, match):
    with pytest.raises(OrderRejected, match=match):
        validate_order(BTC, **kwargs)


def test_below_minimum_rejected():
    spec = ContractSpec(**{**BTC.__dict__, "min_vol": Decimal("2")})
    with pytest.raises(OrderRejected, match="below minimum"):
        validate_order(spec, Decimal("1"))


def test_untradable_contract_rejected():
    spec = ContractSpec(**{**BTC.__dict__, "tradable": False})
    with pytest.raises(OrderRejected, match="not tradable"):
        validate_order(spec, Decimal("1"))
