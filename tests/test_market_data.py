from decimal import Decimal

import httpx
import pytest

from trader.market_data import MarketDataClient, MarketDataError, is_fresh, top_movers

NOW = 1_800_000_000_000


def ticker(sym, change, amount=1_000_000, bid="100", ask="100.01", ts=NOW):
    return {"symbol": sym, "riseFallRate": change, "amount24": amount, "bid1": bid, "ask1": ask,
            "lastPrice": bid, "fundingRate": 0.0001, "timestamp": ts}


def make_client(responses):
    """responses: list of callables or (status, json) tuples, consumed in order."""
    it = iter(responses)

    def handler(request):
        item = next(it)
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body)

    sleeps = []
    client = MarketDataClient(httpx.Client(base_url="https://contract.mexc.com",
                                           transport=httpx.MockTransport(handler)),
                              backoff_s=0.1, sleep=sleeps.append)
    return client, sleeps


# ---- connection recovery ---------------------------------------------------

def test_recovers_after_transport_errors_with_backoff():
    ok = (200, {"success": True, "code": 0, "data": [{"symbol": "BTC_USDT"}]})
    client, sleeps = make_client([httpx.ConnectError("down"), httpx.ConnectError("down"), ok])
    assert client.tickers() == [{"symbol": "BTC_USDT"}]
    assert sleeps == [0.1, 0.2]


def test_gives_up_after_retries_and_raises():
    err = httpx.ConnectError("down")
    client, sleeps = make_client([err, err, err])
    with pytest.raises(MarketDataError, match="failed after 3 attempts"):
        client.tickers()
    assert len(sleeps) == 2


def test_server_error_status_is_retried():
    ok = (200, {"success": True, "code": 0, "data": []})
    client, _ = make_client([(503, {}), ok])
    assert client.tickers() == []


def test_api_error_code_not_retried():
    client, sleeps = make_client([(200, {"success": False, "code": 1002, "data": None})])
    with pytest.raises(MarketDataError, match="1002"):
        client.tickers()
    assert sleeps == []


def test_contract_parsing_through_client():
    body = {"success": True, "code": 0, "data": [{
        "symbol": "BTC_USDT", "state": 0, "apiAllowed": True, "priceUnit": 0.1, "volUnit": 1,
        "minVol": 1, "maxVol": 400000, "contractSize": 0.0001, "minLeverage": 1, "maxLeverage": 500}]}
    client, _ = make_client([(200, body)])
    specs = client.contracts()
    assert specs["BTC_USDT"].contract_size == Decimal("0.0001")


# ---- scanning and freshness ------------------------------------------------

def test_freshness_window():
    assert is_fresh(ticker("A", 0, ts=NOW - 1000), NOW, 5000)
    assert not is_fresh(ticker("A", 0, ts=NOW - 9000), NOW, 5000)
    assert not is_fresh(ticker("A", 0, ts=NOW + 10_000), NOW, 5000)  # clock skew treated as untrusted


def test_top_movers_ranks_by_absolute_change_and_filters_illiquid_and_stale():
    tickers = [
        ticker("BIG_UP", 0.12),
        ticker("BIG_DOWN", -0.20),
        ticker("ILLIQUID", 0.50, amount=10),
        ticker("STALE", 0.90, ts=NOW - 60_000),
        ticker("WIDE", 0.80, bid="100", ask="105"),
        ticker("SMALL", 0.01),
    ]
    movers = top_movers(tickers, now_ms=NOW, n=10, min_turnover_usdt=Decimal("1000"),
                        max_spread_pct=Decimal("0.001"), max_age_ms=5000)
    assert [m.symbol for m in movers] == ["BIG_DOWN", "BIG_UP", "SMALL"]


def test_top_movers_skips_crossed_or_missing_quotes():
    tickers = [ticker("CROSSED", 0.3, bid="101", ask="100"), ticker("NOQUOTE", 0.3, bid="0", ask="0")]
    assert top_movers(tickers, now_ms=NOW, min_turnover_usdt=Decimal("1"),
                      max_spread_pct=Decimal("1"), max_age_ms=5000) == []


def test_top_movers_limit():
    tickers = [ticker(f"S{i}", i / 100) for i in range(1, 20)]
    movers = top_movers(tickers, now_ms=NOW, n=10, min_turnover_usdt=Decimal("1"),
                        max_spread_pct=Decimal("1"), max_age_ms=5000)
    assert len(movers) == 10
