import hashlib
import hmac
import json
from decimal import Decimal

import httpx
import pytest

from trader.contracts import ContractSpec, OrderRejected
from trader.execution import (
    DuplicateOrder, InsufficientMargin, LiveCredentials, LiveOrderClient, OrderIntent, PaperBroker,
)

BTC = ContractSpec(
    symbol="BTC_USDT", tradable=True, price_unit=Decimal("0.1"), vol_unit=Decimal("1"),
    min_vol=Decimal("1"), max_vol=Decimal("400000"), contract_size=Decimal("0.0001"),
    min_leverage=1, max_leverage=500,
)


def intent(cid="c1", side="long", vol="10", leverage=5, stop="59000", take=None):
    return OrderIntent(
        client_id=cid, symbol="BTC_USDT", side=side, vol=Decimal(vol), leverage=leverage,
        price=None, stop_loss=Decimal(stop) if stop else None,
        take_profit=Decimal(take) if take else None,
    )


def broker(equity="100", fee="0", slip="0"):
    return PaperBroker(Decimal(equity), taker_fee_rate=Decimal(fee), slippage_pct=Decimal(slip))


# ---- paper broker ----------------------------------------------------------

def test_paper_open_reserves_margin_and_charges_fee():
    b = broker(equity="100", fee="0.001")
    b.open(intent(vol="10", leverage=5), BTC, Decimal("60000"))
    notional = Decimal("10") * Decimal("0.0001") * Decimal("60000")  # 60
    assert b.margin_in_use == notional / 5
    assert b.cash == Decimal("100") - notional * Decimal("0.001")


def test_paper_slippage_applied_adversely():
    b = broker(slip="0.001")
    pos = b.open(intent(), BTC, Decimal("60000"))
    assert pos.entry == Decimal("60060")  # long pays up
    s = broker(slip="0.001")
    short = s.open(intent(cid="s", side="short"), BTC, Decimal("60000"))
    assert short.entry == Decimal("59940")  # short sells down


def test_duplicate_client_id_rejected():
    b = broker()
    b.open(intent(cid="dup"), BTC, Decimal("60000"))
    with pytest.raises(DuplicateOrder):
        b.open(intent(cid="dup"), BTC, Decimal("60000"))
    assert len(b.positions) == 1


def test_insufficient_margin_rejected():
    b = broker(equity="1")
    with pytest.raises(InsufficientMargin):
        b.open(intent(vol="100", leverage=2), BTC, Decimal("60000"))


def test_invalid_order_rejected_before_fill():
    b = broker()
    with pytest.raises(OrderRejected):
        b.open(intent(vol="0.5"), BTC, Decimal("60000"))
    assert b.positions == []


def test_stop_loss_triggers_and_realizes_loss():
    b = broker(equity="100")
    b.open(intent(vol="10", leverage=5, stop="59000"), BTC, Decimal("60000"))
    b.mark("BTC_USDT", Decimal("58900"))  # through the stop
    assert b.positions == []
    assert b.closed[-1].reason == "stop_loss"
    # Long 10 contracts of 0.0001 BTC, exit 1000 below entry, zero fee and slippage: -1 USDT.
    assert b.closed[-1].pnl == Decimal("-1")


def test_take_profit_triggers_for_short():
    b = broker(equity="100")
    b.open(intent(side="short", vol="10", stop="61000", take="59000"), BTC, Decimal("60000"))
    b.mark("BTC_USDT", Decimal("58990"))
    assert b.closed[-1].reason == "take_profit"
    assert b.closed[-1].pnl > 0


def test_liquidation_caps_loss_at_margin():
    b = broker(equity="100")
    pos = b.open(intent(vol="10", leverage=5, stop=None), BTC, Decimal("60000"))
    margin = pos.margin
    b.mark("BTC_USDT", Decimal("1"))  # catastrophic move
    assert b.closed[-1].reason == "liquidation"
    assert b.closed[-1].pnl == -margin
    assert b.cash == Decimal("100") - margin


def test_mark_only_affects_matching_symbol():
    b = broker()
    b.open(intent(vol="10", stop="59000"), BTC, Decimal("60000"))
    b.mark("ETH_USDT", Decimal("1"))
    assert len(b.positions) == 1


# ---- live order client (mock transport, no network) -----------------------

CREDS = LiveCredentials(api_key="apikey", api_secret="topsecret")


def live_client(handler):
    return LiveOrderClient(CREDS, httpx.Client(base_url="https://api.mexc.com",
                                                transport=httpx.MockTransport(handler)))


def test_live_order_is_signed_over_exact_body_and_sent_to_create_endpoint():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json={"success": True, "code": 0, "data": {"orderId": "123"}})

    oid = live_client(handler).submit(intent(vol="10", leverage=5, stop="59000"), BTC)
    assert oid == "123"
    assert seen["url"].endswith("/api/v1/private/order/create")
    body = json.loads(seen["body"])
    assert body == {
        "symbol": "BTC_USDT", "price": "0", "vol": "10", "side": 1, "type": 5,
        "openType": 1, "leverage": 5, "externalOid": "c1", "stopLossPrice": "59000",
    }
    expected = hmac.new(b"topsecret", b"apikey" + seen["headers"]["request-time"].encode() + seen["body"],
                        hashlib.sha256).hexdigest()
    assert seen["headers"]["signature"] == expected
    assert seen["headers"]["apikey"] == "apikey"


def test_live_short_uses_open_short_code():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True, "code": 0, "data": {"orderId": "9"}})

    live_client(handler).submit(intent(side="short"), BTC)
    assert seen["body"]["side"] == 3


def test_live_duplicate_client_id_never_sent_twice():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"success": True, "code": 0, "data": {"orderId": "1"}})

    client = live_client(handler)
    client.submit(intent(cid="same"), BTC)
    with pytest.raises(DuplicateOrder):
        client.submit(intent(cid="same"), BTC)
    assert len(calls) == 1


def test_live_timeout_marks_order_submitted_so_retry_is_blocked():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("timed out", request=request)

    client = live_client(handler)
    with pytest.raises(httpx.ReadTimeout):
        client.submit(intent(cid="t1"), BTC)
    with pytest.raises(DuplicateOrder):  # a retry must not place a second order
        client.submit(intent(cid="t1"), BTC)
    assert len(calls) == 1


def test_live_exchange_rejection_surfaces():
    def handler(request):
        return httpx.Response(200, json={"success": False, "code": 2008, "message": "no"})

    with pytest.raises(OrderRejected, match="2008"):
        live_client(handler).submit(intent(), BTC)


def test_live_invalid_order_not_sent():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"success": True, "code": 0, "data": {"orderId": "1"}})

    with pytest.raises(OrderRejected):
        live_client(handler).submit(intent(vol="0.5"), BTC)
    assert calls == []


def test_credentials_not_in_repr():
    assert "topsecret" not in repr(CREDS)
