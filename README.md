# Fidel

Fidel is a professional autonomous AI trading agent web application for BNB Hack AI Trading Agent Competition Track 1. It reads market data through CoinMarketCap Agent Hub paths, builds multi-confluence signals, applies strict competition risk gates, and executes BSC trades through Trust Wallet Agent Kit.

## Critical Competition Notes

- Live trading window: June 22 to June 28, 2026.
- DoraHacks submission deadline: June 21, 2026 at 13:00.
- Register before June 22 with `twak compete register`.
- Only eligible BEP-20 symbols in `backend/signals.py` are allowed. Unknown tokens are rejected before execution.
- For live mode, set `STRICT_LIVE_TOKEN_CONTRACTS=true` and provide `ELIGIBLE_TOKEN_REGISTRY_PATH` with BSC contract addresses. Symbol-only validation is not enough for real competition execution.
- Hard drawdown cap defaults to 25%. At or above the cap Fidel stops all trading.
- Maximum position size defaults to 2% of portfolio.
- Daily loss limit defaults to 5%.
- Minimum one trade per UTC day is tracked on the dashboard.
- Live mode fails closed if CMC, TWAK, BSC, or signing configuration is unavailable.
- See `COMPETITION_RUNBOOK.md` for the live cutover, DoraHacks submission checklist, and emergency procedure.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm install
```

Copy `.env.example` to `.env` and fill:

- `CMC_API_KEY` or `CMC_MCP_COMMAND`
- `TRUST_WALLET_PRIVATE_KEY`
- `AGENT_WALLET_ADDRESS`
- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
- PancakeSwap and BSC contract addresses

Copy `config/eligible_tokens.example.json` to `config/eligible_tokens.json` and complete the official competition token registry before live mode. Fidel refuses live trades for eligible symbols that do not have a verified BSC contract address in that registry.

## Run Locally

Backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Frontend:

```powershell
cd frontend
npm run dev -- --port 5173
```

Open `http://localhost:5173`.

## Docker

```powershell
docker compose up --build
```

## Live Mode

Set `AUTONOMOUS_LIVE=true`. Fidel will then require real CMC Agent Hub/MCP data access, TWAK signing, BSC connectivity, wallet address, and PancakeSwap addresses. Private keys are read from environment variables and are never logged.

## Competition Registration

Register on-chain:

```powershell
twak compete register --chain bsc --contract 0x212c61b9b72c95d95bf29cf032f5e5635629aed5 --wallet <AGENT_WALLET_ADDRESS> --json
```

The API endpoint `/api/competition/register` calls the same TWAK registration flow. Submit the agent address on DoraHacks and verify the registration transaction on BscScan.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests
```

## Dashboard

The React dashboard uses a professional light theme by default and includes a one-click dark theme. Colors are centralized in `frontend/src/styles.css` CSS variables, so operators can change branding without rewriting components. It updates through WebSocket and includes portfolio value, PnL, open positions, ATR stop loss/take profit, drawdown meter, trade history with BSC transaction hashes, signal reasoning, Fear and Greed, market regime, agent controls, activity log, daily trade counter, eligible watchlist, session indicator, and competition CSV download.

## Source Audit

I verified the official BNB Chain blog and CoinMarketCap hackathon page. You also provided the DoraHacks requirements text. Track 1 is an autonomous BSC trading agent track using CMC for signal/data, Trust Wallet Agent Kit for self-custody signing/execution, BNB AI Agent SDK for BSC agent primitives, and PancakeSwap/BSC perps as execution venues.

The DoraHacks text states 149 eligible-token list entries. The pasted list includes duplicate/ambiguous text (`SLX` appears twice and `USDf`/`USDF` are case-distinct). Fidel preserves 149 official list entries for audit while the executable registry keeps unique display symbols and exact-case validation.
