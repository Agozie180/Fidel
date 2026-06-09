# Fidel Competition Runbook

## Final DoraHacks Checks

The DoraHacks text provided in the thread confirms Track 1 rules, special prize criteria, registration requirements, minimum trade count, max drawdown gate, and official resources. Before submission manually confirm:

- Official 149-token BEP-20 list and contract addresses.
- Agent address submission field.
- Repository URL, demo video, and write-up requirements.
- Any final scoring or disqualification wording.

## Live Cutover Checklist

1. Copy `.env.example` to `.env`.
2. Copy `config/eligible_tokens.example.json` to `config/eligible_tokens.json`.
3. Replace the example token file with the official DoraHacks token list and verified BSC contract addresses.
4. Configure `CMC_API_KEY` or `CMC_MCP_COMMAND`.
5. Configure `TRUST_WALLET_PRIVATE_KEY`, `AGENT_WALLET_ADDRESS`, `TWAK_COMMAND`, `BSC_RPC_URL`, and PancakeSwap addresses.
6. Configure `BNB_AGENT_SDK_COMMAND`.
7. Configure `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.
8. Keep `STRICT_LIVE_TOKEN_CONTRACTS=true`.
9. Run the test suite.
10. Start backend and frontend.
11. Confirm dashboard Judging Scorecard is at least `COMPETITION READY`.
12. Register before the deadline with `/api/competition/register` or `twak compete register`.
13. Submit the wallet address on DoraHacks.
14. Set `AUTONOMOUS_LIVE=true` only after registration and dry-run checks.

## During June 22-28 Trading

- Keep the dashboard open.
- Verify at least one qualifying BSC trade hash is logged per UTC day.
- Treat any drawdown above 18% as capital preservation mode.
- Treat drawdown above 20% as urgent manual review.
- The hard 25% drawdown gate stops all trading.
- Use the Kill button if CMC, TWAK, BSC RPC, token registry, or routing behaves unexpectedly.

## Operator Emergency Procedure

1. Press `Kill`.
2. Save `/api/competition/report`.
3. Inspect `data/fidel.sqlite3` and `data/fidel_trades.csv`.
4. Confirm open positions on BscScan and wallet UI.
5. Do not restart live mode until the fault is understood.

## What Makes Fidel Judge-Grade

- Sponsor-stack readiness score.
- Strict live contract registry.
- Risk-adjusted signal ranking.
- CMC confluence across indicators, sentiment, funding, liquidity, and market regime.
- TWAK-only execution boundary.
- Local self-custody signing requirement.
- Execution preflight with slippage, gas, route, and warnings.
- SQLite and CSV judge-verifiable logs.
- Daily trade requirement monitor.
- Hard drawdown circuit breaker.
