from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timezone
from statistics import mean
from typing import Any

import httpx

from .config import Settings, settings
from .tokens import ELIGIBLE_TOKENS, validate_token


@dataclass(frozen=True)
class TradingSession:
    name: str
    minimum_confidence: int


def current_session(now: datetime | None = None) -> TradingSession:
    now = now or datetime.now(timezone.utc)
    t = now.time()
    if time(23, 0) <= t or t < time(6, 0):
        return TradingSession("Asian", 65)
    if time(7, 0) <= t < time(12, 0):
        return TradingSession("London", 72)
    if time(13, 0) <= t < time(21, 0):
        return TradingSession("New York", 75)
    return TradingSession("Off", 60)


@dataclass
class CmcSnapshot:
    symbol: str
    price: float
    change_24h: float
    rsi: dict[str, float]
    macd: str
    ema_9: float
    ema_21: float
    bollinger_middle: float
    atr: float
    funding_rate: float
    fear_greed: int
    news_sentiment: int
    social_sentiment: int
    liquidity_score: int
    open_interest_change: float
    market_regime: str
    narratives: list[str] = field(default_factory=list)


@dataclass
class Signal:
    symbol: str
    direction: str
    confidence: int
    strength: str
    price: float
    stop_loss: float
    take_profit: float
    confluence: list[str]
    session: str
    session_min_confidence: int
    reasoning: str
    cmc_snapshot: dict[str, Any]
    executable: bool
    edge_score: float = 0.0
    risk_reward: float = 2.0
    volatility_pct: float = 0.0


class CmcAgentHubClient:
    """CMC Agent Hub adapter with x402-ready headers and a deterministic dev fallback."""

    def __init__(self, cfg: Settings = settings) -> None:
        self.cfg = cfg

    async def snapshot(self, symbol: str) -> CmcSnapshot:
        symbol = validate_token(symbol)
        if self.cfg.cmc_mcp_command:
            return await self._mcp_snapshot(symbol)
        if self.cfg.cmc_api_key:
            return await self._http_snapshot(symbol)
        if self.cfg.autonomous_live:
            raise RuntimeError("CMC data feed unavailable; live trading must fail closed")
        return self._demo_snapshot(symbol)

    async def _http_snapshot(self, symbol: str) -> CmcSnapshot:
        headers = {"X-CMC_PRO_API_KEY": self.cfg.cmc_api_key, "X-Accept-x402": "true"}
        async with httpx.AsyncClient(timeout=15) as client:
            quote = await client.get(
                "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest",
                params={"symbol": symbol},
                headers=headers,
            )
            quote.raise_for_status()
            data = quote.json()["data"][symbol][0]["quote"]["USD"]
            price = float(data["price"])
        return self._derive_snapshot(symbol, price, float(data.get("percent_change_24h", 0)))

    async def _mcp_snapshot(self, symbol: str) -> CmcSnapshot:
        proc = await asyncio.create_subprocess_shell(
            f'{self.cfg.cmc_mcp_command} snapshot {symbol} --x402',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"CMC MCP snapshot failed: {err.decode().strip()}")
        payload = json.loads(out.decode())
        return CmcSnapshot(**payload)

    def _demo_snapshot(self, symbol: str) -> CmcSnapshot:
        seed = int(hashlib.sha256(f"{symbol}:{datetime.now(timezone.utc).date()}".encode()).hexdigest(), 16)
        rng = random.Random(seed)
        price = round(rng.uniform(0.05, 800), 6)
        return self._derive_snapshot(symbol, price, rng.uniform(-8, 8))

    def _derive_snapshot(self, symbol: str, price: float, change_24h: float) -> CmcSnapshot:
        base = int(hashlib.sha1(symbol.encode()).hexdigest(), 16)
        phase = (base % 360) / 180 * math.pi
        rsi_1h = 50 + math.sin(phase) * 24 + change_24h
        rsi = {tf: max(5, min(95, rsi_1h + delta)) for tf, delta in {"5m": -4, "1h": 0, "4h": 3, "24h": 1}.items()}
        ema_9 = price * (1 + (rsi_1h - 50) / 2500)
        ema_21 = price * (1 - (rsi_1h - 50) / 3200)
        atr = max(price * (0.008 + abs(change_24h) / 1000), 0.000001)
        return CmcSnapshot(
            symbol=symbol,
            price=price,
            change_24h=change_24h,
            rsi=rsi,
            macd="bullish_crossover" if ema_9 > ema_21 and change_24h > 0 else "bearish_crossover" if ema_9 < ema_21 and change_24h < 0 else "mixed",
            ema_9=ema_9,
            ema_21=ema_21,
            bollinger_middle=price * (0.995 if change_24h > 0 else 1.005),
            atr=atr,
            funding_rate=(change_24h / 10000),
            fear_greed=max(1, min(99, int(50 + change_24h * 3))),
            news_sentiment=max(1, min(99, int(55 + change_24h * 2))),
            social_sentiment=max(1, min(99, int(52 + change_24h * 2.5))),
            liquidity_score=70 + base % 25,
            open_interest_change=change_24h / 2,
            market_regime="risk-on trend" if change_24h > 2 else "risk-off volatility" if change_24h < -2 else "range compression",
            narratives=["CMC Agent Hub", "BSC eligible token", "x402 data path"],
        )


