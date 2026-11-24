from decimal import Decimal

import pytest

from trader.contracts import ContractSpec
from trader.risk import AccountState, EntryRequest, KillSwitch, RiskEngine, RiskLimits, size_position

BTC = ContractSpec(
    symbol="BTC_USDT", tradable=True, price_unit=Decimal("0.1"), vol_unit=Decimal("1"),
    min_vol=Decimal("1"), max_vol=Decimal("400000"), contract_size=Decimal("0.0001"),
    min_leverage=1, max_leverage=500,
)


def limits(**over):
    base = dict(
        max_leverage=5,
        max_risk_per_trade_pct=Decimal("0.01"),
        max_daily_loss_pct=Decimal("0.05"),
        max_notional_per_position=Decimal("1000"),
        max_open_positions=2,
        max_data_age_ms=5000,
        max_spread_pct=Decimal("0.001"),
    )
    base.update(over)
    return RiskLimits(**base)


def state(**over):
    base = dict(
        equity=Decimal("1000"), available_margin=Decimal("1000"),
        start_of_day_equity=Decimal("1000"), realized_pnl_today=Decimal("0"), open_positions=0,
    )
    base.update(over)
    return AccountState(**base)


def engine(tmp_path, **lim):
    return RiskEngine(limits(**lim), KillSwitch(tmp_path / "KILL"))


def req(**over):
    base = dict(symbol="BTC_USDT", vol=Decimal("1"), entry=Decimal("60000"),
                stop=Decimal("59000"), leverage=5, side="long")
    base.update(over)
    return EntryRequest(**base)


# ---- limits must be explicit and sane -------------------------------------

def test_limits_have_no_silent_defaults():
    with pytest.raises(TypeError):
        RiskLimits()  # type: ignore[call-arg]


@pytest.mark.parametrize("over", [
    dict(max_risk_per_trade_pct=Decimal("0")),
    dict(max_risk_per_trade_pct=Decimal("0.9")),
    dict(max_leverage=0),
    dict(max_notional_per_position=Decimal("-1")),
    dict(max_open_positions=0),
])
def test_invalid_limits_rejected(over):
    with pytest.raises(ValueError):
        limits(**over)


# ---- sizing ----------------------------------------------------------------

def test_size_respects_risk_budget_and_never_exceeds_it():
    vol = size_position(spec=BTC, equity=Decimal("1000"), available_margin=Decimal("1000"),
                        entry=Decimal("60000"), stop=Decimal("59000"), leverage=5, limits=limits())
    # Budget 10 USDT; loss per contract = 0.0001 * 1000 = 0.1 -> 100 contracts.
    assert vol == Decimal("100")
    assert BTC.contract_size * vol * Decimal("1000") <= Decimal("10")


def test_size_capped_by_notional_limit():
    vol = size_position(spec=BTC, equity=Decimal("100000"), available_margin=Decimal("100000"),
                        entry=Decimal("60000"), stop=Decimal("59900"), leverage=5,
                        limits=limits(max_notional_per_position=Decimal("600")))
    assert BTC.notional(vol, Decimal("60000")) <= Decimal("600")


def test_size_capped_by_margin():
    vol = size_position(spec=BTC, equity=Decimal("100000"), available_margin=Decimal("10"),
                        entry=Decimal("60000"), stop=Decimal("59900"), leverage=5,
                        limits=limits(max_notional_per_position=Decimal("100000")))
    assert BTC.notional(vol, Decimal("60000")) / 5 <= Decimal("10")


def test_tiny_account_cannot_meet_risk_at_minimum_size_returns_zero():
    # $2 equity, 1% risk = $0.02. A 1-contract BTC trade with a 1000-point stop loses 0.1 per 1 contract.
    vol = size_position(spec=BTC, equity=Decimal("2"), available_margin=Decimal("2"),
                        entry=Decimal("60000"), stop=Decimal("59000"), leverage=5, limits=limits())
    assert vol == 0


