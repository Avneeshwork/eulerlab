'use client';

/**
 * Paper deployments: each strategy trading forward with its own money.
 *
 * A deployment is brought up to the latest close by `make paper-daily` (part
 * of `make daily`) or by "Run now" here. Every number on a card comes from the
 * deployment's last run (`data/deployments/<id>/state.json`), which the server
 * wrote after checking its book against its broker. A halted card says why in
 * the deployment's own words; nothing here clears a halt.
 */

import { Info } from '@/components/terminal/ui';
import { useCallback, useEffect, useState } from 'react';

import { Spark } from '@/components/terminal/Spark';
import { api } from '@/lib/api';
import type { Deployment, DeploymentState, FleetStrategy } from '@/lib/api';

const rupees = (value: number | undefined) =>
  value === undefined
    ? '—'
    : `${value < 0 ? '−' : ''}₹${Math.abs(Math.round(value)).toLocaleString('en-IN')}`;
const pct = (value: number | undefined, digits = 1) =>
  value === undefined || !Number.isFinite(value)
    ? '—'
    : `${value < 0 ? '−' : '+'}${Math.abs(value * 100).toFixed(digits)}%`;

// The equity curve with deposits and withdrawals taken out, from 1. Plotting
// raw equity drew every deposit as a jump in value (2026-10-17). The same
// rule as `risk/book.py: growth` and the engine's total_return.
function growth(s: DeploymentState, capital: number): number[] {
  const moved = new Map<string, number>();
  for (const flow of s.flows ?? []) {
    if (flow.applied_day) moved.set(flow.applied_day, (moved.get(flow.applied_day) ?? 0) + flow.amount);
  }
  let index = 1;
  let previous = capital;
  return (s.curve ?? []).map(([day, value]) => {
    const base = previous + (moved.get(day) ?? 0);
    if (base > 0) index *= value / base;
    previous = value;
    return index;
  });
}

// The first sentence of a server note; the whole note stays one hover away.
const firstSentence = (text: string) => {
  const cut = text.search(/[.;](\s|$)/);
  return cut > 0 ? text.slice(0, cut + 1) : text;
};

// Long generated titles ("Fixed-rule combination: intraday: when …") cut to one line.
const shortTitle = (text: string, max = 80) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

const STATUS_LABEL: Record<string, string> = {
  ok: 'Up to date',
  waiting: 'Waiting for the next close',
  halted: 'Halted',
  error: 'Run failed',
};

const share = (value: number | null | undefined) =>
  value === null || value === undefined ? 'off' : `${(value * 100).toFixed(0)}%`;

/**
 * The loss limits that act (ADR-092): how far the book is below its high, where
 * it goes reduce-only and where it halts, and the switch to go reduce-only now.
 */
