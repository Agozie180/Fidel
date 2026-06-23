from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Settings, settings
from .proc import ToolCommandError, run_tool_command
from .risk import PortfolioState, Position, RiskDecision
from .signals import Signal
from .tokens import validate_token
from .tokens import registry


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    tx_hash: str
    message: str
    mode: str = "PAPER"


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
    mode: str = "PAPER"


class TrustWalletExecutor:
    """Trust Wallet Agent Kit execution adapter.

    Runs in one of two honest modes:
      * LIVE  - every credential present (autonomous, private key, TWAK binary,
                PancakeSwap router). Real swaps are signed locally by TWAK.
      * PAPER - any credential missing. Trades are simulated with a clearly
                labelled deterministic hash so the pipeline, logs and daily-trade
                requirement still work, but Fidel never claims a live fill it
                did not make.
    """

    def __init__(self, cfg: Settings = settings) -> None:
        self.cfg = cfg

    async def execute_swap(self, signal: Signal, risk: RiskDecision, portfolio: PortfolioState) -> ExecutionResult:
        mode = self.cfg.execution_mode
        validate_token(signal.symbol, require_contract=self.cfg.live_execution_ready and self.cfg.strict_live_token_contracts)
        if not risk.approved:
            return ExecutionResult("rejected", "", risk.reason, mode)
        preview = self.preview_swap(signal, risk)
        if not preview.approved:
            return ExecutionResult("rejected", "", "execution preflight rejected route: " + "; ".join(preview.warnings), mode)
        if self.cfg.live_execution_ready:
            return await self._twak_swap(signal, risk)
        payload = f"{signal.symbol}:{signal.direction}:{signal.price}:{datetime.now(timezone.utc).isoformat()}"
        tx_hash = "0x" + hashlib.sha256(payload.encode()).hexdigest()
        return ExecutionResult("confirmed", tx_hash, "PAPER fill (no live TWAK credentials); set keys to trade live", "PAPER")

    def preview_swap(self, signal: Signal, risk: RiskDecision) -> ExecutionPreview:
        mode = self.cfg.execution_mode
        require_contract = self.cfg.live_execution_ready and self.cfg.strict_live_token_contracts
        token = registry.validate(signal.symbol, require_contract=require_contract)
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
        if self.cfg.live_execution_ready and not token.address:
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
            mode=mode,
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
        return ExecutionResult(data.get("status", "submitted"), data.get("tx_hash", ""), data.get("message", "TWAK swap submitted"), "LIVE")

    def apply_fill(self, signal: Signal, risk: RiskDecision, result: ExecutionResult, portfolio: PortfolioState) -> None:
        if result.status not in {"confirmed", "submitted"}:
            return
        quantity = risk.position_size_usdt / signal.price
        portfolio.cash_usdt -= risk.position_size_usdt
        portfolio.positions.append(Position(signal.symbol, signal.direction, signal.price, signal.price, quantity, signal.stop_loss, signal.take_profit, datetime.now(timezone.utc).isoformat(), result.tx_hash))


class BnbAgentCoordinator:
    """BNB AI Agent SDK lifecycle coordinator.

    Prefers the official ``bnbagent`` Python SDK (lazy-imported so web3 is only
    loaded when actually enabled, keeping idle memory low). Falls back to a CLI
    command, then to the native Python coordinator.
    """

    def __init__(self, cfg: Settings = settings) -> None:
        self.cfg = cfg
        self._sdk = None
        self._sdk_error = ""
        self._sdk_tried = False

    @property
    def sdk_available(self) -> bool:
        return self._sdk is not None

    def _init_sdk(self):
        # web3 is only loaded here, and only when a private key is present, so
        # PAPER mode on Railway never pays the ~35 MB web3 import cost.
        if self._sdk_tried:
            return self._sdk
        self._sdk_tried = True
        if not (self.cfg.bnb_agent_sdk_enabled and self.cfg.trust_wallet_private_key):
            return None
        try:
            from bnbagent import BNBAgent, BNBAgentConfig  # lazy import (pulls web3)

            config = BNBAgentConfig(
                network=self.cfg.bsc_chain,
                private_key=self.cfg.trust_wallet_private_key,
                wallet_address=self.cfg.agent_wallet_address,
            )
            self._sdk = BNBAgent(config)
        except Exception as exc:  # noqa: BLE001 - never let SDK init crash the agent
            self._sdk = None
            self._sdk_error = str(exc)
        return self._sdk

    async def heartbeat(self) -> str:
        # Live signing path: initialise the real SDK only when a key exists.
        if self.cfg.bnb_agent_sdk_enabled and self.cfg.trust_wallet_private_key:
            sdk = await asyncio.to_thread(self._init_sdk)
            if sdk is not None:
                wallet = self.cfg.agent_wallet_address or "unsigned"
                return f"BNB AI Agent SDK {self._sdk_version()} live on {self.cfg.bsc_chain} (wallet {wallet})"
            if self._sdk_error:
                return f"BNB SDK not initialised ({self._sdk_error}); native coordinator active"
        version = self._sdk_version()
        if version:
            return f"BNB AI Agent SDK (bnbagent {version}) installed and enabled; idle until live credentials are set"
        if self.cfg.bnb_agent_sdk_command:
            # Run the optional CLI safely: a malformed value (e.g. a stray
            # "=bnbaent" from a dashboard typo) raises instead of hitting /bin/sh.
            try:
                result = await run_tool_command(self.cfg.bnb_agent_sdk_command, "heartbeat", "--chain", "bsc")
            except ToolCommandError as exc:
                return f"BNB SDK command misconfigured ({exc}); native coordinator active"
            if result is not None:
                _, out, _ = result
                return out or "BNB SDK heartbeat sent"
        return "BNB AI Agent SDK not installed; lifecycle running in native Python coordinator"

    @staticmethod
    def _sdk_version() -> str:
        # Read version via metadata - does NOT import bnbagent/web3.
        try:
            import importlib.metadata as md

            return md.version("bnbagent")
        except Exception:  # noqa: BLE001
            return ""

    @property
    def integration_ready(self) -> bool:
        """True when the SDK is installed/enabled. Uses find_spec so it never imports web3."""
        if not self.cfg.bnb_agent_sdk_enabled:
            return bool(self.cfg.bnb_agent_sdk_command)
        import importlib.util

        if importlib.util.find_spec("bnbagent") is not None:
            return True
        return bool(self.cfg.bnb_agent_sdk_command)