def test_zero_or_invalid_stop_yields_zero():
    assert size_position(spec=BTC, equity=Decimal("1000"), available_margin=Decimal("1000"),
                         entry=Decimal("60000"), stop=Decimal("60000"), leverage=5,
                         limits=limits()) == 0


# ---- entry checks ----------------------------------------------------------

def test_clean_entry_approved(tmp_path):
    d = engine(tmp_path).check_entry(req(vol=Decimal("10")), BTC, state(),
                                     data_age_ms=100, spread_pct=Decimal("0.0001"))
    assert d.approved, d.reasons


def test_entry_without_stop_rejected(tmp_path):
    d = engine(tmp_path).check_entry(req(stop=None), BTC, state(),
                                     data_age_ms=100, spread_pct=Decimal("0.0001"))
    assert not d.approved and any("no stop-loss" in r for r in d.reasons)


def test_stale_data_blocks_entry(tmp_path):
    d = engine(tmp_path).check_entry(req(), BTC, state(), data_age_ms=9000, spread_pct=Decimal("0"))
    assert any("stale" in r for r in d.reasons)


def test_wide_spread_blocks_entry(tmp_path):
    d = engine(tmp_path).check_entry(req(), BTC, state(), data_age_ms=1, spread_pct=Decimal("0.01"))
    assert any("spread" in r for r in d.reasons)


def test_kill_switch_blocks_everything(tmp_path):
    eng = engine(tmp_path)
    eng.kill_switch.engage("manual test")
    d = eng.check_entry(req(), BTC, state(), data_age_ms=1, spread_pct=Decimal("0"))
    assert not d.approved and any("kill switch" in r for r in d.reasons)


def test_kill_switch_persists_as_file(tmp_path):
    KillSwitch(tmp_path / "KILL").engage("x")
    assert KillSwitch(tmp_path / "KILL").engaged  # a new instance still sees it


def test_leverage_above_limit_rejected(tmp_path):
    d = engine(tmp_path, max_leverage=3).check_entry(req(leverage=5), BTC, state(),
                                                     data_age_ms=1, spread_pct=Decimal("0"))
    assert any("leverage" in r for r in d.reasons)


def test_leverage_is_never_raised_to_reach_target(tmp_path):
    # Leverage is capped by the risk limit even when the exchange allows more.
    d = engine(tmp_path, max_leverage=2).check_entry(req(leverage=500), BTC, state(),
                                                     data_age_ms=1, spread_pct=Decimal("0"))
    assert not d.approved


def test_max_open_positions_enforced(tmp_path):
    d = engine(tmp_path).check_entry(req(), BTC, state(open_positions=2),
                                     data_age_ms=1, spread_pct=Decimal("0"))
    assert any("max open positions" in r for r in d.reasons)


def test_daily_loss_limit_blocks_entry(tmp_path):
    d = engine(tmp_path).check_entry(req(), BTC, state(realized_pnl_today=Decimal("-60")),
                                     data_age_ms=1, spread_pct=Decimal("0"))
    assert any("daily loss" in r for r in d.reasons)


def test_margin_shortfall_rejected(tmp_path):
    d = engine(tmp_path, max_notional_per_position=Decimal("100000")).check_entry(
        req(vol=Decimal("100")), BTC, state(available_margin=Decimal("1")),
        data_age_ms=1, spread_pct=Decimal("0"))
    assert any("margin" in r for r in d.reasons)


def test_stop_risk_over_budget_rejected(tmp_path):
    # 100 contracts with a 1000-point stop risks 10 USDT on a 1000 USDT account at 1% = 10 -> ok at 100,
    # but 200 contracts exceeds the budget.
    d = engine(tmp_path, max_notional_per_position=Decimal("100000")).check_entry(
        req(vol=Decimal("200")), BTC, state(), data_age_ms=1, spread_pct=Decimal("0"))
    assert any("per-trade budget" in r for r in d.reasons)
