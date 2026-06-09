import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, AlertTriangle, CheckCircle2, Download, Gauge, Moon, Pause, Play, Power, Radio, Route, Shield, Sun, Wallet } from "lucide-react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import "./styles.css";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
const WS = API.replace("http", "ws") + "/ws";

function money(value) {
  return `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function pct(value) {
  return `${Number(value || 0).toFixed(2)}%`;
}

function App() {
  const [state, setState] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem("fidel-theme") || "professional");

  useEffect(() => {
    fetch(`${API}/api/state`).then((r) => r.json()).then(setState).catch(() => {});
    const socket = new WebSocket(WS);
    socket.onmessage = (event) => setState(JSON.parse(event.data));
    const timer = setInterval(() => {
      if (socket.readyState !== 1) fetch(`${API}/api/state`).then((r) => r.json()).then(setState).catch(() => {});
    }, 5000);
    return () => {
      clearInterval(timer);
      socket.close();
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("fidel-theme", theme);
  }, [theme]);

  const chartData = useMemo(() => {
    const trades = [...(state?.trades || [])].reverse();
    if (!trades.length && state?.portfolio) return [{ name: "Start", value: state.portfolio.starting_value }, { name: "Now", value: state.portfolio.value }];
    return trades.map((trade, index) => ({ name: String(index + 1), value: Number(trade.portfolio_after || 0) }));
  }, [state]);

  async function action(path) {
    const res = await fetch(`${API}${path}`, { method: "POST" });
    setState(await fetch(`${API}/api/state`).then((r) => r.json()));
    return res;
  }

  if (!state) return <div className="boot">Fidel is loading market telemetry...</div>;
  const dd = state.portfolio.drawdown_pct;
  const ddClass = dd >= 20 ? "danger" : dd >= 15 ? "warn" : "ok";

  return (
    <main>
      <header className="topbar">
        <div>
          <h1>Fidel</h1>
          <p>Autonomous AI Trading Agent for BNB Hack Track 1</p>
        </div>
        <div className={`status ${state.agent.status.toLowerCase()}`}><Radio size={16} />{state.agent.status}</div>
        <button title="Start agent" onClick={() => action("/api/agent/start")}><Play size={18} />Start</button>
        <button title="Pause agent" onClick={() => action("/api/agent/pause")}><Pause size={18} />Pause</button>
        <button title="Stop agent" onClick={() => action("/api/agent/stop")}><Power size={18} />Stop</button>
        <button className="dangerBtn" title="Emergency stop and lock circuit breaker" onClick={() => action("/api/agent/emergency-stop")}><Shield size={18} />Kill</button>
        <button title="Change theme" onClick={() => setTheme(theme === "professional" ? "dark" : "professional")}>{theme === "professional" ? <Moon size={18} /> : <Sun size={18} />}{theme === "professional" ? "Dark" : "Light"}</button>
      </header>

      <section className="metrics">
        <Metric label="Portfolio Value" value={money(state.portfolio.value)} sub={`PnL ${money(state.portfolio.total_pnl)} (${pct(state.portfolio.total_return_pct)})`} icon={<Wallet />} />
        <Metric label="Drawdown Gate" value={pct(dd)} sub={`Max allowed ${pct(state.portfolio.max_drawdown_pct)}`} icon={<Shield />} tone={ddClass} />
        <Metric label="Daily Trade Count" value={`${state.today_trades}/1`} sub="Minimum required per UTC day" icon={<Activity />} />
        <Metric label="Win Rate" value={pct(state.win_rate)} sub={`${state.trades.length} verifiable BSC trades logged`} />
        <Metric label="Fear & Greed" value={state.fear_greed} sub={state.market_regime} />
        <Metric label="Session" value={state.session} sub={`Minimum confidence ${state.min_confidence}%`} />
      </section>

      <section className="heroGrid">
        <Panel title="Judging Scorecard">
          <div className="scorecard">
            <div className="scoreRing"><Gauge size={28} /><strong>{state.judging.score}</strong><span>/ {state.judging.possible}</span></div>
            <div>
              <h3>{state.judging.grade}</h3>
              <p>{state.judging.missing.length ? `Missing: ${state.judging.missing.join(", ")}` : "All critical judging gates are satisfied."}</p>
            </div>
          </div>
          <div className="judgeItems">{state.judging.items.map((item) => <Ready key={item.name} label={`${item.name} (${item.earned}/${item.points})`} on={item.status === "PASS"} />)}</div>
        </Panel>
        <Panel title="Survival Plan">
          <div className="survival">
            <Metric label="Drawdown Left" value={pct(state.survival.drawdown_left_pct)} sub={state.survival.risk_posture} tone={state.survival.drawdown_left_pct <= 7 ? "danger" : state.survival.drawdown_left_pct <= 12 ? "warn" : "ok"} />
            <Metric label="Position Slots" value={state.survival.open_position_slots} sub="Max 3 open positions" />
            <Metric label="Trade Deadline" value={state.survival.daily_trade_requirement_met ? "Met" : "Pending"} sub={state.survival.minimum_trade_deadline} tone={state.survival.daily_trade_requirement_met ? "ok" : "warn"} />
          </div>
        </Panel>
      </section>

      {state.agent.last_error && <div className="banner"><AlertTriangle size={18} />{state.agent.last_error}</div>}
      {dd >= 20 && <div className="banner danger"><AlertTriangle size={18} />Drawdown warning active. Fidel will stop all trading at 25%.</div>}
      {state.agent.status === "STOPPED" && state.portfolio.drawdown_pct >= state.portfolio.max_drawdown_pct && <div className="banner danger"><AlertTriangle size={18} />Circuit breaker is locked. Review logs before any restart.</div>}

      <section className="grid">
        <Panel title="Portfolio Growth">
          <div className="chart">
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={chartData}>
                <XAxis dataKey="name" stroke="var(--muted)" />
                <YAxis stroke="var(--muted)" domain={["auto", "auto"]} />
                <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)", color: "var(--text)" }} />
                <Area type="monotone" dataKey="value" stroke="var(--accent)" fill="var(--chart-fill)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <Panel title="Signal Feed">
          <div className="signalList">
            {state.signals.map((s) => <SignalRow key={s.symbol} signal={s} />)}
          </div>
        </Panel>
      </section>

      <section className="grid">
        <Panel title="Competition Readiness">
          <div className="readiness">
            <Ready label="CMC Agent Hub" on={state.compliance.cmc_agent_hub} />
            <Ready label="Trust Wallet Agent Kit" on={state.compliance.twak} />
            <Ready label="BNB AI Agent SDK" on={state.compliance.bnb_ai_agent_sdk} />
            <Ready label="LLM Reasoning" on={state.compliance.llm_reasoning} />
            <Ready label="Strict Live Contracts" on={state.compliance.strict_live_contracts} />
            <Ready label="Autonomous Live" on={state.compliance.autonomous_live} />
          </div>
        </Panel>
        <Panel title="Token Registry">
          <div className="registry">
            <Metric label="Seed Symbols" value={state.token_registry.seed_symbols} sub="Competition allowlist seed" />
            <Metric label="Contract Ready" value={state.token_registry.contract_ready} sub="BSC addresses loaded" />
            <Metric label="External Registry" value={state.token_registry.external_registry_loaded ? "Loaded" : "Missing"} sub={state.token_registry.registry_path} tone={state.token_registry.external_registry_loaded ? "ok" : "warn"} />
          </div>
        </Panel>
      </section>

      <section className="grid">
        <Panel title="Execution Preflight">
          <div className={`preflight ${state.execution_preview.approved ? "yes" : "no"}`}>
            <Route size={22} />
            <div>
              <strong>{state.execution_preview.venue || "No route selected"}</strong>
              <span>{(state.execution_preview.route || []).join(" -> ") || "Waiting for approved signal"}</span>
            </div>
            <b>{state.execution_preview.approved ? "APPROVED" : "BLOCKED"}</b>
          </div>
          <div className="registry">
            <Metric label="Slippage" value={`${state.execution_preview.estimated_slippage_bps || 0} bps`} sub={`Max ${state.execution_preview.max_slippage_bps || 0} bps`} />
            <Metric label="Gas Estimate" value={money(state.execution_preview.estimated_gas_usdt)} sub="BSC execution cost" />
            <Metric label="Price Impact" value={pct(state.execution_preview.price_impact_pct)} sub="Pre-trade route impact" />
          </div>
          {(state.execution_preview.warnings || []).length > 0 && <div className="warnings">{state.execution_preview.warnings.map((w, i) => <p key={i}>{w}</p>)}</div>}
        </Panel>
        <Panel title="Submission Brief">
          <div className="brief">
            <p><strong>{state.judging.submission_brief.agent_name}</strong> · {state.judging.submission_brief.track}</p>
            <p>{state.judging.submission_brief.venue}</p>
            <p>{state.judging.submission_brief.trading_window}</p>
            <div>{state.judging.submission_brief.proofs.map((proof) => <span key={proof}>{proof}</span>)}</div>
          </div>
        </Panel>
      </section>

      <section className="grid wide">
        <Panel title="Open Positions">
          <Table columns={["asset", "entry", "current", "stop loss", "take profit", "unrealized pnl", "tx"]} rows={state.positions.map((p) => [p.symbol, money(p.entry_price), money(p.current_price), money(p.stop_loss), money(p.take_profit), money(p.unrealized_pnl), shortHash(p.tx_hash)])} />
        </Panel>
        <Panel title="Trade History">
          <a className="download" href={`${API}/api/competition/report`}><Download size={16} />Download CSV</a>
          <Table columns={["utc", "token", "side", "size", "pnl", "drawdown", "bsc tx"]} rows={state.trades.map((t) => [t.utc_timestamp, t.token, t.direction, money(t.position_size_usdt), money(t.pnl_usdt), pct(t.drawdown_pct), shortHash(t.bsc_tx_hash)])} />
        </Panel>
      </section>

      <section className="grid">
        <Panel title="Live Activity Log">
          <div className="log">{state.activity.map((line, i) => <p key={i}>{line}</p>)}</div>
        </Panel>
        <Panel title="Eligible Token Watchlist">
          <div className="tokens">{state.eligible_tokens.map((token) => <span key={token}>{token}</span>)}</div>
        </Panel>
      </section>
    </main>
  );
}

function Metric({ label, value, sub, icon, tone = "" }) {
  return <article className={`metric ${tone}`}>{icon && React.cloneElement(icon, { size: 20 })}<span>{label}</span><strong>{value}</strong><small>{sub}</small></article>;
}

function Panel({ title, children }) {
  return <section className="panel"><h2>{title}</h2>{children}</section>;
}

function SignalRow({ signal }) {
  return <article className={`signal ${signal.executable ? "hot" : ""}`}>
    <div><strong>{signal.symbol}</strong><span>{signal.direction} · {signal.strength} · edge {Number(signal.edge_score || 0).toFixed(1)}</span></div>
    <b>{signal.confidence}%</b>
    <p>{signal.reasoning}</p>
  </article>;
}

function Ready({ label, on }) {
  return <div className={`ready ${on ? "yes" : "no"}`}><CheckCircle2 size={17} /><span>{label}</span><strong>{on ? "READY" : "NEEDS CONFIG"}</strong></div>;
}

function Table({ columns, rows }) {
  return <div className="table"><table><thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c || "—"}</td>)}</tr>)}</tbody></table></div>;
}

function shortHash(hash) {
  return hash ? `${hash.slice(0, 8)}...${hash.slice(-6)}` : "pending";
}

createRoot(document.getElementById("root")).render(<App />);
