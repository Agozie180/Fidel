from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Settings, settings


@dataclass(frozen=True)
class RegistrationStatus:
    registered: bool
    wallet: str
    contract: str
    tx_hash: str = ""
    message: str = ""


class CompetitionRegistrar:
    def __init__(self, cfg: Settings = settings) -> None:
        self.cfg = cfg

    async def register(self) -> RegistrationStatus:
        if not self.cfg.agent_wallet_address:
            return RegistrationStatus(False, "", self.cfg.competition_contract_address, message="AGENT_WALLET_ADDRESS is missing")
        command = [
            self.cfg.twak_command,
            "compete",
            "register",
            "--chain", "bsc",
            "--contract", self.cfg.competition_contract_address,
            "--wallet", self.cfg.agent_wallet_address,
            "--json",
        ]
        proc = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        if proc.returncode != 0:
            return RegistrationStatus(False, self.cfg.agent_wallet_address, self.cfg.competition_contract_address, message=err.decode().strip())
        data = json.loads(out.decode() or "{}")
        return RegistrationStatus(True, self.cfg.agent_wallet_address, self.cfg.competition_contract_address, data.get("tx_hash", ""), "registered")

    async def status(self) -> RegistrationStatus:
        if not self.cfg.agent_wallet_address:
            return RegistrationStatus(False, "", self.cfg.competition_contract_address, message="wallet not configured")
        return RegistrationStatus(False, self.cfg.agent_wallet_address, self.cfg.competition_contract_address, message="Use register before 2026-06-22; verify tx on bscscan.com")