function LossLimits({
  d,
  onAct,
}: {
  d: Deployment;
  onAct: (call: Promise<{ ok: boolean; error?: string }>) => void;
}) {
  const seen = d.state?.loss_limit;
  const limits = d.limits ?? { reduce_at: null, halt_at: null };
  const [editing, setEditing] = useState(false);
  const [reduce, setReduce] = useState('');
  const [halt, setHalt] = useState('');
  const down = seen?.drawdown ?? 0;
  // The bar runs to a little past the halt level, so both marks always show.
  const scale = Math.max(limits.halt_at ?? 0, limits.reduce_at ?? 0, down, 0.05) * 1.15;
  const at = (value: number) => `${Math.min(100, (value / scale) * 100)}%`;
  const tone =
    limits.halt_at !== null && down >= limits.halt_at
      ? 'down'
      : limits.reduce_at !== null && down >= limits.reduce_at
        ? 'caveat'
        : 'brand';
  const parse = (text: string) => (text.trim() === '' ? null : Number(text) / 100);
  return (
    <div className="ll">
      <div className="ll-head">
        <span>
          <b>Loss limits</b>{' '}
          <span className="tfine">
            {seen ? `down ${(down * 100).toFixed(1)}% from its high (worst ${(seen.worst * 100).toFixed(1)}%)` : 'not measured yet'}
            {' · '}reduce-only at {share(limits.reduce_at)} · halt at {share(limits.halt_at)}
          </span>
        </span>
        <span className="ll-acts">
          {d.status === 'active' && (
            <button
              type="button"
              className={`tbtn sm${d.reducing_now ? ' ok' : ''}`}
              disabled={!!d.running}
              title={
                d.reducing_now
                  ? 'Let the strategy buy again from the next session'
                  : 'From the next session: sells go through, buys are refused'
              }
              onClick={() => onAct(api.reduceOnly(d.id, !d.reducing_now))}
            >
              {d.reducing_now ? 'Resume buying' : 'Reduce only'}
            </button>
          )}
          <button
            type="button"
            className="tbtn sm"
            onClick={() => {
              setReduce(limits.reduce_at === null ? '' : String(Math.round(limits.reduce_at * 100)));
              setHalt(limits.halt_at === null ? '' : String(Math.round(limits.halt_at * 100)));
              setEditing((v) => !v);
            }}
          >
            {editing ? 'Cancel' : 'Change'}
          </button>
        </span>
      </div>
      <div className="ll-bar" data-tone={tone} role="img" aria-label={`Down ${(down * 100).toFixed(1)}% from its high`}>
        <i style={{ width: at(down) }} />
        {limits.reduce_at !== null && <u className="ll-reduce" style={{ left: at(limits.reduce_at) }} title="reduce-only" />}
        {limits.halt_at !== null && <u className="ll-halt" style={{ left: at(limits.halt_at) }} title="halt" />}
      </div>
      {editing && (
        <form
          className="ll-form"
          onSubmit={(event) => {
            event.preventDefault();
            onAct(api.deploymentLimits(d.id, parse(reduce), parse(halt)));
            setEditing(false);
          }}
        >
          <label>
            Reduce-only at
            <input type="number" min="1" max="99" value={reduce} placeholder="off" onChange={(e) => setReduce(e.target.value)} />%
          </label>
          <label>
            Halt at
            <input type="number" min="1" max="99" value={halt} placeholder="off" onChange={(e) => setHalt(e.target.value)} />%
          </label>
          <button type="submit" className="tbtn sm go">
            Save
          </button>
          <span className="tfine">Empty means off. A drawdown is measured from the book&apos;s own high, deposits and withdrawals taken out.</span>
        </form>
      )}
    </div>
  );
}