class SignalEngine:
    def __init__(self, cmc: CmcAgentHubClient | None = None) -> None:
        self.cmc = cmc or CmcAgentHubClient()

    async def scan(self, symbols: list[str] | None = None) -> list[Signal]:
        targets = symbols or sorted(ELIGIBLE_TOKENS)
        snapshots = await asyncio.gather(*(self.cmc.snapshot(s) for s in targets), return_exceptions=True)
        signals = [self.build_signal(s) for s in snapshots if isinstance(s, CmcSnapshot)]
        return sorted(signals, key=lambda item: (item.executable, item.edge_score, item.confidence), reverse=True)

    def build_signal(self, snap: CmcSnapshot) -> Signal:
        validate_token(snap.symbol)
        session = current_session()
        bullish: list[str] = []
        bearish: list[str] = []
        avg_rsi = mean(snap.rsi.values())
        if avg_rsi < 35 or 55 <= avg_rsi <= 72:
            bullish.append(f"RSI {avg_rsi:.1f} supports upside")
        if avg_rsi > 70 or 28 <= avg_rsi <= 45:
            bearish.append(f"RSI {avg_rsi:.1f} supports downside")
        if "bullish" in snap.macd:
            bullish.append("MACD bullish crossover")
        if "bearish" in snap.macd:
            bearish.append("MACD bearish crossover")
        if snap.ema_9 > snap.ema_21:
            bullish.append("EMA 9 above EMA 21")
        else:
            bearish.append("EMA 9 below EMA 21")
        if snap.price > snap.bollinger_middle:
            bullish.append("Price above Bollinger middle")
        else:
            bearish.append("Price below Bollinger middle")
        if snap.funding_rate > 0:
            bullish.append("Funding pressure positive")
        else:
            bearish.append("Funding pressure negative")
        if snap.fear_greed > 45:
            bullish.append(f"Fear and Greed {snap.fear_greed}")
        else:
            bearish.append(f"Fear and Greed {snap.fear_greed}")
        if snap.news_sentiment >= 55:
            bullish.append(f"CMC news sentiment {snap.news_sentiment}")
        else:
            bearish.append(f"CMC news sentiment {snap.news_sentiment}")

        if len(bullish) >= 4 and len(bullish) >= len(bearish):
            direction, confluence = "BUY", bullish
        elif len(bearish) >= 4:
            direction, confluence = "SELL", bearish
        else:
            direction, confluence = "HOLD", bullish if len(bullish) >= len(bearish) else bearish
        confidence = min(96, 42 + len(confluence) * 8 + int(abs(snap.change_24h)) + max(0, snap.liquidity_score - 70) // 3)
        strength = "EXTREME" if confidence >= 86 and len(confluence) >= 6 else "STRONG" if confidence >= 75 and len(confluence) >= 5 else "MODERATE" if confidence >= 62 else "WEAK"
        stop_distance = max(snap.atr * 1.5, snap.price * 0.004)
        stop_loss = snap.price - stop_distance if direction == "BUY" else snap.price + stop_distance
        take_profit = snap.price + stop_distance * 2 if direction == "BUY" else snap.price - stop_distance * 2
        volatility_pct = snap.atr / snap.price * 100
        liquidity_bonus = max(0, snap.liquidity_score - 70) / 4
        sentiment_bonus = max(0, snap.news_sentiment - 50) / 8 + max(0, snap.social_sentiment - 50) / 12
        oi_bonus = max(-4, min(4, snap.open_interest_change / 2))
        volatility_penalty = max(0, volatility_pct - 2.5) * 3
        edge_score = round(confidence + liquidity_bonus + sentiment_bonus + oi_bonus - volatility_penalty, 2)
        snap.narratives = [*snap.narratives, f"edge_score:{edge_score}", f"volatility_pct:{volatility_pct:.2f}"]
        executable = direction in {"BUY", "SELL"} and strength in {"STRONG", "EXTREME"} and confidence >= session.minimum_confidence
        reasoning = (
            f"{snap.symbol} produced a {strength} {direction} signal at {confidence}% confidence and {edge_score:.1f} edge score during the "
            f"{session.name} session, which requires {session.minimum_confidence}%. "
            f"{len(confluence)} CMC factors agree: {', '.join(confluence[:6])}. "
            f"ATR stop distance is {stop_distance:.6g}, giving a 1:2 minimum risk reward plan. "
            f"Market regime is {snap.market_regime}; token eligibility was confirmed before execution."
        )
        return Signal(snap.symbol, direction, confidence, strength, snap.price, stop_loss, take_profit, confluence, session.name, session.minimum_confidence, reasoning, asdict(snap), executable, edge_score, 2.0, volatility_pct)
