"""Public market data for MEXC futures (no credentials required).

Endpoints verified against the live API:
    GET /api/v1/contract/detail   contract specifications
    GET /api/v1/contract/ticker   24h tickers (bid/ask, volume, funding)

Not implemented yet: candlestick endpoint and WebSocket streaming. Their paths
and keepalive rules have not been verified against the official docs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

import httpx

from .contracts import ContractSpec, to_decimal

BASE_URL = "https://contract.mexc.com"


class MarketDataError(Exception):
    pass


class MarketDataClient:
    def __init__(
        self,
        http: httpx.Client | None = None,
        *,
        base_url: str = BASE_URL,
        retries: int = 3,
        backoff_s: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if retries < 1:
            raise ValueError("retries must be >= 1")
        self._http = http or httpx.Client(base_url=base_url, timeout=10.0)
        self._retries = retries
        self._backoff = backoff_s
        self._sleep = sleep

    def _get(self, path: str, params: dict | None = None):
        last_exc: Exception | None = None
        for attempt in range(self._retries):
            try:
                resp = self._http.get(path, params=params)
                resp.raise_for_status()
                body = resp.json()
            except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
                last_exc = exc
                if attempt + 1 < self._retries:
                    self._sleep(self._backoff * (2 ** attempt))
                continue
            if not body.get("success"):
                raise MarketDataError(f"{path} returned error code {body.get('code')}")
            return body["data"]
        raise MarketDataError(f"GET {path} failed after {self._retries} attempts: {last_exc}") from last_exc

    def contracts(self) -> dict[str, ContractSpec]:
        return {
            spec.symbol: spec
            for spec in (ContractSpec.from_api(d) for d in self._get("/api/v1/contract/detail"))
        }

    def tickers(self) -> list[dict]:
        return self._get("/api/v1/contract/ticker")


@dataclass(frozen=True)
class MoverCandidate:
    symbol: str
    change_pct: Decimal      # 24h change as a fraction, e.g. -0.0392
    turnover_usdt: Decimal   # 24h quote volume
    spread_pct: Decimal      # (ask - bid) / mid
    funding_rate: Decimal
    last_price: Decimal


def ticker_age_ms(ticker: dict, now_ms: int) -> int:
    return now_ms - int(ticker["timestamp"])


def is_fresh(ticker: dict, now_ms: int, max_age_ms: int) -> bool:
    return 0 <= ticker_age_ms(ticker, now_ms) <= max_age_ms


def top_movers(
    tickers: list[dict],
    *,
    now_ms: int,
    n: int = 10,
    min_turnover_usdt: Decimal,
    max_spread_pct: Decimal,
    max_age_ms: int,
) -> list[MoverCandidate]:
    """Rank liquid, fresh contracts by absolute 24h change. Filters are applied before ranking."""
    candidates: list[MoverCandidate] = []
    for t in tickers:
        if not is_fresh(t, now_ms, max_age_ms):
            continue
        bid, ask = to_decimal(t.get("bid1", 0)), to_decimal(t.get("ask1", 0))
        if bid <= 0 or ask <= 0 or ask < bid:
            continue
        mid = (bid + ask) / 2
        spread = (ask - bid) / mid
        turnover = to_decimal(t.get("amount24", 0))
        if turnover < min_turnover_usdt or spread > max_spread_pct:
            continue
        candidates.append(
            MoverCandidate(
                symbol=t["symbol"],
                change_pct=to_decimal(t.get("riseFallRate", 0)),
                turnover_usdt=turnover,
                spread_pct=spread,
                funding_rate=to_decimal(t.get("fundingRate", 0)),
                last_price=to_decimal(t.get("lastPrice", mid)),
            )
        )
    candidates.sort(key=lambda c: abs(c.change_pct), reverse=True)
    return candidates[:n]
