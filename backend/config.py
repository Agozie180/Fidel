from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


COMPETITION_CONTRACT = "0x212c61b9b72c95d95bf29cf032f5e5635629aed5"


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


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
    competition_registration_deadline: str = os.getenv("COMPETITION_REGISTRATION_DEADLINE", "2026-06-21T23:59:59Z")
    competition_trading_start: str = os.getenv("COMPETITION_TRADING_START", "2026-06-22T00:00:00Z")
    competition_trading_end: str = os.getenv("COMPETITION_TRADING_END", "2026-06-28T23:59:59Z")

    @property
    def llm_available(self) -> bool:
        return bool(self.anthropic_api_key or self.openai_api_key)


settings = Settings()
