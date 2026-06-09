from datetime import datetime, timezone

from backend.config import Settings
from backend.risk import PortfolioState, RiskManager
from backend.signals import Signal


def _signal(**overrides):
    data = dict(
        symbol="CAKE",
        direction="BUY",
        confidence=90,
        strength="EXTREME",
        price=3.0,
        stop_loss=2.9,
        take_profit=3.2,
        confluence=["a", "b", "c", "d"],
        session="London",
        session_min_confidence=72,
        reasoning="test",
        cmc_snapshot={"change_24h": 1, "liquidity_score": 90},
        executable=True,
    )
    data.update(overrides)
    return Signal(**data)


def test_risk_caps_position_at_two_percent():
    cfg = Settings(max_position_pct=2)
    portfolio = PortfolioState(1000, 1000)
    decision = RiskManager(cfg).evaluate(_signal(), portfolio)
    assert decision.approved
    assert decision.position_size_usdt <= 20


def test_hard_drawdown_stops_agent():
    portfolio = PortfolioState(1000, 740, high_watermark=1000)
    decision = RiskManager().evaluate(_signal(), portfolio)
    assert not decision.approved
    assert portfolio.stopped


def test_rejects_non_executable_signal():
    portfolio = PortfolioState(1000, 1000)
    decision = RiskManager().evaluate(_signal(executable=False, strength="MODERATE"), portfolio)
    assert not decision.approved


def test_daily_loss_limit_pauses_trading():
    portfolio = PortfolioState(1000, 949, daily_start_value=1000, daily_utc_date="2026-06-22")
    decision = RiskManager().evaluate(_signal(), portfolio, now=datetime(2026, 6, 22, 12, tzinfo=timezone.utc))
    assert not decision.approved
    assert decision.warning == "DAILY_LOSS"
