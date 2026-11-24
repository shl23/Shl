import hashlib
import hmac
import json
from urllib.parse import parse_qs

import pytest

from trader.signing import sign_request


def test_hmac_sha256_matches_rfc4231_vector():
    # RFC 4231 test case 2 checks the HMAC-SHA256 primitive itself.
    mac = hmac.new(b"Jefe", b"what do ya want for nothing?", hashlib.sha256).hexdigest()
    assert mac == "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"


def test_post_signature_covers_exact_body():
    req = sign_request("key1", "secret1", "POST", {"symbol": "BTC_USDT", "vol": 1},
                       timestamp_ms=1700000000000)
    assert req.body == b'{"symbol":"BTC_USDT","vol":1}'
    expected = hmac.new(b"secret1", b'key1' + b'1700000000000' + req.body, hashlib.sha256).hexdigest()
    assert req.headers["Signature"] == expected
    assert req.headers["ApiKey"] == "key1"
    assert req.headers["Request-Time"] == "1700000000000"


def test_get_params_are_sorted_encoded_and_signed_as_sent():
    req = sign_request("k", "s", "GET", {"symbol": "BTC_USDT", "b": "x y", "a": "1,2"},
                       timestamp_ms=5)
    assert req.query == "a=1%2C2&b=x%20y&symbol=BTC_USDT"
    expected = hmac.new(b"s", ("k" + "5" + req.query).encode(), hashlib.sha256).hexdigest()
    assert req.headers["Signature"] == expected
    assert parse_qs(req.query)["a"] == ["1,2"]


def test_none_params_are_excluded_from_signature():
    with_none = sign_request("k", "s", "GET", {"a": 1, "b": None}, timestamp_ms=1)
    without = sign_request("k", "s", "GET", {"a": 1}, timestamp_ms=1)
    assert with_none.query == without.query == "a=1"
    assert with_none.headers["Signature"] == without.headers["Signature"]


def test_empty_params_sign_empty_string():
    req = sign_request("k", "s", "GET", None, timestamp_ms=9)
    expected = hmac.new(b"s", b"k9", hashlib.sha256).hexdigest()
    assert req.headers["Signature"] == expected
    assert req.query == ""


def test_post_body_is_compact_json():
    req = sign_request("k", "s", "POST", {"x": [1, 2]}, timestamp_ms=1)
    assert json.loads(req.body) == {"x": [1, 2]}
    assert b" " not in req.body


def test_recv_window_bounds():
    assert sign_request("k", "s", "GET", timestamp_ms=1, recv_window=30).headers["Recv-Window"] == "30"
    with pytest.raises(ValueError):
        sign_request("k", "s", "GET", timestamp_ms=1, recv_window=61)


def test_missing_credentials_rejected():
    with pytest.raises(ValueError):
        sign_request("", "s", "GET")


def test_unsupported_method_rejected():
    with pytest.raises(ValueError):
        sign_request("k", "s", "PUT")


def test_secret_not_in_repr():
    req = sign_request("apikey123", "supersecret", "GET", timestamp_ms=1)
    assert "supersecret" not in repr(req)
