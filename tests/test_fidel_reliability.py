"""Tests for the reliability fixes: honest execution mode, resilient data
fallback, BNB SDK crediting, and execution-preview routing."""
from __future__ import annotations

import asyncio

from backend.config import Settings
from backend.executor import BnbAgentCoordinator, TrustWalletExecutor
from backend.judging import build_judging_readiness
from backend.risk import PortfolioState, RiskManager
from backend.signals import Signal, SignalEngine


def _approved_signal() -> Signal:
    return Signal(
        symbol="CAKE",
        direction="BUY",
        confidence=90,
        strength="EXTREME",
        price=3.0,
        stop_loss=2.9,
        take_profit=3.2,
        confluence=["a", "b", "c", "d", "e"],
        session="London",
        session_min_confidence=72,
        reasoning="test",
        cmc_snapshot={"liquidity_score": 90, "change_24h": 1},
        executable=True,
        edge_score=90,
        risk_reward=2.0,
        volatility_pct=1.0,
    )


def test_execution_mode_is_paper_without_full_credentials():
    cfg = Settings(autonomous_live=True, trust_wallet_private_key="", twak_command="twak", pancakeswap_v3_router="")
    assert cfg.execution_mode == "PAPER"
    assert not cfg.live_execution_ready


def test_execution_mode_is_live_only_with_every_credential():
    cfg = Settings(
        autonomous_live=True,
        trust_wallet_private_key="0xabc",
        twak_command="twak",
        pancakeswap_v3_router="0xrouter",
    )
    assert cfg.execution_mode == "LIVE"
    assert cfg.live_execution_ready


def test_paper_swap_returns_labelled_simulated_fill():
    cfg = Settings(autonomous_live=True, strict_live_token_contracts=False)
    executor = TrustWalletExecutor(cfg)
    decision = RiskManager(cfg).evaluate(_approved_signal(), PortfolioState(1000, 1000))
    result = asyncio.run(executor.execute_swap(_approved_signal(), decision, PortfolioState(1000, 1000)))
    assert result.status == "confirmed"
    assert result.mode == "PAPER"
    assert result.tx_hash.startswith("0x")
    assert "PAPER" in result.message


def test_preview_always_carries_route_and_mode():
    cfg = Settings(autonomous_live=False)
    preview = TrustWalletExecutor(cfg).preview_swap(_approved_signal(), RiskManager(cfg).evaluate(_approved_signal(), PortfolioState(1000, 1000)))
    assert preview.route == ["USDT", "CAKE"]
    assert preview.mode == "PAPER"
    assert preview.venue == "PancakeSwap V3 on BSC"


def test_data_fallback_keeps_signals_when_cmc_absent():
    # Live mode, no CMC key, public feed off -> deterministic fallback still trades.
    cfg = Settings(autonomous_live=True, public_price_feed=False, data_fallback_enabled=True)
    signals = asyncio.run(SignalEngine(cfg=cfg).scan())
    assert signals, "fallback data should still produce signals in live mode"


def test_fails_closed_only_when_fallback_disabled():
    cfg = Settings(autonomous_live=True, public_price_feed=False, data_fallback_enabled=False)
    signals = asyncio.run(SignalEngine(cfg=cfg).scan())
    assert signals == [], "with fallback disabled live mode must fail closed (no signals)"


def test_scan_universe_only_contains_eligible_symbols():
    cfg = Settings(scan_universe_csv="CAKE, NOTREAL, ETH")
    universe = SignalEngine(cfg=cfg)._universe()
    assert "CAKE" in universe and "ETH" in universe
    assert "NOTREAL" not in universe


def test_judging_credits_installed_bnb_sdk():
    readiness = build_judging_readiness(
        cfg=Settings(bnb_agent_sdk_command=""),
        registry_status={"contract_ready": 0},
        trade_count=0,
        today_trades=0,
        has_bsc_hashes=False,
        bnb_ready=True,
    )
    assert "BNB AI Agent SDK lifecycle" not in readiness.missing


def test_bnb_coordinator_reports_installed_sdk():
    coordinator = BnbAgentCoordinator(Settings(bnb_agent_sdk_enabled=True, trust_wallet_private_key=""))
    assert coordinator.integration_ready
    message = asyncio.run(coordinator.heartbeat())
    assert "bnbagent" in message.lower()
