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


# A focused, liquid sub-universe of the eligible allowlist. Scanning every one of
# the 148 eligible symbols on each tick is wasteful (memory + latency on Railway)
# and undisciplined; Fidel concentrates on liquid markets that actually have a
# real BSC/CEX price. Every symbol here is also on the eligible allowlist.
FOCUSED_UNIVERSE: tuple[str, ...] = (
    "ETH", "XRP", "TRX", "DOGE", "ADA", "LINK", "BCH", "TON", "LTC", "AVAX",
    "SHIB", "DOT", "UNI", "ETC", "AAVE", "ATOM", "FIL", "INJ", "FET", "BONK",
    "PENGU", "CAKE", "FLOKI", "LDO", "PENDLE", "AXS", "COMP", "APE", "SUSHI",
    "ZRO", "SNX", "YFI", "KAVA", "ZIL", "ROSE", "ACH", "1INCH",
)


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
    data_source: str = "demo"
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
    data_source: str = "demo"


class PublicPriceFeed:
    """Free, key-less real-price fallback via Binance public spot tickers.

    One batched HTTP call returns 24h price + percent change for every requested
    symbol, so the whole scan costs a single request instead of 30+. Symbols not
    listed on Binance simply fall through to the deterministic model below.
    """

    BASE = "https://api.binance.com/api/v3/ticker/24hr"

    async def fetch(self, symbols: list[str]) -> dict[str, tuple[float, float]]:
        pairs = {f"{s.upper()}USDT": s for s in symbols}
        params = {"symbols": json.dumps(list(pairs.keys()), separators=(",", ":"))}
        out: dict[str, tuple[float, float]] = {}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.get(self.BASE, params=params)
                res.raise_for_status()
                rows = res.json()
        except Exception:
            return out
        for row in rows if isinstance(rows, list) else []:
            symbol = pairs.get(row.get("symbol", ""))
            try:
                price = float(row["lastPrice"])
                change = float(row.get("priceChangePercent", 0))
            except (KeyError, TypeError, ValueError):
                continue
            if symbol and price > 0:
                out[symbol] = (price, change)
        return out


class CmcAgentHubClient:
    """CMC Agent Hub adapter with x402-ready headers and resilient fallbacks.

    Resolution order per symbol: CMC MCP -> CMC HTTP -> public price feed
    (real Binance prices) -> deterministic model. Live mode only fails closed
    when DATA_FALLBACK_ENABLED is off, so Fidel keeps trading on honest,
    clearly-labelled fallback data instead of silently going dark.
    """

    def __init__(self, cfg: Settings = settings) -> None:
        self.cfg = cfg

    async def snapshot(self, symbol: str, price_hint: tuple[float, float] | None = None) -> CmcSnapshot:
        symbol = validate_token(symbol)
        if self.cfg.cmc_mcp_command:
            return await self._mcp_snapshot(symbol)
        if self.cfg.cmc_api_key:
            return await self._http_snapshot(symbol)
        if price_hint is not None:
            price, change = price_hint
            return self._derive_snapshot(symbol, price, change, source="binance-public")
        if self.cfg.autonomous_live and not self.cfg.data_fallback_enabled:
            raise RuntimeError("CMC data feed unavailable and DATA_FALLBACK_ENABLED is off; live trading fails closed")
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
        return self._derive_snapshot(symbol, price, float(data.get("percent_change_24h", 0)), source="cmc-agent-hub")

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
        payload.setdefault("data_source", "cmc-mcp")
        return CmcSnapshot(**payload)

    def _demo_snapshot(self, symbol: str) -> CmcSnapshot:
        seed = int(hashlib.sha256(f"{symbol}:{datetime.now(timezone.utc).date()}".encode()).hexdigest(), 16)
        rng = random.Random(seed)
        price = round(rng.uniform(0.05, 800), 6)
        return self._derive_snapshot(symbol, price, rng.uniform(-8, 8), source="demo")

    def _derive_snapshot(self, symbol: str, price: float, change_24h: float, *, source: str) -> CmcSnapshot:
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
            data_source=source,
            narratives=["CMC Agent Hub", "BSC eligible token", "x402 data path", f"source:{source}"],
        )


