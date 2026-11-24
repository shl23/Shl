"""Live trading gate. Every condition must pass before live execution can be enabled.

The gate reports every failing condition. It never enables live trading by
default. The operator sets LIVE_AUTHORIZED_UNTIL themselves, and the runtime
must pass verified checks (key test, eligibility) in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

KEY_LIFETIME_DAYS = 90   # MEXC: keys not bound to an IP are valid for 90 days
RENEWAL_WINDOW_DAYS = 5  # MEXC: renewal is available 5 days before expiry


@dataclass(frozen=True)
class GateInputs:
    trading_mode: str
    live_trading_flag: bool
    authorized_until: str | None    # ISO-8601 with timezone, set by the operator
    key_verified: bool              # a signed private call succeeded
    eligibility_verified: bool      # the account is confirmed eligible for futures API trading
    limits_configured: bool
    kill_switch_engaged: bool
    key_created_at: str | None      # ISO-8601, operator-provided


def live_gate(inputs: GateInputs, now: datetime | None = None) -> list[str]:
    """Return failure reasons. An empty list means live execution may be enabled."""
    now = now or datetime.now(timezone.utc)
    failures: list[str] = []

    if inputs.trading_mode != "live":
        failures.append("TRADING_MODE is not 'live'")
    if not inputs.live_trading_flag:
        failures.append("LIVE_TRADING is not true")
    if inputs.kill_switch_engaged:
        failures.append("kill switch is engaged")
    if not inputs.limits_configured:
        failures.append("risk limits are not configured")
    if not inputs.key_verified:
        failures.append("API key has not passed a signed test call")
    if not inputs.eligibility_verified:
        failures.append("account eligibility is not verified")

    try:
        until = datetime.fromisoformat(inputs.authorized_until) if inputs.authorized_until else None
    except ValueError:
        until = None
    if until is None or until.tzinfo is None:
        failures.append("operator authorization missing or lacks a timezone (LIVE_AUTHORIZED_UNTIL)")
    elif until <= now:
        failures.append("operator authorization has expired")

    if inputs.key_created_at:
        try:
            created = datetime.fromisoformat(inputs.key_created_at)
            if created.tzinfo is None:
                raise ValueError
            if key_days_remaining(created, now) <= 0:
                failures.append("API key has expired; create a new key")
        except ValueError:
            failures.append("KEY_CREATED_AT is not a valid timezone-aware ISO-8601 timestamp")
    else:
        failures.append("KEY_CREATED_AT not set, so key expiry cannot be tracked")

    return failures


def key_days_remaining(created_at: datetime, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    expires = created_at + timedelta(days=KEY_LIFETIME_DAYS)
    return (expires - now).days


def key_renewal_due(created_at: datetime, now: datetime | None = None) -> bool:
    return key_days_remaining(created_at, now) <= RENEWAL_WINDOW_DAYS


def kill_switch_path_default() -> Path:
    return Path("/opt/mexc-trader/state/KILL_SWITCH")
