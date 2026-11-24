"""Futures contract specifications and order validation.

All money and quantity arithmetic uses Decimal. Values come from MEXC's
public contract detail endpoint (GET /api/v1/contract/detail).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal


class OrderRejected(Exception):
    """Raised when an order violates contract rules or local validation."""


def to_decimal(value) -> Decimal:
    return Decimal(str(value))


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise ValueError("step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def is_multiple_of(value: Decimal, step: Decimal) -> bool:
    if step <= 0:
        raise ValueError("step must be positive")
    return (value / step) == (value / step).to_integral_value()


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    tradable: bool
    price_unit: Decimal
    vol_unit: Decimal
    min_vol: Decimal
    max_vol: Decimal
    contract_size: Decimal
    min_leverage: int
    max_leverage: int

    @classmethod
    def from_api(cls, d: dict) -> "ContractSpec":
        return cls(
            symbol=d["symbol"],
            tradable=d.get("state") == 0 and bool(d.get("apiAllowed")),
            price_unit=to_decimal(d["priceUnit"]),
            vol_unit=to_decimal(d["volUnit"]),
            min_vol=to_decimal(d["minVol"]),
            max_vol=to_decimal(d["maxVol"]),
            contract_size=to_decimal(d["contractSize"]),
            min_leverage=int(d["minLeverage"]),
            max_leverage=int(d["maxLeverage"]),
        )

    def notional(self, vol: Decimal, price: Decimal) -> Decimal:
        """Quote-currency value of `vol` contracts at `price`."""
        return vol * self.contract_size * price


def validate_order(
    spec: ContractSpec,
    vol: Decimal,
    price: Decimal | None = None,
    leverage: int | None = None,
) -> None:
    if not spec.tradable:
        raise OrderRejected(f"{spec.symbol} is not tradable via API")
    if vol <= 0:
        raise OrderRejected("vol must be positive")
    if not is_multiple_of(vol, spec.vol_unit):
        raise OrderRejected(f"vol {vol} is not a multiple of step {spec.vol_unit}")
    if vol < spec.min_vol:
        raise OrderRejected(f"vol {vol} below minimum {spec.min_vol}")
    if vol > spec.max_vol:
        raise OrderRejected(f"vol {vol} above maximum {spec.max_vol}")
    if price is not None:
        if price <= 0:
            raise OrderRejected("price must be positive")
        if not is_multiple_of(price, spec.price_unit):
            raise OrderRejected(f"price {price} is not a multiple of tick {spec.price_unit}")
    if leverage is not None and not (spec.min_leverage <= leverage <= spec.max_leverage):
        raise OrderRejected(
            f"leverage {leverage} outside [{spec.min_leverage}, {spec.max_leverage}]"
        )
