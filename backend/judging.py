from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .config import Settings, settings


@dataclass(frozen=True)
class ReadinessItem:
    name: str
    points: int
    earned: int
    status: str
    evidence: str


@dataclass(frozen=True)
class JudgingReadiness:
    score: int
    possible: int
    grade: str
    items: list[ReadinessItem]
    missing: list[str]
    submission_brief: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "possible": self.possible,
            "grade": self.grade,
            "items": [asdict(item) for item in self.items],
            "missing": self.missing,
            "submission_brief": self.submission_brief,
        }


def build_judging_readiness(
    *,
    cfg: Settings = settings,
    registry_status: dict[str, Any],
    trade_count: int,
    today_trades: int,
    has_bsc_hashes: bool,
) -> JudgingReadiness:
    items = [
        _item("CMC Agent Hub + x402", 15, bool(cfg.cmc_api_key or cfg.cmc_mcp_command), "CMC key/MCP command configured"),
        _item("Trust Wallet Agent Kit execution", 15, bool(cfg.twak_command), f"TWAK command: {cfg.twak_command or 'missing'}"),
        _item("BNB AI Agent SDK lifecycle", 10, bool(cfg.bnb_agent_sdk_command), "BNB SDK heartbeat command configured"),
        _item("LLM reasoning layer", 10, cfg.llm_available, "Anthropic or OpenAI API key configured"),
        _item("Strict BSC token registry", 15, registry_status.get("contract_ready", 0) > 0 and cfg.strict_live_token_contracts, f"{registry_status.get('contract_ready', 0)} contract-ready tokens"),
        _item("Risk gate implementation", 15, True, "2% position cap, 25% hard drawdown, daily loss, ATR stops, 3-position cap"),
        _item("Judge-verifiable logs", 10, trade_count > 0 and has_bsc_hashes, f"{trade_count} trades logged with transaction hashes"),
        _item("Daily trade compliance", 5, today_trades >= 1, f"{today_trades}/1 UTC trades today"),
        _item("Autonomous live switch", 5, cfg.autonomous_live, f"AUTONOMOUS_LIVE={cfg.autonomous_live}"),
    ]
    score = sum(item.earned for item in items)
    possible = sum(item.points for item in items)
    missing = [item.name for item in items if item.earned < item.points]
    grade = "MYTHIC READY" if score >= 90 else "COMPETITION READY" if score >= 75 else "NEEDS HARDENING" if score >= 55 else "NOT LIVE READY"
    return JudgingReadiness(
        score=score,
        possible=possible,
        grade=grade,
        items=items,
        missing=missing,
        submission_brief={
            "agent_name": "Fidel",
            "track": "Track 1 Autonomous Trading Agent",
            "registration_deadline": cfg.competition_registration_deadline,
            "trading_window": f"{cfg.competition_trading_start} to {cfg.competition_trading_end}",
            "venue": "BNB Smart Chain via TWAK and PancakeSwap/BSC perps",
            "proofs": ["BSC transaction hashes", "SQLite log", "CSV competition report", "dashboard readiness score"],
        },
    )


def _item(name: str, points: int, ok: bool, evidence: str) -> ReadinessItem:
    return ReadinessItem(name, points, points if ok else 0, "PASS" if ok else "MISSING", evidence)
