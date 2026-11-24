import hashlib
import hmac
from decimal import Decimal

import httpx
import pytest

from trader.account import ASSETS_PATH, AccountClient, AccountError, parse_assets

SAMPLE = {
    "success": True,
    "code": 0,
    "data": [
        {"currency": "USDT", "availableBalance": 32.80984793658, "equity": 32.80984793,
         "unrealized": 0, "positionMargin": 0, "cashBalance": 32.8},
        {"currency": "BTC", "availableBalance": 0, "equity": 0, "unrealized": 0},
    ],
}


def test_parse_assets_maps_fields_as_decimal():
    out = parse_assets(SAMPLE)
    usdt = out["USDT"]
    assert usdt.equity == Decimal("32.80984793")
    assert usdt.available == Decimal("32.80984793658")
    assert usdt.unrealized == Decimal("0")
    assert set(out) == {"USDT", "BTC"}


def test_parse_assets_raises_on_error_code():
    with pytest.raises(AccountError, match="1002"):
        parse_assets({"success": False, "code": 1002, "data": None})


def test_parse_assets_empty_data():
    assert parse_assets({"success": True, "code": 0, "data": []}) == {}


def test_request_is_signed_get_with_no_parameters():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["query"] = request.url.query
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json=SAMPLE)

    client = AccountClient("apikey", "topsecret",
                           httpx.Client(base_url="https://api.mexc.com",
                                        transport=httpx.MockTransport(handler)))
    balances = client.assets()

    assert seen["path"] == ASSETS_PATH
    assert seen["query"] == b""
    ts = seen["headers"]["request-time"]
    expected = hmac.new(b"topsecret", f"apikey{ts}".encode(), hashlib.sha256).hexdigest()
    assert seen["headers"]["signature"] == expected
    assert seen["headers"]["apikey"] == "apikey"
    assert balances["USDT"].equity == Decimal("32.80984793")


def test_http_error_propagates_without_leaking_secret():
    def handler(request):
        return httpx.Response(401, json={"success": False, "code": 401})

    client = AccountClient("apikey", "topsecret",
                           httpx.Client(base_url="https://api.mexc.com",
                                        transport=httpx.MockTransport(handler)))
    with pytest.raises(httpx.HTTPStatusError) as exc:
        client.assets()
    assert "topsecret" not in str(exc.value)
