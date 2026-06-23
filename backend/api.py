from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .competition import CompetitionRegistrar
from .config import settings
from .executor import BnbAgentCoordinator, TrustWalletExecutor
from .judging import build_judging_readiness
from .logger import CompetitionLogger
from .risk import PortfolioState, RiskManager
from .signals import Signal, SignalEngine
from .tokens import ELIGIBLE_TOKENS, registry


TRADE_WINDOWS: dict[str, tuple[int, int]] = {
    "morning": (0, 8),
    "afternoon": (8, 16),
    "night": (16, 24),
}


def trade_window(now: datetime) -> str:
    hour = now.astimezone(timezone.utc).hour
    for name, (start, end) in TRADE_WINDOWS.items():
        if start <= hour < end:
            return name
    return "night"


class ReasoningLayer:
    async def explain(self, signal: Signal, alternatives: list[Signal]) -> str:
        prompt = (
            "You are Fidel, an autonomous BSC trading agent. Explain this decision in concise plain English. "
            "Cover token selection, market regime, CMC sentiment/news, position sizing, and why trade or no trade.\n"
            f"Selected: {json.dumps(asdict(signal))}\n"
            f"Top alternatives: {json.dumps([asdict(s) for s in alternatives[:5]])}"
        )
        if settings.anthropic_api_key:
            return await self._anthropic(prompt)
        if settings.openai_api_key:
            return await self._openai(prompt)
        return signal.reasoning + " LLM key is not configured, so Fidel used the deterministic reasoning template."

    async def _anthropic(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=25) as client:
            res = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01"},
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]},
            )
            res.raise_for_status()
            return res.json()["content"][0]["text"]

    async def _openai(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=25) as client:
            res = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": "gpt-4.1-mini", "messages": [{"role": "user", "content": prompt}], "max_tokens": 300},
            )
            res.raise_for_status()
            return res.json()["choices"][0]["message"]["content"]


