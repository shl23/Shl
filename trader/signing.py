"""Request signing for MEXC futures private endpoints (HMAC-SHA256).

Signature scheme (per MEXC futures integration guide):
    target    = accessKey + requestTime(ms, string) + parameterString
    Signature = hex(HMAC_SHA256(secretKey, target))
    GET/DELETE: parameterString = sorted key=value pairs joined by '&', values URL-encoded.
    POST:       parameterString = the exact JSON body string (not re-sorted).

Secrets are never logged or returned in reprs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from urllib.parse import quote


@dataclass(frozen=True)
class SignedRequest:
    headers: dict[str, str] = field(repr=False)
    query: str            # exact query string to send (GET/DELETE), else ""
    body: bytes | None    # exact JSON body to send (POST), else None


def _clean(params: dict | None) -> dict:
    return {k: v for k, v in (params or {}).items() if v is not None}


def _query_string(params: dict) -> str:
    return "&".join(f"{k}={quote(str(params[k]), safe='')}" for k in sorted(params))


def sign_request(
    api_key: str,
    api_secret: str,
    method: str,
    params: dict | None = None,
    *,
    timestamp_ms: int | None = None,
    recv_window: int | None = None,
) -> SignedRequest:
    if not api_key or not api_secret:
        raise ValueError("api_key and api_secret are required for signed requests")

    method = method.upper()
    clean = _clean(params)
    ts = str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000))

    if method in ("GET", "DELETE"):
        query = _query_string(clean)
        body = None
        param_string = query
    elif method == "POST":
        query = ""
        body = json.dumps(clean, separators=(",", ":")).encode() if clean else b""
        param_string = body.decode()
    else:
        raise ValueError(f"unsupported method: {method}")

    target = f"{api_key}{ts}{param_string}"
    signature = hmac.new(api_secret.encode(), target.encode(), hashlib.sha256).hexdigest()

    headers = {
        "ApiKey": api_key,
        "Request-Time": ts,
        "Signature": signature,
        "Content-Type": "application/json",
    }
    if recv_window is not None:
        if not 1 <= recv_window <= 60:
            raise ValueError("recv_window must be between 1 and 60 ms")
        headers["Recv-Window"] = str(recv_window)

    return SignedRequest(headers=headers, query=query, body=body)
