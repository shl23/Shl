"""Order execution: a simulated broker and a signed live order client.

PaperBroker: simulated fills with slippage and taker fees, liquidation, and
stop/take-profit triggers. It is the default path.

LiveOrderClient: signed POST to /api/v1/private/order/create. It is only
constructed after live_gate() passes. Its request logic is covered by tests
against a mock transport. No live order has been placed by this code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

import httpx

from .contracts import ContractSpec, OrderRejected, validate_order
from .signing import sign_request

Side = Literal["long", "short"]
ZERO = Decimal("0")


class DuplicateOrder(Exception):
    pass


class InsufficientMargin(Exception):
    pass


@dataclass(frozen=True)
class OrderIntent:
    client_id: str
    symbol: str
    side: Side
    vol: Decimal
    leverage: int
    price: Decimal | None          # None = market order
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None


@dataclass
class Position:
    symbol: str
    side: Side
    vol: Decimal
    contract_size: Decimal
    entry: Decimal
    leverage: int
    margin: Decimal
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    client_id: str = ""


@dataclass
class ClosedTrade:
    symbol: str
    side: Side
    pnl: Decimal
    reason: str


class PaperBroker:
    def __init__(self, equity: Decimal, *, taker_fee_rate: Decimal, slippage_pct: Decimal) -> None:
        if equity <= 0:
            raise ValueError("equity must be positive")
        self.cash = equity
        self.taker_fee_rate = taker_fee_rate
        self.slippage_pct = slippage_pct
        self.positions: list[Position] = []
        self.closed: list[ClosedTrade] = []
        self._seen: set[str] = set()

    @property
    def margin_in_use(self) -> Decimal:
        return sum((p.margin for p in self.positions), ZERO)

    @property
    def available_margin(self) -> Decimal:
        return self.cash - self.margin_in_use

    def _adverse(self, side: Side, price: Decimal, entering: bool) -> Decimal:
        # Entering long or exiting short pays up; the reverse pays down.
        buying = (side == "long") == entering
        return price * (1 + self.slippage_pct) if buying else price * (1 - self.slippage_pct)

    def open(self, intent: OrderIntent, spec: ContractSpec, mark_price: Decimal) -> Position:
        if intent.client_id in self._seen:
            raise DuplicateOrder(intent.client_id)
        validate_order(spec, intent.vol, intent.price, intent.leverage)
        fill = self._adverse(intent.side, mark_price, entering=True)
        notional = spec.notional(intent.vol, fill)
        margin = notional / intent.leverage
        fee = notional * self.taker_fee_rate
        if margin + fee > self.available_margin:
            raise InsufficientMargin(f"need {margin + fee}, available {self.available_margin}")
        self._seen.add(intent.client_id)
        self.cash -= fee
        pos = Position(
            symbol=intent.symbol,
            side=intent.side,
            vol=intent.vol,
            contract_size=spec.contract_size,
            entry=fill,
            leverage=intent.leverage,
            margin=margin,
            stop_loss=intent.stop_loss,
            take_profit=intent.take_profit,
            client_id=intent.client_id,
        )
        self.positions.append(pos)
        return pos

    def _pnl(self, pos: Position, exit_price: Decimal) -> Decimal:
        move = exit_price - pos.entry if pos.side == "long" else pos.entry - exit_price
        return move * pos.vol * pos.contract_size

    def _close(self, pos: Position, exit_price: Decimal, reason: str) -> None:
        fill = self._adverse(pos.side, exit_price, entering=False)
        pnl = self._pnl(pos, fill)
        # Liquidation caps loss at the posted margin.
        if reason == "liquidation":
            pnl = max(pnl, -pos.margin)
        exit_notional = pos.vol * pos.contract_size * fill
        fee = exit_notional * self.taker_fee_rate
        self.cash += pnl - fee
        self.positions.remove(pos)
        self.closed.append(ClosedTrade(pos.symbol, pos.side, pnl - fee, reason))

    def mark(self, symbol: str, price: Decimal) -> None:
        """Apply a new mark price: liquidation first, then stop-loss, then take-profit."""
        for pos in [p for p in self.positions if p.symbol == symbol]:
            if self._pnl(pos, price) <= -pos.margin:
                self._close(pos, price, "liquidation")
                continue
            if pos.stop_loss is not None and (
                (pos.side == "long" and price <= pos.stop_loss)
                or (pos.side == "short" and price >= pos.stop_loss)
            ):
                self._close(pos, pos.stop_loss, "stop_loss")
                continue
            if pos.take_profit is not None and (
                (pos.side == "long" and price >= pos.take_profit)
                or (pos.side == "short" and price <= pos.take_profit)
            ):
                self._close(pos, pos.take_profit, "take_profit")


@dataclass(frozen=True)
class LiveCredentials:
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)


class LiveOrderClient:
    PATH = "/api/v1/private/order/create"
    SIDE_CODE = {"long": 1, "short": 3}   # open long = 1, open short = 3
    TYPE_LIMIT, TYPE_MARKET = 1, 5
    OPEN_TYPE_ISOLATED = 1

    def __init__(self, creds: LiveCredentials, http: httpx.Client) -> None:
        self._creds = creds
        self._http = http
        self._submitted: set[str] = set()

    def submit(self, intent: OrderIntent, spec: ContractSpec) -> str:
        if intent.client_id in self._submitted:
            raise DuplicateOrder(intent.client_id)
        validate_order(spec, intent.vol, intent.price, intent.leverage)

        body = {
            "symbol": intent.symbol,
            "price": str(intent.price) if intent.price is not None else "0",
            "vol": str(intent.vol),
            "side": self.SIDE_CODE[intent.side],
            "type": self.TYPE_LIMIT if intent.price is not None else self.TYPE_MARKET,
            "openType": self.OPEN_TYPE_ISOLATED,
            "leverage": intent.leverage,
            "externalOid": intent.client_id,
        }
        if intent.stop_loss is not None:
            body["stopLossPrice"] = str(intent.stop_loss)
        if intent.take_profit is not None:
            body["takeProfitPrice"] = str(intent.take_profit)

        # Mark as submitted before sending so a retry after a timeout cannot double-order.
        self._submitted.add(intent.client_id)
        signed = sign_request(self._creds.api_key, self._creds.api_secret, "POST", body)
        resp = self._http.post(self.PATH, content=signed.body, headers=signed.headers)
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("success"):
            raise OrderRejected(f"exchange rejected order: code {payload.get('code')}")
        return str(payload["data"]["orderId"])
