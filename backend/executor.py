from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Settings, settings
from .risk import PortfolioState, Position, RiskDecision
from .signals import Signal
from .tokens import validate_token
from .tokens import registry


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    tx_hash: str
    message: str


@dataclass(frozen=True)
class ExecutionPreview:
    approved: bool
    venue: str
    route: list[str]
    expected_output_usdt: float
    max_slippage_bps: int
    estimated_slippage_bps: int
    estimated_gas_usdt: float
    price_impact_pct: float
    token_address: str
    warnings: list[str]


class TrustWalletExecutor:
    """TWAK-only execution adapter. Live mode requires TWAK CLI/MCP to sign locally."""

    def __init__(self, cfg: Settings = settings) -> None:
        self.cfg = cfg

    async def execute_swap(self, signal: Signal, risk: RiskDecision, portfolio: PortfolioState) -> ExecutionResult:
        validate_token(signal.symbol, require_contract=self.cfg.autonomous_live and self.cfg.strict_live_token_contracts)
        if not risk.approved:
            return ExecutionResult("rejected", "", risk.reason)
        preview = self.preview_swap(signal, risk)
        if not preview.approved:
            return ExecutionResult("rejected", "", "execution preflight rejected route: " + "; ".join(preview.warnings))
        if self.cfg.autonomous_live:
            return await self._twak_swap(signal, risk)
        payload = f"{signal.symbol}:{signal.direction}:{signal.price}:{datetime.now(timezone.utc).isoformat()}"
        return ExecutionResult("confirmed", "0x" + hashlib.sha256(payload.encode()).hexdigest(), "development execution simulated; live mode uses TWAK")

    def preview_swap(self, signal: Signal, risk: RiskDecision) -> ExecutionPreview:
        token = registry.validate(signal.symbol, require_contract=self.cfg.autonomous_live and self.cfg.strict_live_token_contracts)
        liquidity = int(signal.cmc_snapshot.get("liquidity_score", 70))
        volatility = float(getattr(signal, "volatility_pct", 1.0))
        estimated_slippage = max(8, int((100 - liquidity) * 1.4 + volatility * 5))
        gas_usdt = round(0.35 + risk.position_size_usdt * 0.0008, 4)
        price_impact = round(estimated_slippage / 100, 4)
        warnings: list[str] = []
        if estimated_slippage > self.cfg.max_slippage_bps:
            warnings.append(f"estimated slippage {estimated_slippage} bps exceeds {self.cfg.max_slippage_bps} bps")
        if gas_usdt > self.cfg.max_gas_usdt:
            warnings.append(f"estimated gas ${gas_usdt:.2f} exceeds ${self.cfg.max_gas_usdt:.2f}")
        if self.cfg.autonomous_live and not token.address:
            warnings.append("missing BSC token contract")
        return ExecutionPreview(
            approved=not warnings,
            venue="PancakeSwap V3 on BSC",
            route=["USDT", signal.symbol] if signal.direction == "BUY" else [signal.symbol, "USDT"],
            expected_output_usdt=round(risk.position_size_usdt * (1 - estimated_slippage / 10000), 4),
            max_slippage_bps=self.cfg.max_slippage_bps,
            estimated_slippage_bps=estimated_slippage,
            estimated_gas_usdt=gas_usdt,
            price_impact_pct=price_impact,
            token_address=token.address,
            warnings=warnings,
        )

    async def _twak_swap(self, signal: Signal, risk: RiskDecision) -> ExecutionResult:
        if not self.cfg.trust_wallet_private_key:
            raise RuntimeError("TRUST_WALLET_PRIVATE_KEY missing; TWAK cannot sign locally")
        command = [
            self.cfg.twak_command,
            "swap",
            "--chain", "bsc",
            "--router", self.cfg.pancakeswap_v3_router,
            "--token", signal.symbol,
            "--side", signal.direction.lower(),
            "--amount-usdt", str(risk.position_size_usdt),
            "--stop-loss", str(signal.stop_loss),
            "--take-profit", str(signal.take_profit),
            "--autonomous",
            "--x402",
            "--mcp-actions",
            "--langchain",
            "--json",
        ]
        proc = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"TWAK execution failed: {err.decode().strip()}")
        data = json.loads(out.decode())
        return ExecutionResult(data.get("status", "submitted"), data.get("tx_hash", ""), data.get("message", "TWAK swap submitted"))

    def apply_fill(self, signal: Signal, risk: RiskDecision, result: ExecutionResult, portfolio: PortfolioState) -> None:
        if result.status not in {"confirmed", "submitted"}:
            return
        quantity = risk.position_size_usdt / signal.price
        portfolio.cash_usdt -= risk.position_size_usdt
        portfolio.positions.append(Position(signal.symbol, signal.direction, signal.price, signal.price, quantity, signal.stop_loss, signal.take_profit, datetime.now(timezone.utc).isoformat(), result.tx_hash))


class BnbAgentCoordinator:
    def __init__(self, cfg: Settings = settings) -> None:
        self.cfg = cfg

    async def heartbeat(self) -> str:
        if not self.cfg.bnb_agent_sdk_command:
            return "BNB AI Agent SDK command not configured; lifecycle running in native Python coordinator"
        proc = await asyncio.create_subprocess_shell(f"{self.cfg.bnb_agent_sdk_command} heartbeat --chain bsc", stdout=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate()
        return out.decode().strip() or "BNB SDK heartbeat sent"
