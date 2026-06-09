from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .config import Settings, settings
from .signals import Signal
from .tokens import validate_token


@dataclass
class Position:
    symbol: str
    direction: str
    entry_price: float
    current_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    opened_at: str
    tx_hash: str = ""

    @property
    def notional(self) -> float:
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        sign = 1 if self.direction == "BUY" else -1
        return (self.current_price - self.entry_price) * self.quantity * sign


@dataclass
class PortfolioState:
    starting_value: float
    cash_usdt: float
    positions: list[Position] = field(default_factory=list)
    realized_pnl: float = 0.0
    high_watermark: float = 0.0
    consecutive_losses: int = 0
    paused_until: datetime | None = None
    stopped: bool = False
    daily_start_value: float = 0.0
    daily_utc_date: str = ""

    def __post_init__(self) -> None:
        if not self.high_watermark:
            self.high_watermark = self.starting_value
        if not self.daily_start_value:
            self.daily_start_value = self.starting_value

    @property
    def value(self) -> float:
        return self.cash_usdt + sum(p.notional for p in self.positions)

    @property
    def total_pnl(self) -> float:
        return self.value - self.starting_value

    @property
    def drawdown_pct(self) -> float:
        if self.high_watermark <= 0:
            return 0
        return max(0, (self.high_watermark - self.value) / self.high_watermark * 100)

    def mark_to_market(self, prices: dict[str, float]) -> None:
        for position in self.positions:
            if position.symbol in prices:
                position.current_price = prices[position.symbol]
        self.high_watermark = max(self.high_watermark, self.value)


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    position_size_usdt: float = 0.0
    warning: str = ""
    max_slippage_bps: int = 0
    kill_switches: tuple[str, ...] = ()


class RiskManager:
    def __init__(self, cfg: Settings = settings) -> None:
        self.cfg = cfg

    def evaluate(self, signal: Signal, portfolio: PortfolioState, now: datetime | None = None) -> RiskDecision:
        now = now or datetime.now(timezone.utc)
        today = now.date().isoformat()
        if portfolio.daily_utc_date != today:
            portfolio.daily_utc_date = today
            portfolio.daily_start_value = portfolio.value
        validate_token(signal.symbol, require_contract=self.cfg.autonomous_live and self.cfg.strict_live_token_contracts)
        if portfolio.stopped:
            return RiskDecision(False, "agent is stopped by circuit breaker")
        if portfolio.paused_until and portfolio.paused_until > now:
            return RiskDecision(False, f"trading paused until {portfolio.paused_until.isoformat()}")
        if portfolio.value <= 1:
            portfolio.stopped = True
            return RiskDecision(False, "portfolio value is at or below $1 safety floor")
        if portfolio.drawdown_pct >= self.cfg.max_drawdown_pct:
            portfolio.stopped = True
            return RiskDecision(False, "25% hard drawdown cap hit; all trading stopped", warning="HARD_STOP")
        if portfolio.drawdown_pct >= 20:
            return RiskDecision(False, "drawdown is above 20% warning threshold", warning="URGENT_DRAWDOWN")
        daily_loss_pct = max(0, (portfolio.daily_start_value - portfolio.value) / portfolio.daily_start_value * 100)
        if daily_loss_pct >= self.cfg.daily_loss_limit_pct:
            portfolio.paused_until = datetime.combine(now.date(), datetime.max.time(), tzinfo=timezone.utc)
            return RiskDecision(False, "daily loss limit hit; paused for remainder of UTC day", warning="DAILY_LOSS")
        if portfolio.consecutive_losses >= 3:
            portfolio.paused_until = now + timedelta(minutes=30)
            return RiskDecision(False, "3 consecutive losses; pausing 30 minutes", warning="LOSS_STREAK")
        if len(portfolio.positions) >= 3:
            return RiskDecision(False, "maximum 3 open positions already reached")
        if not signal.executable:
            return RiskDecision(False, "signal is not strong enough for autonomous execution")
        liquidity_score = int(signal.cmc_snapshot.get("liquidity_score", 0))
        if liquidity_score < self.cfg.min_liquidity_score:
            return RiskDecision(False, "CMC liquidity score is below execution threshold", warning="LOW_LIQUIDITY")
        change_5m = abs(float(signal.cmc_snapshot.get("change_24h", 0))) / 12
        if change_5m > 10:
            return RiskDecision(False, "extreme market volatility above 10% in 5 minutes", warning="VOLATILITY")
        risk_per_unit = abs(signal.price - signal.stop_loss)
        if risk_per_unit <= 0:
            return RiskDecision(False, "invalid ATR stop distance")
        max_position = portfolio.value * self.cfg.max_position_pct / 100
        volatility_adjusted = min(max_position, portfolio.value * 0.01 / (risk_per_unit / signal.price))
        position_size = max(0, min(max_position, volatility_adjusted, portfolio.cash_usdt - 1.01))
        if position_size <= 0:
            return RiskDecision(False, "insufficient cash after preserving $1 safety floor")
        warning = "APPROACHING_DRAWDOWN" if portfolio.drawdown_pct >= 18 else ""
        kill_switches = (
            "drawdown >= 25%",
            "drawdown warning >= 20%",
            "daily loss >= 5%",
            "3 consecutive losses",
            "CMC feed unavailable",
            "BSC/TWAK execution failure",
            "volatility shock > 10% in 5m",
            "portfolio <= $1",
        )
        return RiskDecision(True, "risk checks passed", round(position_size, 2), warning, self.cfg.max_slippage_bps, kill_switches)
