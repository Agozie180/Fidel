from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


COMPETITION_CONTRACT = "0x212c61b9b72c95d95bf29cf032f5e5635629aed5"


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    cmc_api_key: str = os.getenv("CMC_API_KEY", "")
    trust_wallet_private_key: str = os.getenv("TRUST_WALLET_PRIVATE_KEY", "")
    bsc_rpc_url: str = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    pancakeswap_v3_router: str = os.getenv("PANCAKESWAP_V3_ROUTER", "")
    pancakeswap_perps_contract: str = os.getenv("PANCAKESWAP_PERPS_CONTRACT", "")
    competition_contract_address: str = os.getenv("COMPETITION_CONTRACT_ADDRESS", COMPETITION_CONTRACT)
    max_drawdown_pct: float = _float("MAX_DRAWDOWN_PCT", 25)
    daily_loss_limit_pct: float = _float("DAILY_LOSS_LIMIT_PCT", 5)
    max_position_pct: float = _float("MAX_POSITION_PCT", 2)
    max_slippage_bps: int = _int("MAX_SLIPPAGE_BPS", 60)
    min_liquidity_score: int = _int("MIN_LIQUIDITY_SCORE", 70)
    max_gas_usdt: float = _float("MAX_GAS_USDT", 3)
    min_signal_confidence: int = _int("MIN_SIGNAL_CONFIDENCE", 70)
    trade_interval_seconds: int = _int("TRADE_INTERVAL_SECONDS", 60)
    agent_wallet_address: str = os.getenv("AGENT_WALLET_ADDRESS", "")
    cmc_mcp_command: str = os.getenv("CMC_MCP_COMMAND", "")
    twak_command: str = os.getenv("TWAK_COMMAND", "twak")
    bnb_agent_sdk_command: str = os.getenv("BNB_AGENT_SDK_COMMAND", "")
    autonomous_live: bool = os.getenv("AUTONOMOUS_LIVE", "false").lower() == "true"
    strict_live_token_contracts: bool = os.getenv("STRICT_LIVE_TOKEN_CONTRACTS", "true").lower() == "true"
    eligible_token_registry_path: Path = Path(os.getenv("ELIGIBLE_TOKEN_REGISTRY_PATH", "config/eligible_tokens.json"))
    initial_portfolio_usdt: float = _float("INITIAL_PORTFOLIO_USDT", 1000)
    database_path: Path = Path(os.getenv("DATABASE_PATH", "data/fidel.sqlite3"))
    csv_path: Path = Path(os.getenv("CSV_PATH", "data/fidel_trades.csv"))
    state_path: Path = Path(os.getenv("STATE_PATH", "data/agent_state.json"))
    competition_registration_deadline: str = os.getenv("COMPETITION_REGISTRATION_DEADLINE", "2026-06-21T23:59:59Z")
    competition_trading_start: str = os.getenv("COMPETITION_TRADING_START", "2026-06-22T00:00:00Z")
    competition_trading_end: str = os.getenv("COMPETITION_TRADING_END", "2026-06-28T23:59:59Z")
    # --- Reliability / deployment ---
    auto_start: bool = _bool("AUTO_START", True)
    bnb_agent_sdk_enabled: bool = _bool("BNB_AGENT_SDK_ENABLED", True)
    data_fallback_enabled: bool = _bool("DATA_FALLBACK_ENABLED", True)
    public_price_feed: bool = _bool("PUBLIC_PRICE_FEED", True)
    scan_concurrency: int = _int("SCAN_CONCURRENCY", 6)
    scan_universe_csv: str = os.getenv("SCAN_UNIVERSE", "")
    min_risk_reward: float = _float("MIN_RISK_REWARD", 1.8)
    bsc_chain: str = os.getenv("BNB_NETWORK", "bsc")

    @property
    def llm_available(self) -> bool:
        return bool(self.anthropic_api_key or self.openai_api_key)

    @property
    def live_execution_ready(self) -> bool:
        """True only when every credential for a real on-chain swap is present."""
        return bool(
            self.autonomous_live
            and self.trust_wallet_private_key
            and self.twak_command
            and self.pancakeswap_v3_router
        )

    @property
    def execution_mode(self) -> str:
        return "LIVE" if self.live_execution_ready else "PAPER"


settings = Settings()
