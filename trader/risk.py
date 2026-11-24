"""Risk controls: explicit limits, position sizing, entry checks, kill switch.

Every limit is required. There are no silent defaults, so an operator must
configure exposure and loss limits before the engine will size or approve trades.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .contracts import ContractSpec, floor_to_step


@dataclass(frozen=True)
class RiskLimits:
    max_leverage: int
    max_risk_per_trade_pct: Decimal      # fraction of equity lost if the stop hits
    max_daily_loss_pct: Decimal          # fraction of start-of-day equity
    max_notional_per_position: Decimal   # quote currency
    max_open_positions: int
    max_data_age_ms: int
    max_spread_pct: Decimal

    def __post_init__(self) -> None:
        if self.max_leverage < 1:
            raise ValueError("max_leverage must be >= 1")
        for name in ("max_risk_per_trade_pct", "max_daily_loss_pct"):
            v = getattr(self, name)
            if not (Decimal("0") < v <= Decimal("0.5")):
                raise ValueError(f"{name} must be in (0, 0.5]")
        if self.max_notional_per_position <= 0:
            raise ValueError("max_notional_per_position must be positive")
        if self.max_open_positions < 1:
            raise ValueError("max_open_positions must be >= 1")
        if self.max_data_age_ms <= 0:
            raise ValueError("max_data_age_ms must be positive")
        if self.max_spread_pct <= 0:
            raise ValueError("max_spread_pct must be positive")


@dataclass(frozen=True)
class AccountState:
    equity: Decimal
    available_margin: Decimal
    start_of_day_equity: Decimal
    realized_pnl_today: Decimal
    open_positions: int


@dataclass(frozen=True)
class EntryRequest:
    symbol: str
    vol: Decimal
    entry: Decimal
    stop: Decimal | None
    leverage: int
    side: str  # "long" or "short"


@dataclass(frozen=True)
class Decision:
    approved: bool
    reasons: tuple[str, ...]


class KillSwitch:
    """File-backed emergency stop. Survives restarts until the operator deletes the file."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def engage(self, reason: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(reason + "\n")

    @property
    def engaged(self) -> bool:
        return self._path.exists()


def size_position(
    *,
    spec: ContractSpec,
    equity: Decimal,
    available_margin: Decimal,
    entry: Decimal,
    stop: Decimal,
    leverage: int,
    limits: RiskLimits,
) -> Decimal:
    """Contracts sized so a stop-out loses at most the per-trade risk budget.

    Returns 0 when the risk budget cannot be met at the exchange's minimum order
    size. The function never rounds up past the risk budget.
    """
    if entry <= 0 or stop <= 0 or entry == stop:
        return Decimal("0")
    loss_per_contract = spec.contract_size * abs(entry - stop)
    risk_budget = equity * limits.max_risk_per_trade_pct
    raw = risk_budget / loss_per_contract

    per_contract_notional = spec.contract_size * entry
    cap_notional = limits.max_notional_per_position / per_contract_notional
    cap_margin = available_margin * leverage / per_contract_notional

    vol = floor_to_step(min(raw, cap_notional, cap_margin), spec.vol_unit)
    vol = min(vol, spec.max_vol)
    if vol < spec.min_vol:
        return Decimal("0")
    return vol


class RiskEngine:
    def __init__(self, limits: RiskLimits, kill_switch: KillSwitch) -> None:
        self.limits = limits
        self.kill_switch = kill_switch

    def check_entry(
        self,
        req: EntryRequest,
        spec: ContractSpec,
        state: AccountState,
        *,
        data_age_ms: int,
        spread_pct: Decimal,
    ) -> Decision:
        reasons: list[str] = []
        lim = self.limits

        if self.kill_switch.engaged:
            reasons.append("kill switch engaged")
        if data_age_ms > lim.max_data_age_ms:
            reasons.append(f"market data stale ({data_age_ms} ms > {lim.max_data_age_ms} ms)")
        if spread_pct > lim.max_spread_pct:
            reasons.append(f"spread {spread_pct} above limit {lim.max_spread_pct}")
        if not spec.tradable:
            reasons.append(f"{spec.symbol} not tradable")
        if req.side not in ("long", "short"):
            reasons.append(f"invalid side {req.side!r}")
        if req.stop is None:
            reasons.append("entry rejected: no stop-loss defined")
        if not (spec.min_leverage <= req.leverage <= min(lim.max_leverage, spec.max_leverage)):
            reasons.append(
                f"leverage {req.leverage} outside allowed "
                f"[{spec.min_leverage}, {min(lim.max_leverage, spec.max_leverage)}]"
            )
        if state.open_positions >= lim.max_open_positions:
            reasons.append("max open positions reached")

        daily_floor = state.start_of_day_equity * (Decimal("1") - lim.max_daily_loss_pct)
        if state.equity <= daily_floor or state.realized_pnl_today <= -(
            state.start_of_day_equity * lim.max_daily_loss_pct
        ):
            reasons.append("daily loss limit reached")

        notional = spec.notional(req.vol, req.entry)
        if notional > lim.max_notional_per_position:
            reasons.append(f"notional {notional} exceeds position limit {lim.max_notional_per_position}")
        margin = notional / req.leverage
        if margin > state.available_margin:
            reasons.append(f"required margin {margin} exceeds available {state.available_margin}")
        if req.stop is not None:
            loss = spec.contract_size * req.vol * abs(req.entry - req.stop)
            budget = state.equity * lim.max_risk_per_trade_pct
            if loss > budget:
                reasons.append(f"stop-loss risk {loss} exceeds per-trade budget {budget}")

        return Decision(approved=not reasons, reasons=tuple(reasons))
