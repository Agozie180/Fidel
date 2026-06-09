from backend.executor import TrustWalletExecutor
from backend.risk import RiskDecision
from backend.signals import Signal


def test_execution_preflight_blocks_excessive_slippage():
    signal = Signal(
        symbol="CAKE",
        direction="BUY",
        confidence=90,
        strength="EXTREME",
        price=3,
        stop_loss=2.9,
        take_profit=3.2,
        confluence=["a", "b", "c", "d", "e"],
        session="London",
        session_min_confidence=72,
        reasoning="test",
        cmc_snapshot={"liquidity_score": 10},
        executable=True,
        edge_score=90,
        volatility_pct=8,
    )
    preview = TrustWalletExecutor().preview_swap(signal, RiskDecision(True, "ok", 20, max_slippage_bps=60))
    assert not preview.approved
    assert preview.warnings

