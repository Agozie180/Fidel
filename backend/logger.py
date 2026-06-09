from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import Settings, settings


class CompetitionLogger:
    def __init__(self, cfg: Settings = settings) -> None:
        self.cfg = cfg
        self.cfg.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.cfg.database_path)

    def _init_db(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    utc_timestamp TEXT NOT NULL,
                    token TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    exit_price REAL,
                    position_size_usdt REAL NOT NULL,
                    pnl_usdt REAL DEFAULT 0,
                    pnl_pct REAL DEFAULT 0,
                    bsc_tx_hash TEXT NOT NULL,
                    portfolio_before REAL NOT NULL,
                    portfolio_after REAL NOT NULL,
                    running_return_pct REAL NOT NULL,
                    drawdown_pct REAL NOT NULL,
                    signal_confidence INTEGER NOT NULL,
                    signal_strength TEXT NOT NULL,
                    ai_reasoning_summary TEXT NOT NULL,
                    session_active TEXT NOT NULL,
                    cmc_data_snapshot TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    utc_timestamp TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

    def log_event(self, level: str, message: str, payload: dict[str, Any] | None = None) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO events (utc_timestamp, level, message, payload) VALUES (datetime('now'), ?, ?, ?)",
                (level, message, json.dumps(payload or {})),
            )

    def log_trade(self, trade: dict[str, Any]) -> None:
        columns = [
            "utc_timestamp", "token", "direction", "entry_price", "stop_loss", "take_profit", "exit_price",
            "position_size_usdt", "pnl_usdt", "pnl_pct", "bsc_tx_hash", "portfolio_before", "portfolio_after",
            "running_return_pct", "drawdown_pct", "signal_confidence", "signal_strength", "ai_reasoning_summary",
            "session_active", "cmc_data_snapshot",
        ]
        row = {k: trade.get(k) for k in columns}
        row["cmc_data_snapshot"] = json.dumps(row["cmc_data_snapshot"])
        with self._connect() as db:
            placeholders = ",".join("?" for _ in columns)
            db.execute(f"INSERT INTO trades ({','.join(columns)}) VALUES ({placeholders})", [row[c] for c in columns])
        write_header = not self.cfg.csv_path.exists()
        with self.cfg.csv_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    def recent_trades(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def recent_events(self, limit: int = 80) -> list[dict[str, Any]]:
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

