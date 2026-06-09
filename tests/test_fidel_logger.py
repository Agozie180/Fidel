from backend.config import Settings
from backend.logger import CompetitionLogger


def test_trade_log_writes_sqlite_and_csv(tmp_path):
    cfg = Settings(database_path=tmp_path / "fidel.sqlite3", csv_path=tmp_path / "trades.csv")
    logger = CompetitionLogger(cfg)
    logger.log_trade(
        {
            "utc_timestamp": "2026-06-22T00:00:00Z",
            "token": "CAKE",
            "direction": "BUY",
            "entry_price": 3,
            "stop_loss": 2.9,
            "take_profit": 3.2,
            "exit_price": None,
            "position_size_usdt": 20,
            "pnl_usdt": 0,
            "pnl_pct": 0,
            "bsc_tx_hash": "0xabc",
            "portfolio_before": 1000,
            "portfolio_after": 1000,
            "running_return_pct": 0,
            "drawdown_pct": 0,
            "signal_confidence": 90,
            "signal_strength": "EXTREME",
            "ai_reasoning_summary": "reason",
            "session_active": "London",
            "cmc_data_snapshot": {"fear_greed": 61},
        }
    )
    assert logger.recent_trades()[0]["bsc_tx_hash"] == "0xabc"
    assert cfg.csv_path.exists()

