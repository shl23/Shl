"""Runtime configuration for MEXC trading, loaded from environment variables and .env.

Nothing is read or validated at import time. Call load_config() explicitly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

VALID_TRADING_MODES = frozenset({"paper", "live"})
VALID_LIVE_FLAGS = frozenset({"true", "false"})
PLACEHOLDER_PREFIXES = ("your_", "changeme", "xxxx")


@dataclass(frozen=True)
class Config:
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
    trading_mode: str
    live_trading: bool


def _read(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _check_credential(name: str, value: str) -> str:
    if not value:
        raise RuntimeError(f"{name} is missing.")
    if value.lower().startswith(PLACEHOLDER_PREFIXES):
        raise RuntimeError(f"{name} looks like a placeholder value, not a real credential.")
    return value


def load_config() -> Config:
    # Real environment variables take precedence over values in .env.
    load_dotenv(override=False)

    api_key = _check_credential("MEXC_API_KEY", _read("MEXC_API_KEY"))
    api_secret = _check_credential("MEXC_API_SECRET", _read("MEXC_API_SECRET"))

    trading_mode = _read("TRADING_MODE", "paper").lower()
    if trading_mode not in VALID_TRADING_MODES:
        raise RuntimeError(
            f"Invalid TRADING_MODE {trading_mode!r}; expected one of {sorted(VALID_TRADING_MODES)}."
        )

    live_flag = _read("LIVE_TRADING", "false").lower()
    if live_flag not in VALID_LIVE_FLAGS:
        raise RuntimeError(f"Invalid LIVE_TRADING {live_flag!r}; expected 'true' or 'false'.")
    live_trading = live_flag == "true"

    # Two flags control live trading. Refuse contradictory settings rather than guess.
    if (trading_mode == "live") != live_trading:
        raise RuntimeError(
            f"TRADING_MODE={trading_mode!r} and LIVE_TRADING={live_flag!r} disagree. "
            "Set both for paper trading (paper/false) or live trading (live/true)."
        )

    return Config(
        api_key=api_key,
        api_secret=api_secret,
        trading_mode=trading_mode,
        live_trading=live_trading,
    )
