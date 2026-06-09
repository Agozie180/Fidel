from datetime import datetime, timezone

import pytest

from backend.signals import CmcSnapshot, SignalEngine, current_session, validate_token


def test_token_validator_rejects_unlisted_token():
    with pytest.raises(ValueError):
        validate_token("NOTREAL")


def test_token_validator_accepts_eligible_token():
    assert validate_token("cake") == "CAKE"


def test_session_confidence_schedule():
    assert current_session(datetime(2026, 6, 22, 1, tzinfo=timezone.utc)).minimum_confidence == 65
    assert current_session(datetime(2026, 6, 22, 8, tzinfo=timezone.utc)).minimum_confidence == 72
    assert current_session(datetime(2026, 6, 22, 15, tzinfo=timezone.utc)).minimum_confidence == 75
    assert current_session(datetime(2026, 6, 22, 22, tzinfo=timezone.utc)).minimum_confidence == 60


def test_signal_requires_four_confluences_and_strong_for_execution():
    snap = CmcSnapshot(
        symbol="CAKE",
        price=3.0,
        change_24h=4.0,
        rsi={"5m": 58, "1h": 62, "4h": 64, "24h": 60},
        macd="bullish_crossover",
        ema_9=3.05,
        ema_21=2.95,
        bollinger_middle=2.9,
        atr=0.05,
        funding_rate=0.001,
        fear_greed=61,
        news_sentiment=72,
        social_sentiment=70,
        liquidity_score=90,
        open_interest_change=2,
        market_regime="risk-on trend",
    )
    signal = SignalEngine().build_signal(snap)
    assert signal.direction == "BUY"
    assert len(signal.confluence) >= 4
    assert signal.strength in {"STRONG", "EXTREME"}
    assert signal.take_profit > signal.price > signal.stop_loss