class FidelRuntime:
    def __init__(self) -> None:
        self.status = "STOPPED"
        self.signal_engine = SignalEngine()
        self.risk = RiskManager()
        self.executor = TrustWalletExecutor()
        self.bnb = BnbAgentCoordinator()
        self.reasoning = ReasoningLayer()
        self.logger = CompetitionLogger()
        self.registrar = CompetitionRegistrar()
        self.portfolio = PortfolioState(settings.initial_portfolio_usdt, settings.initial_portfolio_usdt)
        self.top_signals: list[Signal] = []
        self.execution_preview: dict[str, Any] = self._waiting_preview("Agent stopped; press Start")
        self.activity: list[str] = []
        self.daily_trade_count: dict[str, int] = {}
        self.daily_window_trades: dict[str, dict[str, int]] = {}
        self._last_activity_by_key: dict[str, str] = {}
        self.last_error = ""
        self._consecutive_errors = 0
        self.data_source = "demo"
        self._task: asyncio.Task | None = None
        self._clients: set[WebSocket] = set()

    # --- desired-state persistence (survives Railway restarts / OOM kills) ---
    def _persist_state(self) -> None:
        try:
            settings.state_path.parent.mkdir(parents=True, exist_ok=True)
            settings.state_path.write_text(
                json.dumps({"desired_status": self.status, "updated_at": datetime.now(timezone.utc).isoformat()}),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 - persistence must never crash the agent
            self.logger.log_event("WARNING", "state persist failed", {"error": str(exc)})

    def _load_desired_status(self) -> str:
        try:
            if settings.state_path.exists():
                return json.loads(settings.state_path.read_text(encoding="utf-8")).get("desired_status", "")
        except Exception:  # noqa: BLE001
            return ""
        return ""

    async def resume_if_desired(self) -> None:
        """Called on server startup so the agent keeps running across restarts."""
        desired = self._load_desired_status()
        if desired == "RUNNING" or (settings.auto_start and desired != "STOPPED"):
            self._log_activity("auto_resume", f"Auto-resuming agent (desired={desired or 'auto_start'})", force=True)
            await self.start()

    async def start(self) -> None:
        if self.status == "RUNNING" and self._task and not self._task.done():
            return
        self.status = "RUNNING"
        self._persist_state()
        if not self._task or self._task.done():
            self._task = asyncio.create_task(self.loop())
        await self.broadcast()

    async def pause(self) -> None:
        self.status = "PAUSED"
        self._persist_state()
        await self.broadcast()

    async def stop(self) -> None:
        self.status = "STOPPED"
        self._persist_state()
        if self._task:
            self._task.cancel()
        await self.broadcast()

    async def emergency_stop(self, reason: str = "manual emergency stop") -> None:
        self.status = "STOPPED"
        self._persist_state()
        self.portfolio.stopped = True
        self._log_activity("emergency_stop", f"EMERGENCY STOP: {reason}", force=True)
        self.logger.log_event("CRITICAL", "emergency stop activated", {"reason": reason})
        if self._task:
            self._task.cancel()
        await self.broadcast()

    async def loop(self) -> None:
        while self.status != "STOPPED":
            if self.status == "PAUSED":
                await asyncio.sleep(1)
                continue
            try:
                await self.tick()
                self._consecutive_errors = 0
                self.last_error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a single bad tick must not kill the loop
                self._consecutive_errors += 1
                self.last_error = str(exc)
                self.logger.log_event("ERROR", "agent tick failed", {"error": self.last_error, "streak": self._consecutive_errors})
                self._log_activity("tick_error", f"Tick error ({self._consecutive_errors}): {self.last_error}")
            await self.broadcast()
            # Exponential backoff on a run of errors, capped, instead of giving up.
            interval = settings.trade_interval_seconds
            if self._consecutive_errors:
                interval = min(settings.trade_interval_seconds * (2 ** min(self._consecutive_errors, 4)), 600)
            await asyncio.sleep(interval)

    @staticmethod
    def _waiting_preview(message: str) -> dict[str, Any]:
        return {"approved": False, "venue": "PancakeSwap V3 on BSC", "route": [], "warnings": [message], "mode": settings.execution_mode}

    async def tick(self) -> None:
        await self.bnb.heartbeat()
        self.top_signals = (await self.signal_engine.scan())[:10]
        prices = {s.symbol: s.price for s in self.top_signals}
        self.portfolio.mark_to_market(prices)
        if self.top_signals:
            self.data_source = self.top_signals[0].data_source
        if not self.top_signals:
            self.execution_preview = self._waiting_preview("No market data available from CMC or fallback feed")
            self._log_activity("cmc_feed", "No market signals available from any data source")
            return
        now = datetime.now(timezone.utc)
        day = now.date().isoformat()
        window = trade_window(now)
        in_competition_week = "2026-06-22" <= day <= "2026-06-28"
        if in_competition_week and now.hour >= 20 and self.daily_trade_count.get(day, 0) == 0:
            if self._log_activity(f"daily_trade_alert:{day}", "Daily trade requirement alert: no qualifying trade recorded by 20:00 UTC"):
                self.logger.log_event("WARNING", "daily trade requirement alert", {"date": day})
        selected = self.top_signals[0]
        selected.reasoning = await self.reasoning.explain(selected, self.top_signals[1:])
        decision = self.risk.evaluate(selected, self.portfolio)
        route = ["USDT", selected.symbol] if selected.direction == "BUY" else [selected.symbol, "USDT"]
        if decision.approved:
            self.execution_preview = asdict(self.executor.preview_swap(selected, decision))
        else:
            self.execution_preview = {
                "approved": False,
                "venue": "PancakeSwap V3 on BSC",
                "route": route,
                "warnings": [decision.reason],
                "mode": settings.execution_mode,
            }
        self._log_activity("trade_decision", f"{selected.symbol} {selected.direction} {selected.confidence}% {selected.strength} in {window}: {decision.reason}")
        if not decision.approved:
            self.logger.log_event("INFO", "trade rejected by risk layer", {"symbol": selected.symbol, "reason": decision.reason})
            return
        if not self._window_trade_available(day, window):
            reason = f"{window} UTC trade window already used for {day}; waiting for next window"
            self.execution_preview = {"approved": False, "venue": "PancakeSwap V3 on BSC", "route": route, "warnings": [reason], "mode": settings.execution_mode}
            self._log_activity(f"window_throttle:{day}:{window}", reason)
            self.logger.log_event("INFO", "trade rejected by window throttle", {"date": day, "window": window, "symbol": selected.symbol})
            return
        before = self.portfolio.value
        result = await self.executor.execute_swap(selected, decision, self.portfolio)
        if result.status not in {"confirmed", "submitted"}:
            reason = f"Execution rejected for {selected.symbol}: {result.message}"
            self.execution_preview = {"approved": False, "venue": "PancakeSwap V3 on BSC", "route": route, "warnings": [reason], "mode": settings.execution_mode}
            self._log_activity("execution_rejected", reason)
            self.logger.log_event("WARNING", "execution rejected", {"symbol": selected.symbol, "message": result.message})
            return
        self.executor.apply_fill(selected, decision, result, self.portfolio)
        after = self.portfolio.value
        self._record_window_trade(day, window)
        self._log_activity(f"trade_fill:{day}:{window}", f"Executed {selected.direction} {selected.symbol} in {window} window: {result.tx_hash}", force=True)
        self.logger.log_trade(
            {
                "utc_timestamp": datetime.now(timezone.utc).isoformat(),
                "token": selected.symbol,
                "direction": selected.direction,
                "entry_price": selected.price,
                "stop_loss": selected.stop_loss,
                "take_profit": selected.take_profit,
                "exit_price": None,
                "position_size_usdt": decision.position_size_usdt,
                "pnl_usdt": 0,
                "pnl_pct": 0,
                "bsc_tx_hash": result.tx_hash,
                "portfolio_before": before,
                "portfolio_after": after,
                "running_return_pct": (after - self.portfolio.starting_value) / self.portfolio.starting_value * 100,
                "drawdown_pct": self.portfolio.drawdown_pct,
                "signal_confidence": selected.confidence,
                "signal_strength": selected.strength,
                "ai_reasoning_summary": selected.reasoning,
                "session_active": selected.session,
                "cmc_data_snapshot": selected.cmc_snapshot,
            }
        )

    def _window_trade_available(self, day: str, window: str) -> bool:
        return self.daily_window_trades.get(day, {}).get(window, 0) < 1

    def _record_window_trade(self, day: str, window: str) -> None:
        windows = self.daily_window_trades.setdefault(day, {})
        windows[window] = windows.get(window, 0) + 1
        self.daily_trade_count[day] = sum(windows.values())

    def _log_activity(self, key: str, message: str, *, force: bool = False) -> bool:
        if not force and self._last_activity_by_key.get(key) == message:
            return False
        self._last_activity_by_key[key] = message
        self.activity.insert(0, f"{datetime.now(timezone.utc).isoformat()} {message}")
        self.activity = self.activity[:200]
        return True

    def dashboard(self) -> dict[str, Any]:
        value = self.portfolio.value
        today = datetime.now(timezone.utc).date().isoformat()
        trades = self.logger.recent_trades()
        wins = [t for t in trades if float(t.get("pnl_usdt") or 0) > 0]
        closed = [t for t in trades if float(t.get("pnl_usdt") or 0) != 0]
        has_bsc_hashes = any(str(t.get("bsc_tx_hash") or "").startswith("0x") for t in trades)
        token_registry = registry.status()
        bnb_ready = self.bnb.integration_ready
        judging = build_judging_readiness(
            registry_status=token_registry,
            trade_count=len(trades),
            today_trades=self.daily_trade_count.get(today, 0),
            has_bsc_hashes=has_bsc_hashes,
            bnb_ready=bnb_ready,
        ).to_dict()
        drawdown_left = max(0, settings.max_drawdown_pct - self.portfolio.drawdown_pct)
        minimum_trade_deadline = f"{today}T20:00:00Z"
        return {
            "agent": {
                "name": "Fidel",
                "status": self.status,
                "wallet": settings.agent_wallet_address,
                "last_error": self.last_error,
                "execution_mode": settings.execution_mode,
                "data_source": self.data_source,
                "background": bool(self._task and not self._task.done()),
            },
            "portfolio": {
                "value": value,
                "starting_value": self.portfolio.starting_value,
                "total_pnl": self.portfolio.total_pnl,
                "total_return_pct": (value - self.portfolio.starting_value) / self.portfolio.starting_value * 100,
                "drawdown_pct": self.portfolio.drawdown_pct,
                "max_drawdown_pct": settings.max_drawdown_pct,
                "cash_usdt": self.portfolio.cash_usdt,
            },
            "positions": [asdict(p) | {"unrealized_pnl": p.unrealized_pnl} for p in self.portfolio.positions],
            "signals": [asdict(s) for s in self.top_signals],
            "trades": trades,
            "activity": self.activity[:80],
            "daily_trade_count": self.daily_trade_count,
            "daily_window_trades": self.daily_window_trades,
            "today_trades": self.daily_trade_count.get(today, 0),
            "win_rate": round(len(wins) / len(closed) * 100, 2) if closed else 0,
            "fear_greed": self.top_signals[0].cmc_snapshot.get("fear_greed", 50) if self.top_signals else 50,
            "market_regime": self.top_signals[0].cmc_snapshot.get("market_regime", "unknown") if self.top_signals else "unknown",
            "eligible_tokens": sorted((token.symbol for token in registry.tokens.values()), key=str.upper),
            "token_registry": token_registry,
            "execution_preview": self.execution_preview,
            "judging": judging,
            "survival": {
                "drawdown_left_pct": drawdown_left,
                "cash_floor_usdt": 1,
                "open_position_slots": max(0, 3 - len(self.portfolio.positions)),
                "minimum_trade_deadline": minimum_trade_deadline,
                "daily_trade_requirement_met": self.daily_trade_count.get(today, 0) >= 1,
                "risk_posture": "DEFENSIVE" if drawdown_left <= 7 else "CAUTIOUS" if drawdown_left <= 12 else "BALANCED",
            },
            "compliance": {
                "cmc_agent_hub": bool(settings.cmc_api_key or settings.cmc_mcp_command),
                "twak": bool(settings.twak_command),
                "bnb_ai_agent_sdk": bnb_ready,
                "llm_reasoning": settings.llm_available,
                "autonomous_live": settings.autonomous_live,
                "strict_live_contracts": settings.strict_live_token_contracts,
                "execution_mode": settings.execution_mode,
                "data_source": self.data_source,
            },
            "session": self.top_signals[0].session if self.top_signals else "unknown",
            "min_confidence": self.top_signals[0].session_min_confidence if self.top_signals else settings.min_signal_confidence,
        }

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        await websocket.send_json(self.dashboard())

    async def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def broadcast(self) -> None:
        dead: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_json(self.dashboard())
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


runtime = FidelRuntime()
router = APIRouter()


@router.get("/state")
async def state() -> dict[str, Any]:
    return runtime.dashboard()


@router.post("/agent/start")
async def start() -> dict[str, str]:
    await runtime.start()
    return {"status": runtime.status}


@router.post("/agent/pause")
async def pause() -> dict[str, str]:
    await runtime.pause()
    return {"status": runtime.status}


@router.post("/agent/stop")
async def stop() -> dict[str, str]:
    await runtime.stop()
    return {"status": runtime.status}


@router.post("/agent/emergency-stop")
async def emergency_stop() -> dict[str, str]:
    await runtime.emergency_stop()
    return {"status": runtime.status, "portfolio": "circuit_breaker_locked"}


@router.post("/agent/tick")
async def tick() -> dict[str, str]:
    await runtime.tick()
    await runtime.broadcast()
    return {"status": "ok"}


@router.post("/competition/register")
async def register() -> dict[str, Any]:
    return asdict(await runtime.registrar.register())


@router.get("/competition/report")
async def report() -> FileResponse:
    return FileResponse(settings.csv_path, media_type="text/csv", filename="fidel_competition_report.csv")


@router.get("/judging/readiness")
async def judging_readiness() -> dict[str, Any]:
    return runtime.dashboard()["judging"]


def create_app() -> FastAPI:
    app = FastAPI(title="Fidel Autonomous AI Trading Agent", version="1.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(router, prefix="/api")

    @app.on_event("startup")
    async def _resume_agent() -> None:
        # Keep trading across restarts/OOM kills and without the browser open.
        await runtime.resume_if_desired()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "agent": runtime.status, "mode": settings.execution_mode}

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await runtime.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            await runtime.disconnect(websocket)

    return app