export function PaperDeployments({
  fleet,
  onReport,
  onBacktest,
}: {
  fleet: FleetStrategy[];
  /** Open the strategy's backtest report. */
  onBacktest?: (strategyId: string) => void;
  /** Open the deployment's full report, the backtest report's tabs on its own record. */
  onReport?: (deploymentId: string) => void;
}) {
  const [items, setItems] = useState<Deployment[] | null>(null);
  const [problem, setProblem] = useState('');
  const [open, setOpen] = useState<string>('');
  const [flowAmounts, setFlowAmounts] = useState<Record<string, string>>({});
  const [showEnded, setShowEnded] = useState(false);
  const [moneyOpen, setMoneyOpen] = useState('');
  const [limitsOpen, setLimitsOpen] = useState('');

  const load = useCallback(() => {
    api
      .deployments()
      .then((answer) => setItems(answer.deployments))
      .catch((error) => setProblem(error instanceof Error ? error.message : String(error)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Poll only while something is running.
  const busy = (items ?? []).some((d) => d.running);
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(load, 4000);
    return () => window.clearInterval(timer);
  }, [busy, load]);

  const title = (id: string) => fleet.find((s) => s.id === id)?.title ?? id;
  // The backtest beside the paper book: its Sharpe (realistic fills where the
  // server has it, ADR-205) and annual return, linked to the full report.
  const backtestLink = (id: string) => {
    if (!onBacktest) return null;
    const f = fleet.find((x) => x.id === id);
    const sharpe = f
      ? ((f as FleetStrategy & { realistic?: { sharpe: number } | null }).realistic?.sharpe ?? f.sharpe)
      : null;
    const annual = f?.table?.annual_return;
    const figures =
      sharpe === null
        ? ' report'
        : `: Sharpe ${sharpe.toFixed(2)}${annual !== null && annual !== undefined ? ` · ${pct(annual)}/yr` : ''}`;
    return (
      <button className="tlink paper-bt" type="button" onClick={() => onBacktest(id)}>
        Backtest{figures} →
      </button>
    );
  };
  // A refused action's reason stays on screen: the reload after it used to
  // clear it at once, so a refusal looked like nothing happening.
  const act = (call: Promise<{ ok: boolean; error?: string }>) =>
    call
      .then((answer) => {
        setProblem(answer.ok ? '' : (answer.error ?? 'failed'));
        load();
      })
      .catch((error) => setProblem(error instanceof Error ? error.message : String(error)));

  // Only books that are trading get a full card. Stopped and halted books trade
  // nothing, so they fold into one line each under a toggle (2026-11-16).
  const trading = (items ?? []).filter((d) => d.status === 'active');
  const ended = (items ?? []).filter((d) => d.status !== 'active');

  const card = (d: Deployment) => {
    const s = d.state ?? {};
    const status = d.running
      ? 'running'
      : d.status !== 'active'
        ? d.status
        : (s.status ?? 'waiting');
    const isOpen = open === d.id;
    // The lock note ("code changed since it was deployed") is an engineering
    // chore (`make relock`), not something to read on every card: hidden here.
    const notes = (s.warnings ?? []).filter((w) => !w.includes('changed since it was deployed'));
    const drawdown = s.loss_limit?.drawdown ?? 0;
    const reduceAt = d.limits?.reduce_at ?? null;
    const limitHit = reduceAt !== null && drawdown >= reduceAt;
    return (
      <article key={d.id} className="paper-card" data-status={status}>
        <header>
          <div>
            <b title={title(d.strategy_id)}>{shortTitle(title(d.strategy_id))}</b>
            <span className="tfine">
              {d.mode === 'live' ? 'Live' : 'Paper'} · {rupees(d.capital)} · started {d.start} ·{' '}
              {backtestLink(d.strategy_id)}
            </span>
          </div>
          {d.reducing_now && d.status === 'active' && (
            <span className="tbadge" data-tone="caveat" title="Sells go through; buys are refused">
              Reduce-only
            </span>
          )}
          <span className={`paper-badge s-${status}`}>
            {d.running
              ? d.running === 'queued'
                ? 'Queued'
                : 'Running…'
              : d.status === 'stopped'
                ? 'Stopped'
                : (STATUS_LABEL[status] ?? status)}
          </span>
        </header>

        <div className="paper-stats">
          <div>
            <span>Equity</span>
            <b>{rupees(s.equity)}</b>
          </div>
          <div>
            <span>Return</span>
            <b className={(s.total_return ?? 0) >= 0 ? 'pos' : 'neg'}>{pct(s.total_return)}</b>
          </div>
          <div>
            <span>Cash</span>
            <b>{rupees(s.cash)}</b>
          </div>
          <div>
            <span>
              Put in<Info>Starting capital plus deposits, less withdrawals.</Info>
            </span>
            <b>{rupees(s.invested ?? d.capital)}</b>
          </div>
          {s.equity !== undefined && (
            <div>
              <span>
                Made<Info>Equity less the money put in: deposits and withdrawals are not profit.</Info>
              </span>
              <b className={s.equity - (s.invested ?? d.capital) >= 0 ? 'pos' : 'neg'}>{rupees(s.equity - (s.invested ?? d.capital))}</b>
            </div>
          )}
          <div>
            <span>Costs paid</span>
            <b>{rupees(s.costs)}</b>
          </div>
          <div>
            <span>Traded through</span>
            <b>{s.traded_through ?? '—'}</b>
          </div>
          <div>
            <span>Next rebalance</span>
            <b className="small">{s.next_rebalance ?? '—'}</b>
          </div>
          {s.curve && s.curve.length > 1 && (
            <div className="paper-spark">
              <Spark curve={growth(s, d.capital)} clears={false} width={140} height={34} />
            </div>
          )}
        </div>

        {limitsOpen === d.id && <LossLimits d={d} onAct={act} />}

        {(d.status_reason || s.reason) && status !== 'ok' && (
          <div className="tnote bad">{d.status_reason || s.reason}</div>
        )}
        {notes.length > 0 && (
          <div className="tnote warn">
            {firstSentence(notes[0])}
            {notes.length > 1 && ` (+${notes.length - 1} more)`}
            <Info>{notes.join(' ')}</Info>
          </div>
        )}
        {s.intended && s.intended.wanted !== undefined && (
          <p className="tfine">
            Wanted {s.intended.wanted} · buys {s.intended.affordable}
            <Info>
              At the last close the strategy wanted {s.intended.wanted} names;{' '}
              {s.intended.affordable === s.intended.wanted
                ? 'the capital buys all of them.'
                : `the capital buys the top ${s.intended.affordable}. Left out: ${(s.intended.cut ?? []).join(', ')}.`}
            </Info>
          </p>
        )}

        <div className="paper-actions">
          {onReport && (
            <button
              className="tbtn sm go"
              type="button"
              disabled={!s.curve?.length}
              onClick={() => onReport(d.id)}
              title="The backtest report's tabs on this deployment's own record, beside its backtest"
            >
              Detailed analysis
            </button>
          )}
          <button className="tbtn sm" type="button" onClick={() => setOpen(isOpen ? '' : d.id)}>
            {isOpen ? 'Hide' : 'Positions & orders'}
          </button>
          <button
            className={`tbtn sm${limitHit ? ' danger' : ''}`}
            type="button"
            onClick={() => setLimitsOpen(limitsOpen === d.id ? '' : d.id)}
            title={`Down ${((s.loss_limit?.drawdown ?? 0) * 100).toFixed(1)}% from its high`}
          >
            {limitsOpen === d.id ? 'Close limits' : limitHit ? 'Loss limit hit' : 'Loss limits'}
          </button>
          {d.mode === 'paper' && d.status === 'active' && (
            <button className="tbtn sm" type="button" onClick={() => setMoneyOpen(moneyOpen === d.id ? '' : d.id)}>
              {moneyOpen === d.id ? 'Close' : 'Add / withdraw'}
            </button>
          )}
          <button
            className="tbtn sm"
            type="button"
            disabled={d.status !== 'active' || !!d.running}
            onClick={() => act(api.runDeployment(d.id))}
            title="Bring it up to the latest close now. Safe to repeat: nothing is sent twice."
          >
            Run now
          </button>
          <button
            className="tbtn sm ghost-line"
            type="button"
            disabled={d.status !== 'active'}
            onClick={() => act(api.stopDeployment(d.id))}
            title="Stop trading. Positions are kept, nothing is sold."
          >
            Stop
          </button>
        </div>

        {moneyOpen === d.id && (
          <div className="paper-actions">
          <input
            aria-label={`Cash flow amount for ${title(d.strategy_id)}`}
            className="tinput sm"
            inputMode="decimal"
            min="1"
            placeholder="Amount ₹"
            type="number"
            value={flowAmounts[d.id] ?? ''}
            onChange={(event) =>
              setFlowAmounts((current) => ({ ...current, [d.id]: event.target.value }))
            }
          />
          <button
            className="tbtn sm"
            type="button"
            disabled={d.mode !== 'paper' || d.status !== 'active' || !!d.running || !(Number(flowAmounts[d.id]) > 0)}
            onClick={() =>
              act(api.deploymentFlow(d.id, 'add', Number(flowAmounts[d.id])))
            }
          >
            Add money
          </button>
          <button
            className="tbtn sm"
            type="button"
            disabled={d.mode !== 'paper' || d.status !== 'active' || !!d.running || !(Number(flowAmounts[d.id]) > 0)}
            onClick={() =>
              act(api.deploymentFlow(d.id, 'withdraw', Number(flowAmounts[d.id])))
            }
          >
            Withdraw
          </button>
          </div>
        )}

        {(s.pending?.length ?? 0) > 0 && (
          <div className="tfine">
            {s.pending?.map((flow) => (
              <div key={`${flow.entered_at}-${flow.last_decided}`}>
                pending: {flow.amount >= 0 ? '+' : '−'}{rupees(Math.abs(flow.amount))} at the next decision
              </div>
            ))}
          </div>
        )}
        {(s.flows?.length ?? 0) > 0 && (
          <div className="tfine">
            <b>Capital flows</b>
            {s.flows?.map((flow) => (
              <div key={`${flow.entered_at}-${flow.last_decided}`}>
                {flow.amount >= 0 ? 'Added' : 'Withdrew'} {rupees(Math.abs(flow.amount))}
                {flow.applied_day ? ` · applied ${flow.applied_day}` : ''}
              </div>
            ))}
          </div>
        )}

        {isOpen && (
          <div className="paper-detail">
            <table className="ttable">
              <thead>
                <tr>
                  <th>Holding</th>
                  <th className="r">Shares</th>
                  <th className="r">Avg cost</th>
                  <th className="r">Last</th>
                  <th className="r">Value</th>
                  <th className="r">Weight</th>
                </tr>
              </thead>
              <tbody>
                {(s.book ?? []).map((p) => (
                  <tr key={p.symbol}>
                    <td>
                      <a className="tsym" href={`/terminal/company/${encodeURIComponent(p.symbol)}`}>
                        {p.symbol}
                      </a>
                    </td>
                    <td className="r">{p.quantity}</td>
                    <td className="r">{p.average_price?.toFixed(2) ?? '—'}</td>
                    <td className="r">{p.last_price.toFixed(2)}</td>
                    <td className="r">{rupees(p.value)}</td>
                    <td className="r">{(p.weight * 100).toFixed(1)}%</td>
                  </tr>
                ))}
                {(s.book ?? []).length === 0 && (
                  <tr>
                    <td colSpan={6} className="tdim">
                      No positions yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            <h4>Recent fills ({s.fills_total ?? 0} in all)</h4>
            <table className="ttable">
              <thead>
                <tr>
                  <th>Day</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th className="r">Shares</th>
                  <th className="r">Price</th>
                  <th className="r">Cost</th>
                </tr>
              </thead>
              <tbody>
                {(s.fills ?? [])
                  .slice(-15)
                  .reverse()
                  .map((f, i) => (
                    <tr key={`${f.day}-${f.symbol}-${i}`}>
                      <td>{f.day}</td>
                      <td>
                        <a className="tsym" href={`/terminal/company/${encodeURIComponent(f.symbol)}`}>
                          {f.symbol}
                        </a>
                      </td>
                      <td className={f.side === 'buy' ? 'pos' : 'neg'}>{f.side}</td>
                      <td className="r">{f.quantity}</td>
                      <td className="r">{f.price.toFixed(2)}</td>
                      <td className="r">{f.cost.toFixed(2)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
            {(s.rejections ?? []).length > 0 && (
              <p className="tfine">
                Rejected {(s.rejections ?? []).length}
                <Info>{(s.rejections ?? []).map((r) => `${r.symbol} on ${r.day} (${r.reason})`).join('; ')}</Info>
              </p>
            )}
          </div>
        )}
      </article>
    );
  };

  return (
    <div className="tpanel paper">
      <h3>
        Paper trading <span className="tfine">{trading.length} trading</span>
      </h3>
      {problem && <div className="tnote bad">{problem}</div>}
      {items === null && !problem && <div className="tempty">Reading deployments…</div>}
      {items && trading.length === 0 && (
        <div className="tempty">Nothing is paper-trading. Open a strategy and choose Deploy → Paper.</div>
      )}
      {trading.map(card)}
      {ended.length > 0 && (
        <>
          <button className="tbtn sm ghost-line" type="button" onClick={() => setShowEnded((v) => !v)}>
            {showEnded ? 'Hide' : 'Show'} {ended.length} stopped or halted
          </button>
          {showEnded && (
            <table className="ttable paper-ended">
              <tbody>
                {ended.map((d) => (
                  <tr key={d.id}>
                    <td title={title(d.strategy_id)}>
                      <b>{shortTitle(title(d.strategy_id))}</b>
                      <div className="tfine">
                        {rupees(d.capital)} · started {d.start} · {backtestLink(d.strategy_id)}
                      </div>
                    </td>
                    <td>
                      <span className={`paper-badge s-${d.status}`}>
                        {d.status === 'stopped' ? 'Stopped' : (STATUS_LABEL[d.status] ?? d.status)}
                      </span>
                    </td>
                    <td className="tfine" title={d.status_reason || d.state?.reason || ''}>
                      {firstSentence(d.status_reason || d.state?.reason || '')}
                    </td>
                    <td className="r">
                      {onReport && (
                        <button
                          className="tbtn sm"
                          type="button"
                          disabled={!d.state?.curve?.length}
                          onClick={() => onReport(d.id)}
                        >
                          Report
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}
