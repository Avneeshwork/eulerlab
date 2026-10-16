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

import { useCallback, useEffect, useState } from 'react';

import { Spark } from '@/components/terminal/Spark';
import { api } from '@/lib/api';
import type { Deployment, FleetStrategy } from '@/lib/api';

const rupees = (value: number | undefined) =>
  value === undefined ? '—' : `₹${Math.round(value).toLocaleString('en-IN')}`;
const pct = (value: number | undefined, digits = 1) =>
  value === undefined || !Number.isFinite(value)
    ? '—'
    : `${value < 0 ? '−' : '+'}${Math.abs(value * 100).toFixed(digits)}%`;

const STATUS_LABEL: Record<string, string> = {
  ok: 'Up to date',
  waiting: 'Waiting for the next close',
  halted: 'Halted',
  error: 'Run failed',
};

export function PaperDeployments({ fleet }: { fleet: FleetStrategy[] }) {
  const [items, setItems] = useState<Deployment[] | null>(null);
  const [problem, setProblem] = useState('');
  const [open, setOpen] = useState<string>('');
  const [flowAmounts, setFlowAmounts] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    api
      .deployments()
      .then((answer) => {
        setItems(answer.deployments);
        setProblem('');
      })
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
  const act = (call: Promise<{ ok: boolean; error?: string }>) =>
    call
      .then((answer) => {
        if (!answer.ok) setProblem(answer.error ?? 'failed');
        load();
      })
      .catch((error) => setProblem(error instanceof Error ? error.message : String(error)));

  return (
    <div className="tpanel paper">
      <h3>Paper trading</h3>
      {problem && <div className="tnote bad">{problem}</div>}
      {items === null && !problem && <div className="tempty">Reading deployments…</div>}
      {items && items.length === 0 && (
        <div className="tempty">
          Nothing is paper-trading yet. Open a strategy, choose Deploy → Paper, and give it a
          capital amount.
        </div>
      )}
      {items?.map((d) => {
        const s = d.state ?? {};
        const status = d.running
          ? 'running'
          : d.status !== 'active'
            ? d.status
            : (s.status ?? 'waiting');
        const isOpen = open === d.id;
        return (
          <article key={d.id} className="paper-card" data-status={status}>
            <header>
              <div>
                <b>{title(d.strategy_id)}</b>
                <span className="tfine">
                  Paper · {rupees(d.capital)} · started {d.start}
                </span>
              </div>
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
                <span>Invested</span>
                <b>{rupees(s.invested ?? d.capital)}</b>
              </div>
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
                  <Spark curve={s.curve.map(([, v]) => v)} clears={false} width={140} height={34} />
                </div>
              )}
            </div>

            {(d.status_reason || s.reason) && status !== 'ok' && (
              <div className="tnote bad">{d.status_reason || s.reason}</div>
            )}
            {s.warnings?.map((w) => (
              <div key={w} className="tnote warn">
                {w}
              </div>
            ))}
            {s.intended && s.intended.wanted !== undefined && (
              <p className="tfine">
                At the last close the strategy wanted {s.intended.wanted} names;{' '}
                {s.intended.affordable === s.intended.wanted
                  ? 'the capital buys all of them.'
                  : `the capital buys the top ${s.intended.affordable}. Left out: ${(s.intended.cut ?? []).join(', ')}.`}
              </p>
            )}

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
              <button className="tbtn sm" type="button" onClick={() => setOpen(isOpen ? '' : d.id)}>
                {isOpen ? 'Hide' : 'Positions & orders'}
              </button>
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
                    Rejected: {(s.rejections ?? []).map((r) => `${r.symbol} on ${r.day} (${r.reason})`).join('; ')}
                  </p>
                )}
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}