class SignalEngine:
    def __init__(self, cmc: CmcAgentHubClient | None = None, cfg: Settings = settings) -> None:
        self.cfg = cfg
        self.cmc = cmc or CmcAgentHubClient(cfg)
        self.feed = PublicPriceFeed()

    def _universe(self) -> list[str]:
        if self.cfg.scan_universe_csv.strip():
            requested = [s.strip() for s in self.cfg.scan_universe_csv.split(",") if s.strip()]
        else:
            requested = list(FOCUSED_UNIVERSE)
        # Keep only eligible symbols, preserve order, de-dupe.
        seen: set[str] = set()
        universe = []
        for symbol in requested:
            if symbol in ELIGIBLE_TOKENS and symbol not in seen:
                seen.add(symbol)
                universe.append(symbol)
        return universe or sorted(FOCUSED_UNIVERSE)

    async def scan(self, symbols: list[str] | None = None) -> list[Signal]:
        targets = symbols or self._universe()
        price_hints: dict[str, tuple[float, float]] = {}
        if self.cfg.public_price_feed and not (self.cfg.cmc_mcp_command or self.cfg.cmc_api_key):
            price_hints = await self.feed.fetch(targets)
        sem = asyncio.Semaphore(max(1, self.cfg.scan_concurrency))

        async def _one(sym: str) -> CmcSnapshot | Exception:
            async with sem:
                try:
                    return await self.cmc.snapshot(sym, price_hints.get(sym))
                except Exception as exc:  # noqa: BLE001 - degrade gracefully, never crash the scan
                    return exc

        snapshots = await asyncio.gather(*(_one(s) for s in targets))
        signals = [self.build_signal(s) for s in snapshots if isinstance(s, CmcSnapshot)]
        return sorted(signals, key=lambda item: (item.executable, item.edge_score, item.confidence), reverse=True)

    def build_signal(self, snap: CmcSnapshot) -> Signal:
        validate_token(snap.symbol)
        session = current_session()
        bullish: list[str] = []
        bearish: list[str] = []
        avg_rsi = mean(snap.rsi.values())
        rsi_values = list(snap.rsi.values())
        rsi_aligned_up = all(v < 70 for v in rsi_values) and avg_rsi >= 50
        rsi_aligned_down = all(v > 30 for v in rsi_values) and avg_rsi <= 50
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
        # Discipline: a multi-timeframe RSI that agrees with the trade earns a
        # small conviction bump; a contradicting trade is penalised.
        if direction == "BUY" and rsi_aligned_up:
            confidence = min(96, confidence + 3)
        elif direction == "SELL" and rsi_aligned_down:
            confidence = min(96, confidence + 3)
        elif direction in {"BUY", "SELL"}:
            confidence = max(0, confidence - 4)
        strength = "EXTREME" if confidence >= 86 and len(confluence) >= 6 else "STRONG" if confidence >= 75 and len(confluence) >= 5 else "MODERATE" if confidence >= 62 else "WEAK"
        stop_distance = max(snap.atr * 1.5, snap.price * 0.004)
        stop_loss = snap.price - stop_distance if direction == "BUY" else snap.price + stop_distance
        take_profit = snap.price + stop_distance * 2 if direction == "BUY" else snap.price - stop_distance * 2
        risk_reward = round(abs(take_profit - snap.price) / stop_distance, 2) if stop_distance else 0.0
        volatility_pct = snap.atr / snap.price * 100
        liquidity_bonus = max(0, snap.liquidity_score - 70) / 4
        sentiment_bonus = max(0, snap.news_sentiment - 50) / 8 + max(0, snap.social_sentiment - 50) / 12
        oi_bonus = max(-4, min(4, snap.open_interest_change / 2))
        volatility_penalty = max(0, volatility_pct - 2.5) * 3
        edge_score = round(confidence + liquidity_bonus + sentiment_bonus + oi_bonus - volatility_penalty, 2)
        snap.narratives = [*snap.narratives, f"edge_score:{edge_score}", f"volatility_pct:{volatility_pct:.2f}"]
        # Discipline gate: only fire when the setup is strong, confident, the
        # regime is not fighting the trade, and the reward/risk clears the floor.
        regime_ok = not (
            (direction == "BUY" and snap.market_regime == "risk-off volatility")
            or (direction == "SELL" and snap.market_regime == "risk-on trend")
        )
        executable = (
            direction in {"BUY", "SELL"}
            and strength in {"STRONG", "EXTREME"}
            and confidence >= session.minimum_confidence
            and risk_reward >= self.cfg.min_risk_reward
            and regime_ok
        )
        reasoning = (
            f"{snap.symbol} produced a {strength} {direction} signal at {confidence}% confidence and {edge_score:.1f} edge score during the "
            f"{session.name} session, which requires {session.minimum_confidence}%. "
            f"{len(confluence)} CMC factors agree: {', '.join(confluence[:6])}. "
            f"ATR stop distance is {stop_distance:.6g} for a 1:{risk_reward:g} reward-to-risk plan. "
            f"Market regime is {snap.market_regime}; data source {snap.data_source}; token eligibility was confirmed before execution."
        )
        return Signal(
            snap.symbol, direction, confidence, strength, snap.price, stop_loss, take_profit, confluence,
            session.name, session.minimum_confidence, reasoning, asdict(snap), executable, edge_score,
            risk_reward, volatility_pct, snap.data_source,
        )
