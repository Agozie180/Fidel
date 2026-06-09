# Fidel Architecture

## System Overview

Fidel has a Python FastAPI backend and a React dashboard.

Component diagram in text:

`CMC Agent Hub / CMC MCP / x402 data` -> `SignalEngine` -> `AI ReasoningLayer` -> `RiskManager` -> `TrustWalletExecutor` -> `BNB Smart Chain / PancakeSwap` -> `CompetitionLogger` -> `React WebSocket Dashboard`.

`BnbAgentCoordinator` owns lifecycle heartbeats and BSC agent coordination. `CompetitionRegistrar` registers the wallet with the BNB competition contract.

## Data Flow

1. `CmcAgentHubClient` requests price quotes, 24h change, RSI, MACD, EMA, ATR, Fear and Greed, sentiment, liquidity, funding, open interest, narratives, and social signals. The adapter sends x402-ready headers for CMC HTTP calls and supports `CMC_MCP_COMMAND` for MCP snapshots.
2. `SignalEngine` validates each symbol against the eligible-token allowlist, evaluates confluence, and ranks opportunities every 60 seconds.
3. `ReasoningLayer` calls Anthropic or OpenAI to produce a plain-English decision summary for the chosen opportunity. Without an LLM key it falls back to a deterministic explanation in development mode.
4. `RiskManager` enforces drawdown, daily loss, max position, max open positions, stop-loss, take-profit, volatility, feed, and connection gates.
5. `TrustWalletExecutor` is the sole live execution boundary. In live mode it calls TWAK with local signing, autonomous execution, x402, MCP actions, and LangChain flags.
6. `CompetitionLogger` writes every trade to SQLite and CSV with BSC transaction hash, CMC data snapshot, signal confidence, drawdown, portfolio values, and AI reasoning.
7. FastAPI broadcasts state to the React dashboard over WebSocket.

## Risk Decision Tree

For every candidate trade:

1. Reject if token is not eligible.
2. Stop if portfolio value is at or below $1.
3. Stop if drawdown is at or above 25%.
4. Reject and warn if drawdown is above 20%.
5. Pause for 30 minutes after 3 consecutive losses.
6. Reject if CMC feed or BSC/TWAK path is unavailable in live mode.
7. Reject if maximum 3 open positions is reached.
8. Reject if signal is not STRONG or EXTREME.
9. Reject if session confidence threshold is not met.
10. Reject if 5-minute volatility proxy exceeds 10%.
11. Size position using current portfolio value, ATR stop distance, and max 2% notional.
12. Preserve more than $1 cash safety floor.
13. Approve only after all checks pass.

## Signal Engine

BUY requires at least four bullish factors:

- RSI oversold or bullish momentum.
- MACD bullish crossover.
- EMA 9 above EMA 21.
- Price above Bollinger middle.
- Positive funding pressure.
- Fear and Greed above 45.
- Positive CMC news sentiment.

SELL requires at least four bearish factors. Only STRONG or EXTREME signals can execute. Sessions set dynamic confidence thresholds: Asian 65%, London 72%, New York 75%, Off 60%.

## AI Reasoning Layer

The LLM is not used as a blind executor. It receives the selected signal, top alternatives, CMC snapshot, market regime, sentiment, stop distance, confidence, and session threshold. It explains why the token was selected, why alternatives were not, how market regime affects the trade, how CMC news and sentiment are interpreted, and how position sizing follows ATR and portfolio risk.

## TWAK Self-Custody Flow

1. Signal and risk approval produce a swap intent.
2. Fidel calls TWAK locally.
3. TWAK signs using the local private key from `TRUST_WALLET_PRIVATE_KEY`.
4. The key never leaves the user device and is never logged.
5. TWAK submits the transaction to BSC.
6. Fidel records the returned transaction hash.
7. Stop-loss and take-profit values are passed in the same execution plan so protective controls are attached immediately after confirmation.

## Competition Compliance

- Uses CMC Agent Hub/MCP paths for market data and x402-ready requests.
- Uses TWAK as the live execution layer.
- Provides BNB AI Agent SDK command hook for lifecycle coordination.
- Registers through `twak compete register` against `0x212c61b9b72c95d95bf29cf032f5e5635629aed5`.
- Trades only the eligible allowlist.
- Logs every trade with BSC transaction hash and CMC data snapshot.
- Tracks one trade per UTC day.
- Enforces 25% max drawdown, 5% daily loss limit, 2% max position, 3 open positions, ATR stops, and 1:2 reward/risk.
- Enforces contract-address token registry in live mode so a spoofed or wrong BEP-20 cannot pass by symbol alone.
- Displays sponsor-stack readiness in the dashboard so the operator can see whether CMC, TWAK, BNB SDK, LLM reasoning, autonomous live mode, and strict token contracts are configured.
- Uses a professional light dashboard by default, with a dark option and CSS-variable theming for easy operator branding.

## Source-Audited Requirements

The BNB Chain blog states that Track 1 agents must trade on-chain autonomously on BSC, read markets via CMC, decide, and sign/execute through TWAK under user-defined rules. It also names CMC MCP + Cognitive Layer, Trust Wallet Agent Kit with self-custody local signing/autonomous mode/native x402/LangChain/MCP/REST coverage, BNB AI Agent SDK, and PancakeSwap/BSC perps execution.

The CoinMarketCap hackathon page confirms the same Track 1 stack and adds that teams using all three sponsor stacks have the strongest shot with judges. It describes CMC Agent Hub as Data API, Data MCP, Skills Marketplace, and x402; TWAK as self-custody unattended local signing with MCP/REST and x402; and BNB AI Agent SDK as BSC mainnet, PancakeSwap, and BSC perps primitives.

The user supplied DoraHacks requirement text confirms: public GitHub/GitLab/Bitbucket link is required, Track 1 requires on-chain proof through a BSC agent address, minimum trade count is 1 per day over the June 22-28 trading week, trades outside the fixed eligible-token list do not count, and submissions must explain the strategy. The pasted token text contains 149 list entries with repeated/ambiguous symbols; Fidel stores the official entry count separately from the unique executable registry.

## Failure Handling

- CMC unavailable in live mode: pause/fail closed.
- BSC RPC or TWAK error: no trade is recorded as filled unless a transaction hash is returned.
- LLM unavailable: development mode falls back to deterministic reasoning; live operators should configure Anthropic or OpenAI.
- Drawdown breach: portfolio state is stopped and no further trades are approved.
- Volatility shock: trade rejected.
- WebSocket drop: frontend reconnects through polling fallback.
- Shutdown: state already persisted in SQLite and CSV after each trade.

## BSC Transaction Lifecycle

1. `SignalEngine` selects a token and side.
2. `RiskManager` approves size, stop loss, and take profit.
3. `TrustWalletExecutor` constructs a PancakeSwap BSC swap command.
4. TWAK signs locally.
5. TWAK submits to BSC.
6. Fidel monitors returned status and transaction hash.
7. Trade is written to SQLite and CSV.
8. Dashboard shows the BSC hash for judge verification on `bscscan.com`.
