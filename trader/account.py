"""Read-only account balance for MEXC futures.

Endpoint (per MEXC futures docs): GET /api/v1/private/account/assets
Requires the "View Account Details" permission on the API key. No parameters.
Places no orders.

    python -m trader.account        # reads MEXC_API_KEY / MEXC_API_SECRET from env
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from decimal import Decimal

import httpx

from .contracts import to_decimal
from .signing import sign_request

BASE_URL = "https://api.mexc.com"
ASSETS_PATH = "/api/v1/private/account/assets"


class AccountError(Exception):
    pass


@dataclass(frozen=True)
class AssetBalance:
    currency: str
    available: Decimal
    equity: Decimal
    unrealized: Decimal


def parse_assets(payload: dict) -> dict[str, AssetBalance]:
    if not payload.get("success"):
        raise AccountError(f"exchange returned error code {payload.get('code')}")
    out: dict[str, AssetBalance] = {}
    for row in payload.get("data") or []:
        bal = AssetBalance(
            currency=str(row["currency"]),
            available=to_decimal(row.get("availableBalance", 0)),
            equity=to_decimal(row.get("equity", 0)),
            unrealized=to_decimal(row.get("unrealized", 0)),
        )
        out[bal.currency] = bal
    return out


class AccountClient:
    def __init__(self, api_key: str, api_secret: str, http: httpx.Client | None = None) -> None:
        self._key = api_key
        self._secret = api_secret
        self._http = http or httpx.Client(base_url=BASE_URL, timeout=10.0)

    def assets(self) -> dict[str, AssetBalance]:
        signed = sign_request(self._key, self._secret, "GET", None)
        url = ASSETS_PATH + (f"?{signed.query}" if signed.query else "")
        resp = self._http.get(url, headers=signed.headers)
        resp.raise_for_status()
        return parse_assets(resp.json())


def main() -> int:
    key, secret = os.getenv("MEXC_API_KEY", "").strip(), os.getenv("MEXC_API_SECRET", "").strip()
    if not key or not secret:
        print("MEXC_API_KEY and MEXC_API_SECRET must be set in the environment.", file=sys.stderr)
        return 2
    try:
        balances = AccountClient(key, secret).assets()
    except (AccountError, httpx.HTTPError) as exc:
        # Error text is printed without the request, so secrets are not included.
        print(f"balance check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for bal in balances.values():
        if bal.equity or bal.available:
            print(f"{bal.currency}: equity={bal.equity} available={bal.available} unrealized={bal.unrealized}")
    if not balances:
        print("no asset rows returned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
