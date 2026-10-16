'use client';

/**
 * Risk on the deployed book (ADR-071): three views of one payload.
 *
 * Overview says what the book could lose and where that risk sits.
 * Performance says how each deployment is doing against its own backtest.
 * Stress & exposure says what a bad day costs and what the book is
 * concentrated in.
 *
 * Read-only. Every number comes from `/api/risk/book`; nothing here can stop,
 * reduce or place a trade. Rows marked "watch" are warning levels the operator
 * sets in `config/risk_watch.yaml`.
 */

import { useEffect, useMemo, useState } from 'react';

import { api } from '@/lib/api';
import type { RiskBook, RiskBookResponse, RiskDeployment, RiskLimit } from '@/lib/api';
import './riskbook.css';

type View = 'overview' | 'performance' | 'stress';

const SERIES = ['var(--rk-1)', 'var(--rk-2)', 'var(--rk-3)', 'var(--rk-4)', 'var(--rk-5)'];
/** Colour follows the deployment's slot: its place in the order deployments were
 * created, stopped ones included. Adding or stopping one never repaints the rest.
 * A sixth folds to grey. */
const colourOf = (slot: number) => SERIES[slot] ?? 'var(--rk-quiet)';

const rupees = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });

function inr(value: number): string {
  const sign = value < 0 ? '−' : '';
  return `${sign}₹${rupees.format(Math.abs(Math.round(value)))}`;
}

/** ₹21.14 L for a headline; exact rupees below a lakh. */
function lakh(value: number): string {
  if (Math.abs(value) < 100_000) return inr(value);
  return `${value < 0 ? '−' : ''}₹${(Math.abs(value) / 100_000).toFixed(2)} L`;
}

function pct(value: number | null | undefined, digits = 1, signed = false): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const text = `${Math.abs(value * 100).toFixed(digits)}%`;
  if (value < 0) return `−${text}`;
  return signed ? `+${text}` : text;
}

/** A plain percentage for an axis: a true minus sign, two decimals. */
function axisPct(value: number): string {
  return `${value < 0 ? '−' : ''}${Math.abs(value).toFixed(2)}%`;
}

function signedInr(value: number): string {
  return value > 0 ? `+${inr(value)}` : inr(value);
}

const VERDICT: Record<RiskDeployment['against_backtest']['verdict'], string> = {
  inside: 'Inside its band',
  below: 'Below the band',
  above: 'Above the band',
  too_early: 'Too early to say',
  no_backtest: 'No backtest stored',
  not_started: 'Not started',
};

const STATE_LABEL: Record<RiskLimit['state'], string> = { ok: 'OK', near: 'Near', over: 'Over' };

export function RiskBookView({ view }: { view: View }) {
  const [data, setData] = useState<RiskBookResponse | null>(null);
  const [problem, setProblem] = useState('');

  useEffect(() => {
    let live = true;
    api
      .riskBook()
      .then((loaded) => live && setData(loaded))
      .catch((error) => live && setProblem(error instanceof Error ? error.message : String(error)));
    return () => {
      live = false;
    };
  }, []);

  if (problem) return <div className="tnote bad"><span className="mk">▲</span><div>The risk figures could not be read: {problem}</div></div>;
  if (!data) return <div className="tempty">Working out the risk on the deployed book…</div>;
  if (!data.ok) return <div className="tnote bad"><span className="mk">▲</span><div>The risk figures could not be read: {data.error}</div></div>;
  if (data.empty) return <div className="tempty">{data.reason} Deploy a strategy from the Strategies page to see its risk here.</div>;

  return (
    <div className="rk">
      <Caveats risk={data} />
      {view === 'overview' && <Overview risk={data} />}
      {view === 'performance' && <Performance risk={data} />}
      {view === 'stress' && <Stress risk={data} />}
    </div>
  );
}

/** What the figures cannot see, said before they are read. Nothing when all is in order. */
function Caveats({ risk }: { risk: RiskBook }) {
  const flat = risk.deployments.filter((d) => d.flat);
  const flatShare = flat.reduce((sum, d) => sum + d.capital_share, 0);
  const lines: string[] = [];
  if (!risk.enough_history) {
    lines.push(`Only ${risk.history_days} days of prices are held for these names, so no value at risk is given: fewer than 60 days is a guess.`);
  }
  if (flat.length > 0) {
    lines.push(
      `${flat.length === 1 ? `"${flat[0].title}" holds` : `${flat.length} deployments hold`} nothing at the close (${pct(flatShare, 0)} of the money). ` +
        'It adds nothing to these figures.'
    );
  }
  for (const d of risk.deployments.filter((x) => x.gap)) {
    const g = d.gap!;
    lines.push(
      g.notional > 0
        ? `"${d.title}" trades only overnight. It is in these figures as it has been run: in position on ${g.nights_held} of the last ${g.nights} nights. ` +
            (g.holds_tonight ? `It holds ${lakh(g.held_now)} of the future tonight.` : 'It holds nothing tonight.')
        : `"${d.title}" cannot buy one lot of the future with its money, so it carries no risk.`
    );
  }
  if (risk.book.coverage < 0.999) {
    lines.push(`${pct(1 - risk.book.coverage, 0)} of the holdings by value lack a full year of prices; those names count as flat on the days they are missing.`);
  }
  if (lines.length === 0) return null;
  return (
    <div className="rk-note" role="note">
      {lines.map((line) => (
        <div key={line}>{line}</div>
      ))}
    </div>
  );
}

function Overview({ risk }: { risk: RiskBook }) {
  const b = risk.book;
  const historical = risk.var.methods[0];
  return (
    <>
      <section className="rk-tiles" aria-label="The book in one line">
        <div className="rk-tile">
          <span>Equity</span>
          <b>{lakh(b.equity)}</b>
          <span>on {lakh(b.capital)} deployed · {b.deployments} deployment{b.deployments === 1 ? '' : 's'}</span>
        </div>
        <div className="rk-tile">
          <span>Last session{risk.as_of ? `, ${risk.as_of}` : ''}</span>
          <b className={b.today > 0 ? 'rk-up' : b.today < 0 ? 'rk-down' : ''}>{signedInr(b.today)}</b>
          <span>{pct(b.today_pct, 2, true)} · since start {signedInr(b.since_start)} ({pct(b.since_start_pct, 2, true)})</span>
        </div>
        <div className="rk-tile">
          <span>VaR, 1 day, 95%</span>
          <b>{risk.enough_history ? inr(b.var95) : '—'}</b>
          <span>{risk.enough_history ? `${pct(b.var95_pct, 2)} of equity` : 'not enough history'}</span>
        </div>
        <div className="rk-tile">
          <span>Expected shortfall, 95%</span>
          <b>{risk.enough_history ? inr(b.es95) : '—'}</b>
          <span>average loss on the worst 1 day in 20</span>
        </div>
        <div className="rk-tile">
          <span>Invested</span>
          <b>{pct(b.exposure, 1)}</b>
          <span>{lakh(b.invested)} in {b.names} names · {lakh(b.cash)} cash</span>
        </div>
        <div className="rk-tile">
          <span>Drawdown now</span>
          <b>{pct(b.drawdown.now, 1)}</b>
          <span>deepest so far {pct(b.drawdown.deepest, 1)}{b.drawdown.deepest_day ? ` on ${b.drawdown.deepest_day}` : ''}</span>
        </div>
      </section>

      {risk.enough_history && historical && (
        <div className="rk-row">
          <section className="rk-card wide">
            <h3>Value at risk</h3>
            <p className="rk-sub">
              Today&rsquo;s holdings run through the last {risk.history_days} trading days. Each bar is how many of those days would have ended in that range.
            </p>
            <Histogram risk={risk} />
            <div className="rk-legend">
              <span className="rk-key"><span className="rk-dot" style={{ background: 'var(--rk-1)' }} />Days inside the 95% range</span>
              <span className="rk-key"><span className="rk-dot" style={{ background: 'var(--rk-loss)' }} />Days beyond it</span>
              {risk.var.worst_day && (
                <span>Worst of the {risk.history_days}: {inr(risk.var.worst_day.pnl)} ({pct(risk.var.worst_day.pct, 2)}) on {risk.var.worst_day.day}</span>
              )}
            </div>
          </section>

          <section className="rk-card narrow">
            <h3>The same question, three ways</h3>
            <p className="rk-sub">When the methods disagree, the largest is the one to plan around.</p>
            <div className="rk-scroll">
              <table className="rk-table">
                <thead>
                  <tr><th scope="col">One day</th><th scope="col">95% VaR</th><th scope="col">99% VaR</th><th scope="col">Shortfall 95%</th></tr>
                </thead>
                <tbody className="rk-num">
                  {risk.var.methods.map((m) => (
                    <tr key={m.method}><td>{m.label}</td><td>{inr(m.var95)}</td><td>{inr(m.var99)}</td><td>{inr(m.es95)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            {b.deployments > 1 && (
              <div className="rk-call">
                <b>Holding them together saves {inr(Math.max(0, b.diversification))}.</b> The deployments&rsquo; own VaRs add up to {inr(b.standalone_sum)}; as one book it is {inr(b.var95)}, because they do not all lose on the same days.
              </div>
            )}
            <p className="rk-fine" style={{ marginTop: 12 }}>
              VaR is the loss to expect to exceed on one day in twenty. It says nothing about how bad that day gets; the shortfall column does.
            </p>
          </section>
        </div>
      )}

      {risk.deployments.filter((d) => d.gap && d.gap.notional > 0).map((d) => (
        <GapCard key={d.id} deployment={d} risk={risk} />
      ))}

      <div className="rk-row">
        <section className="rk-card wide">
          <h3>Where the risk is</h3>
          <p className="rk-sub">
            Each deployment&rsquo;s share of the money beside its share of the VaR. A risk bar much longer than its money bar means it carries more than its size suggests.
          </p>
          <div className="rk-legend" style={{ marginTop: 0, marginBottom: 12 }}>
            <span className="rk-key"><span className="rk-dot" style={{ background: 'var(--rk-quiet)' }} />Share of the money</span>
            <span className="rk-key"><span className="rk-dot" style={{ background: 'var(--rk-1)' }} />Share of the VaR</span>
          </div>
          <div className="rk-bars">
            {risk.deployments.map((d) => (
              <div className="rk-bar-row" key={d.id}>
                <div className="rk-bar-name" title={d.title}>{d.title}</div>
                <div className="rk-bar-track rk-pair">
                  <div><div className="rk-bar" style={{ width: `${Math.max(0, d.capital_share) * 100}%`, background: 'var(--rk-quiet)' }} /><span>{pct(d.capital_share, 0)}</span></div>
                  <div><div className="rk-bar" style={{ width: `${Math.max(0, Math.min(1, d.var_share)) * 100}%`, background: 'var(--rk-1)' }} /><span>{risk.enough_history ? pct(d.var_share, 0) : '—'}</span></div>
                </div>
                <div className="rk-bar-value" title="Rupees this deployment adds to the book's VaR">{risk.enough_history ? inr(d.var_component) : '—'}</div>
              </div>
            ))}
          </div>
          <p className="rk-fine" style={{ marginTop: 14 }}>Right column: the rupees each deployment adds to the book&rsquo;s VaR. They sum to the total.</p>
        </section>

        <section className="rk-card narrow">
          <h3>Allocation</h3>
          <p className="rk-sub">Where the {lakh(b.equity)} is right now.</p>
          <div className="rk-stack" role="img" aria-label={risk.deployments.map((d) => `${d.title} ${pct(d.capital_share, 0)}`).join(', ')}>
            {risk.deployments.map((d) => (
              <div key={d.id} style={{ flex: Math.max(d.capital_share, 0.004), background: colourOf(d.slot) }} title={`${d.title}: ${pct(d.capital_share, 1)}`} />
            ))}
          </div>
          <div className="rk-list">
            {risk.deployments.map((d) => (
              <div key={d.id}>
                <span className="rk-dot" style={{ background: colourOf(d.slot) }} />
                <span className="grow" title={d.title}>{d.title}</span>
                <span className="rk-num">{lakh(d.equity)} · {pct(d.capital_share, 0)}</span>
              </div>
            ))}
          </div>
          <div className="rk-facts">
            <div><span>Names held</span><b className="rk-num">{b.names}</b></div>
            <div><span>Held by more than one deployment</span><b className="rk-num">{b.shared_names}</b></div>
            <div><span>Largest name</span><b className="rk-num">{risk.names[0] ? `${risk.names[0].symbol} · ${pct(risk.names[0].share, 1)}` : '—'}</b></div>
            <div><span>Largest sector, of what is invested</span><b className="rk-num">{risk.sectors[0] ? `${risk.sectors[0].sector} · ${pct(risk.sectors[0].share, 0)}` : '—'}</b></div>
          </div>
        </section>
      </div>

      <section className="rk-card">
        <h3>Limits and headroom</h3>
        <p className="rk-sub">Every limit, how much of it is used, and what happens when it is reached. {risk.watch_note}</p>
        <div className="rk-scroll">
          <table className="rk-table" style={{ minWidth: 760 }}>
            <thead>
              <tr><th scope="col">Limit</th><th scope="col" className="l" style={{ width: '24%' }}>Used</th><th scope="col">Now</th><th scope="col">Limit</th><th scope="col" className="l">State</th><th scope="col" className="l">When reached</th></tr>
            </thead>
            <tbody>
              {risk.limits.map((row) => (
                <tr key={row.name}>
                  <td className="name" title={row.name}>{row.name} <span className="rk-fine">· {row.kind === 'watch' ? 'watch' : 'kill switch'}</span></td>
                  <td className="l"><div className="rk-meter" data-state={row.state}><div style={{ width: `${Math.min(1, row.used) * 100}%` }} /></div></td>
                  <td className="rk-num">{row.unit === 'INR' ? inr(row.now) : `${row.now.toFixed(2)}%`}</td>
                  <td className="rk-num">{row.unit === 'INR' ? inr(row.limit) : `${row.limit.toFixed(2)}%`}</td>
                  <td className="l"><span className="rk-pill" data-state={row.state}><span aria-hidden="true">{row.state === 'ok' ? '●' : '▲'}</span>{STATE_LABEL[row.state]}, {pct(row.used, 0)}</span></td>
                  <td className="l rk-fine">{row.when}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

/** The overnight future: what one night in position can cost (ADR-072). */
function GapCard({ deployment, risk }: { deployment: RiskDeployment; risk: RiskBook }) {
  const g = deployment.gap!;
  const dailyLoss = risk.limits.find((row) => row.name === 'Loss today');
  const over = dailyLoss && g.enough && g.var95_when_held > dailyLoss.limit;
  return (
    <section className="rk-card">
      <h3>Gap risk: the overnight future</h3>
      <p className="rk-sub">
        {deployment.title}. It buys {g.lots} lot{g.lots === 1 ? '' : 's'} of {g.contract} ({g.lot_size} units a lot, {lakh(g.notional)}) at the close on a signal day and sells at the next open. Whatever the market does in between, it takes in full.
      </p>
      <div className="rk-tiles">
        <div className="rk-tile">
          <span>Tonight</span>
          <b>{g.holds_tonight ? lakh(g.held_now) : 'Not held'}</b>
          <span>{g.holds_tonight ? 'in position until the open' : 'no signal on the last close'}</span>
        </div>
        <div className="rk-tile">
          <span>VaR on a night it holds, 95%</span>
          <b>{g.enough ? inr(g.var95_when_held) : '—'}</b>
          <span>{g.enough ? `from the ${g.nights_held} nights it held, of the last ${g.nights}` : `only ${g.nights_held} nights held: too few`}</span>
        </div>
        <div className="rk-tile">
          <span>Expected shortfall on such a night</span>
          <b>{g.enough ? inr(g.es95_when_held) : '—'}</b>
          <span>average of its worst 1 night in 20</span>
        </div>
        <div className="rk-tile">
          <span>Worst night it held, last year</span>
          <b>{g.worst_night ? inr(g.worst_night.pnl) : '—'}</b>
          <span>{g.worst_night ? `the open of ${g.worst_night.day}` : 'no losing night'}</span>
        </div>
        <div className="rk-tile">
          <span>Worst gap on record</span>
          <b>{g.worst_ever ? inr(g.worst_ever.pnl) : '—'}</b>
          <span>{g.worst_ever ? `${pct(g.worst_ever.gap, 1)} at the open of ${g.worst_ever.day}, at today's size` : ''}</span>
        </div>
        <div className="rk-tile">
          <span>VaR as it is run, 95%</span>
          <b>{deployment.var95 === null ? '—' : inr(deployment.var95)}</b>
          <span>counting the {pct(1 - g.held_share, 0)} of nights it sits out</span>
        </div>
      </div>
      {over && dailyLoss && (
        <div className="rk-call">
          <b>One bad night is more than the kill switch&rsquo;s daily loss limit.</b> A 1-in-20 gap costs {inr(g.var95_when_held)}; the limit is {inr(dailyLoss.limit)}. The switch would trip after the open, with the loss already taken.
        </div>
      )}
      <p className="rk-fine" style={{ marginTop: 12 }}>
        The book&rsquo;s VaR above counts this deployment as it is run, so a quiet night and a signal night are averaged. On a signal night, read the &ldquo;night it holds&rdquo; figure. A gap cannot be stopped out: there is no trading between the close and the open.
      </p>
    </section>
  );
}

function Histogram({ risk }: { risk: RiskBook }) {
  const bins = risk.var.histogram;
  const most = Math.max(1, ...bins.map((bin) => bin.days));
  const left = 40;
  const width = 500;
  const base = 180;
  const tall = 150;
  const low = bins[0]?.from ?? -1;
  const high = bins[bins.length - 1]?.to ?? 1;
  const x = (value: number) => left + ((value - low) / (high - low)) * width;
  const step = width / Math.max(1, bins.length);
  const var95 = -risk.book.var95_pct * 100;
  const var99 = risk.book.equity > 0 ? (-risk.book.var99 / risk.book.equity) * 100 : 0;
  const label = `One-day profit and loss of today's holdings over ${risk.history_days} days, as a share of equity. 95% VaR is ${var95.toFixed(2)}%, 99% VaR is ${var99.toFixed(2)}%.`;
  return (
    <svg viewBox="0 0 560 232" role="img" aria-label={label}>
      <line className="axis" x1={left} y1={base} x2={left + width} y2={base} />
      <line className="grid" x1={left} y1={base - tall / 2} x2={left + width} y2={base - tall / 2} />
      <line className="grid" x1={left} y1={base - tall} x2={left + width} y2={base - tall} />
      <text x={left - 6} y={base + 4} textAnchor="end">0</text>
      <text x={left - 6} y={base - tall / 2 + 4} textAnchor="end">{Math.round(most / 2)}</text>
      <text x={left - 6} y={base - tall + 4} textAnchor="end">{most}</text>
      {bins.map((bin, i) => {
        const height = (bin.days / most) * tall;
        const beyond = bin.to <= var95;
        return (
          <rect key={bin.from} x={left + i * step + 2} y={base - height} width={Math.max(1, step - 4)} height={height} rx={Math.min(3, height / 2)} fill={beyond ? 'var(--rk-loss)' : 'var(--rk-1)'}>
            <title>{`${axisPct(bin.from)} to ${axisPct(bin.to)}: ${bin.days} day${bin.days === 1 ? '' : 's'}`}</title>
          </rect>
        );
      })}
      {var95 > low && (
        <>
          <line x1={x(var95)} y1={20} x2={x(var95)} y2={base} stroke="var(--ink)" strokeWidth={2} strokeDasharray="4 4" />
          <text className="strong" x={x(var95) + 6} y={28}>95% VaR {axisPct(var95)}</text>
        </>
      )}
      {var99 > low && var99 < var95 && (
        <>
          <line x1={x(var99)} y1={52} x2={x(var99)} y2={base} stroke="var(--ink-3)" strokeWidth={2} strokeDasharray="2 4" />
          <text x={Math.max(left, x(var99) - 4)} y={46} textAnchor={x(var99) > left + 90 ? 'end' : 'start'}>99% VaR {axisPct(var99)}</text>
        </>
      )}
      <text x={left} y={base + 18} textAnchor="middle">{axisPct(low)}</text>
      <text x={x(0)} y={base + 18} textAnchor="middle">0</text>
      <text x={left + width} y={base + 18} textAnchor="middle">+{high.toFixed(2)}%</text>
      <text x={left + width / 2} y={base + 44} textAnchor="middle">One day&rsquo;s profit or loss, % of the book&rsquo;s equity</text>
    </svg>
  );
}

function Performance({ risk }: { risk: RiskBook }) {
  const [picked, setPicked] = useState(risk.deployments.find((d) => !d.flat)?.id ?? risk.deployments[0]?.id ?? '');
  const chosen = risk.deployments.find((d) => d.id === picked) ?? risk.deployments[0];
  const biggest = Math.max(1, ...risk.deployments.map((d) => Math.abs(d.today)));
  const b = risk.book;

  return (
    <>
      <section className="rk-card">
        <h3>Every deployment</h3>
        <p className="rk-sub">One row each. Click a row to draw it in the chart below.</p>
        <div className="rk-scroll">
          <table className="rk-table" style={{ minWidth: 1240 }}>
            <thead>
              <tr>
                <th scope="col">Deployment</th><th scope="col">Capital</th><th scope="col">Equity</th><th scope="col">Since start</th><th scope="col">Last session</th>
                <th scope="col">Volatility, a year</th><th scope="col">VaR 95%, 1 day</th><th scope="col" title="The book's VaR if this deployment were stopped">Book VaR without it</th><th scope="col">Beta to Nifty</th><th scope="col">Drawdown now</th><th scope="col">Worst in backtest</th><th scope="col">Days live</th><th scope="col">Positions</th>
              </tr>
            </thead>
            <tbody className="rk-num">
              {risk.deployments.map((d) => (
                <tr key={d.id} className="pick" aria-selected={d.id === chosen?.id} tabIndex={0} onClick={() => setPicked(d.id)} onKeyDown={(event) => event.key === 'Enter' && setPicked(d.id)}>
                  <td className="name" title={d.title}><span className="rk-dot" style={{ display: 'inline-block', marginRight: 8, background: colourOf(d.slot) }} />{d.title}</td>
                  <td>{lakh(d.capital)}</td>
                  <td>{lakh(d.equity)}</td>
                  <td>{pct(d.since_start, 2, true)}</td>
                  <td>{signedInr(d.today)}</td>
                  <td>{d.flat ? '—' : pct(d.volatility, 0)}</td>
                  <td>{d.flat || d.var95 === null ? '—' : inr(d.var95)}</td>
                  <td>{d.var_without === null ? '—' : inr(d.var_without)}</td>
                  <td>{d.beta === null ? '—' : d.beta.toFixed(2)}</td>
                  <td>{pct(d.drawdown_now, 1)}</td>
                  <td>{pct(d.backtest_worst_drawdown, 0)}</td>
                  <td>{d.days_live}</td>
                  <td>{d.gap ? (d.gap.holds_tonight ? `${d.gap.lots} lot` : 'none tonight') : d.positions}</td>
                </tr>
              ))}
              <tr style={{ fontWeight: 600 }}>
                <td>The book</td><td>{lakh(b.capital)}</td><td>{lakh(b.equity)}</td><td>{pct(b.since_start_pct, 2, true)}</td><td>{signedInr(b.today)}</td>
                <td>{pct(b.volatility, 1)}</td><td>{risk.enough_history ? inr(b.var95) : '—'}</td><td>—</td><td>{b.beta === null ? '—' : b.beta.toFixed(2)}</td><td>{pct(b.drawdown.now, 1)}</td><td>—</td><td>{b.curve.length}</td><td>{b.names}</td>
              </tr>
            </tbody>
          </table>
        </div>
        {risk.stopped.length > 0 && (
          <>
            <h3 style={{ marginTop: 20 }}>Stopped</h3>
            <p className="rk-sub">No longer trading, so in none of the figures on these pages. Kept here with what each made.</p>
            <div className="rk-scroll">
              <table className="rk-table">
                <thead><tr><th scope="col">Deployment</th><th scope="col">Capital</th><th scope="col">Ended at</th><th scope="col">Made</th><th scope="col">Days live</th><th scope="col">Last day</th></tr></thead>
                <tbody className="rk-num">
                  {risk.stopped.map((d) => (
                    <tr key={d.id}>
                      <td className="name" title={d.title}><span className="rk-dot" style={{ display: 'inline-block', marginRight: 8, background: colourOf(d.slot) }} />{d.title}</td>
                      <td>{lakh(d.capital)}</td><td>{lakh(d.equity)}</td><td>{signedInr(d.made)} ({pct(d.made_pct, 2, true)})</td><td>{d.days_live}</td><td>{d.last_day ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
        <p className="rk-fine" style={{ marginTop: 12 }}>&ldquo;Book VaR without it&rdquo; is the whole book&rsquo;s VaR if that deployment were stopped today: lower than the book&rsquo;s means it adds risk, higher means it offsets some. The book&rsquo;s VaR is less than the sum of the rows when the deployments do not all lose on the same days. Volatility and VaR come from today&rsquo;s holdings over the last {risk.history_days} days, not from the deployment&rsquo;s own short record.</p>
      </section>

      <div className="rk-row">
        <section className="rk-card wide">
          <h3>Live against its backtest</h3>
          <p className="rk-sub" title={chosen?.title}>
            {chosen?.title}. The shaded band is where its backtest says equity should be after this many days, nine times in ten. A line that leaves the band is not behaving as tested.
          </p>
          {chosen && <Band deployment={chosen} colour={colourOf(chosen.slot)} />}
        </section>

        <section className="rk-card narrow">
          <h3>Is each one behaving as tested?</h3>
          <p className="rk-sub">Return since it started, beside what its backtest expected over the same number of days.</p>
          <div className="rk-scroll">
            <table className="rk-table">
              <thead><tr><th scope="col">Deployment</th><th scope="col">Expected</th><th scope="col">Got</th><th scope="col" className="l">Verdict</th></tr></thead>
              <tbody className="rk-num">
                {risk.deployments.map((d) => (
                  <tr key={d.id}>
                    <td className="name" style={{ maxWidth: 170 }} title={d.title}>{d.title}</td>
                    <td>{pct(d.against_backtest.expected, 1, true)}</td>
                    <td>{pct(d.since_start, 1, true)}</td>
                    <td className="l"><span className="rk-pill" data-state={d.against_backtest.verdict}>{VERDICT[d.against_backtest.verdict]}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="rk-fine" style={{ marginTop: 12 }}>A deployment is judged only after 20 days live. Before that, almost any path is inside the band.</p>
        </section>
      </div>

      <div className="rk-row">
        <section className="rk-card wide">
          <h3>Drawdown of the book</h3>
          <p className="rk-sub">How far the whole book&rsquo;s equity sits below its highest point so far. Zero means a new high.</p>
          <Underwater risk={risk} />
        </section>

        <section className="rk-card narrow">
          <h3>Who made and lost money in the last session</h3>
          <p className="rk-sub">Each deployment&rsquo;s change in equity{risk.as_of ? ` on ${risk.as_of}` : ''}. They sum to {signedInr(b.today)}.</p>
          <div className="rk-bars">
            {risk.deployments.map((d) => (
              <div className="rk-bar-row" key={d.id}>
                <div className="rk-bar-name" style={{ flexBasis: 150 }} title={d.title}>{d.title}</div>
                <div style={{ flex: 1, display: 'flex', minWidth: 0 }}>
                  <div style={{ flex: 1, display: 'flex', justifyContent: 'flex-end' }}>
                    {d.today < 0 && <div className="rk-bar" style={{ width: `${(Math.abs(d.today) / biggest) * 100}%`, background: 'var(--rk-loss)', borderRadius: '4px 0 0 4px' }} />}
                  </div>
                  <div style={{ width: 1, background: 'var(--rule-2)' }} />
                  <div style={{ flex: 1 }}>{d.today > 0 && <div className="rk-bar" style={{ width: `${(d.today / biggest) * 100}%`, background: 'var(--rk-1)' }} />}</div>
                </div>
                <div className="rk-bar-value" style={{ flexBasis: 80 }}>{signedInr(d.today)}</div>
              </div>
            ))}
          </div>
          <div className="rk-legend" style={{ marginTop: 16 }}>
            <span className="rk-key"><span className="rk-dot" style={{ background: 'var(--rk-1)' }} />Gain</span>
            <span className="rk-key"><span className="rk-dot" style={{ background: 'var(--rk-loss)' }} />Loss</span>
          </div>
        </section>
      </div>
    </>
  );
}

function Band({ deployment, colour }: { deployment: RiskDeployment; colour: string }) {
  const { live, band, verdict } = deployment.against_backtest;
  const shape = useMemo(() => {
    const values = [...live.map((p) => p.value), ...band.flatMap((p) => [p.low, p.high])];
    const lo = Math.floor(Math.min(...values, 99) - 0.5);
    const hi = Math.ceil(Math.max(...values, 101) + 0.5);
    const last = Math.max(1, live[live.length - 1]?.day ?? 1, band[band.length - 1]?.day ?? 1);
    const x = (day: number) => 44 + (day / last) * 496;
    const y = (value: number) => 190 - ((value - lo) / (hi - lo)) * 170;
    return { lo, hi, last, x, y };
  }, [live, band]);
  const { lo, hi, last, x, y } = shape;

  if (live.length < 2) return <p className="rk-fine">This deployment has no trading days yet, so there is nothing to draw.</p>;

  const end = live[live.length - 1];
  const area = band.length > 1 ? [...band.map((p) => `${x(p.day)},${y(p.high)}`), ...[...band].reverse().map((p) => `${x(p.day)},${y(p.low)}`)].join(' ') : '';
  const mid = band[band.length - 1];
  return (
    <>
      <svg viewBox="0 0 560 222" role="img" aria-label={`Equity of ${deployment.title} over ${end.day} days, starting at 100. It is at ${end.value.toFixed(1)}. ${VERDICT[verdict]}.`}>
        {[lo, (lo + hi) / 2, hi].map((tick) => (
          <g key={tick}>
            <line className={tick === lo ? 'axis' : 'grid'} x1={44} y1={y(tick)} x2={540} y2={y(tick)} />
            <text x={38} y={y(tick) + 4} textAnchor="end">{tick.toFixed(tick % 1 ? 1 : 0)}</text>
          </g>
        ))}
        {area && <polygon points={area} fill={colour} fillOpacity={0.14}><title>Backtest, 5th to 95th percentile</title></polygon>}
        {band.length > 1 && (
          <polyline points={band.map((p) => `${x(p.day)},${y(p.mid)}`).join(' ')} fill="none" stroke="var(--ink-3)" strokeWidth={2} strokeDasharray="5 5"><title>Backtest, middle path</title></polyline>
        )}
        <polyline points={live.map((p) => `${x(p.day)},${y(p.value)}`).join(' ')} fill="none" stroke={colour} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"><title>Live equity, start = 100</title></polyline>
        <circle cx={x(end.day)} cy={y(end.value)} r={5} fill={colour} stroke="var(--surface)" strokeWidth={2}><title>{`Day ${end.day}: ${end.value.toFixed(2)}`}</title></circle>
        <text className="strong" x={x(end.day) - 8} y={Math.max(14, y(end.value) - 10)} textAnchor="end">Live {end.value.toFixed(1)}</text>
        {mid && band.length > 1 && <text x={x(mid.day) - 8} y={Math.min(186, y(mid.mid) + 16)} textAnchor="end">Backtest middle {mid.mid.toFixed(1)}</text>}
        <text x={44} y={208} textAnchor="middle">Day 0</text>
        <text x={540} y={208} textAnchor="middle">Day {last}</text>
      </svg>
      <div className="rk-legend">
        <span className="rk-key"><span className="rk-dot" style={{ background: colour }} />Live equity</span>
        {band.length > 1 ? (
          <>
            <span className="rk-key"><span className="rk-dot" style={{ background: 'var(--ink-3)' }} />Backtest, middle path</span>
            <span className="rk-key"><span className="rk-dot" style={{ background: colour, opacity: 0.3 }} />Backtest, 9 times in 10</span>
          </>
        ) : (
          <span>No backtest of this strategy is stored, so there is no band to compare with.</span>
        )}
      </div>
    </>
  );
}

function Underwater({ risk }: { risk: RiskBook }) {
  const path = risk.book.drawdown.path;
  if (path.length < 2) return <p className="rk-fine">Not enough days yet to draw.</p>;
  const deepest = Math.min(...path.map(([, value]) => value), -0.001);
  const floor = Math.floor(deepest * 100 - 0.5) / 100;
  const x = (index: number) => 44 + (index / (path.length - 1)) * 496;
  const y = (value: number) => 26 + (value / floor) * 112;
  const line = path.map(([, value], i) => `${x(i)},${y(value)}`).join(' ');
  const worst = path.findIndex(([, value]) => value === Math.min(...path.map(([, v]) => v)));
  const last = path.length - 1;
  return (
    <svg viewBox="0 0 560 172" role="img" aria-label={`Drawdown of the whole book over ${path.length} days. Deepest ${pct(risk.book.drawdown.deepest, 1)}. Now ${pct(risk.book.drawdown.now, 1)}.`}>
      {[0, floor / 2, floor].map((tick) => (
        <g key={tick}>
          <line className={tick === 0 ? 'axis' : 'grid'} x1={44} y1={y(tick)} x2={540} y2={y(tick)} />
          <text x={38} y={y(tick) + 4} textAnchor="end">{tick === 0 ? '0' : pct(tick, 1)}</text>
        </g>
      ))}
      <polygon points={`44,${y(0)} ${line} 540,${y(0)}`} fill="var(--rk-1)" fillOpacity={0.18} />
      <polyline points={line} fill="none" stroke="var(--rk-1)" strokeWidth={2} strokeLinejoin="round"><title>Drawdown of the book</title></polyline>
      {path[worst][1] < 0 && (
        <>
          <circle cx={x(worst)} cy={y(path[worst][1])} r={5} fill="var(--rk-1)" stroke="var(--surface)" strokeWidth={2}><title>{`${path[worst][0]}: ${pct(path[worst][1], 2)}`}</title></circle>
          {worst !== last && <text x={x(worst)} y={y(path[worst][1]) + 18} textAnchor="middle">Deepest {pct(path[worst][1], 1)}</text>}
        </>
      )}
      <circle cx={x(last)} cy={y(path[last][1])} r={5} fill="var(--rk-1)" stroke="var(--surface)" strokeWidth={2}><title>{`${path[last][0]}: ${pct(path[last][1], 2)}`}</title></circle>
      <text className="strong" x={x(last) - 8} y={y(path[last][1]) + 18} textAnchor="end">Now {pct(path[last][1], 1)}</text>
      <text x={44} y={160} textAnchor="start">{path[0][0]}</text>
      <text x={540} y={160} textAnchor="end">{path[last][0]}</text>
    </svg>
  );
}

function Stress({ risk }: { risk: RiskBook }) {
  const b = risk.book;
  const worst = Math.max(0.0001, ...risk.stress.map((row) => Math.abs(row.share)));
  const watchDrawdown = risk.limits.find((row) => row.name === 'Book drawdown');
  const limitShare = watchDrawdown ? watchDrawdown.limit / 100 : null;
  const scale = Math.max(worst, limitShare ?? 0) * 1.05;
  const topSector = Math.max(0.0001, ...risk.sectors.map((row) => row.share));
  const sectorLimit = risk.limits.find((row) => row.name.startsWith('Largest sector'));
  const sectorScale = Math.max(topSector, sectorLimit ? sectorLimit.limit / 100 : 0) * 1.05;
  const band = (value: number | null) => (value === null ? 0 : value >= 0.8 ? 4 : value >= 0.6 ? 3 : value >= 0.45 ? 2 : 1);
  const crossing = limitShare === null ? [] : risk.stress.filter((row) => Math.abs(row.share) >= limitShare);
  const shown = risk.correlation.titles.length <= 6;

  return (
    <>
      <section className="rk-card">
        <h3>If it happened tomorrow</h3>
        <p className="rk-sub">
          Today&rsquo;s holdings put through bad days. VaR describes an ordinary bad day; these are the days it does not cover.
          {limitShare !== null && ` The marker is the ${watchDrawdown?.limit}% drawdown watch level for the book.`}
        </p>
        <div className="rk-bars">
          {risk.stress.map((row) => (
            <div className="rk-bar-row" key={row.key}>
              <div className="rk-bar-name" style={{ flexBasis: 300 }} title={`${row.label} (${row.note})`}>{row.label} <span className="rk-fine">· {row.note}</span></div>
              <div className="rk-bar-track">
                <div className="rk-bar" style={{ width: `${(Math.abs(row.share) / scale) * 100}%`, background: 'var(--rk-loss)' }} title={`${inr(row.loss)}, ${pct(row.share, 2)} of equity`} />
                {limitShare !== null && <div className="rk-mark" style={{ left: `${(limitShare / scale) * 100}%` }} title={`Book drawdown watch level, ${watchDrawdown?.limit}%`} />}
              </div>
              <div className="rk-bar-value">{inr(row.loss)} · {pct(row.share, 2)}</div>
            </div>
          ))}
        </div>
        <div className="rk-legend" style={{ marginTop: 16 }}>
          <span className="rk-key"><span className="rk-dot" style={{ background: 'var(--rk-loss)' }} />Loss, % of the book&rsquo;s equity</span>
          {limitShare !== null && <span className="rk-key"><span style={{ width: 2, height: 14, background: 'var(--ink)' }} />Book drawdown watch level</span>}
          {limitShare !== null && <span>{crossing.length === 0 ? 'No scenario reaches the watch level.' : `${crossing.length} scenario${crossing.length === 1 ? '' : 's'} would pass the watch level.`}</span>}
        </div>
        <p className="rk-fine" style={{ marginTop: 12 }}>A market fall reaches each holding through its own beta to the Nifty, measured over the last {risk.history_days} days; a holding with no measured beta is taken to fall with the market.</p>
      </section>

      <div className="rk-row">
        <section className="rk-card">
          <h3>By sector</h3>
          <p className="rk-sub">Share of the {lakh(b.invested)} invested.{sectorLimit ? ` The marker is the ${sectorLimit.limit}% watch level for any one sector.` : ''}</p>
          <div className="rk-bars">
            {risk.sectors.map((row) => (
              <div className="rk-bar-row" key={row.sector}>
                <div className="rk-bar-name" style={{ flexBasis: 190 }} title={row.sector}>{row.sector}</div>
                <div className="rk-bar-track">
                  <div className="rk-bar" style={{ width: `${(row.share / sectorScale) * 100}%`, background: row.sector === 'Unclassified' ? 'var(--rk-quiet)' : 'var(--rk-1)' }} title={`${row.sector}: ${inr(row.value)}`} />
                  {sectorLimit && <div className="rk-mark" style={{ left: `${(sectorLimit.limit / 100 / sectorScale) * 100}%` }} title={`Sector watch level, ${sectorLimit.limit}%`} />}
                </div>
                <div className="rk-bar-value" style={{ flexBasis: 48 }}>{pct(row.share, 0)}</div>
              </div>
            ))}
            {risk.sectors.length === 0 && <p className="rk-fine">Nothing is invested.</p>}
          </div>
        </section>

        <section className="rk-card">
          <h3>Largest names</h3>
          <p className="rk-sub">Added up across every deployment that holds them. A name held by two deployments is one bet, not two.</p>
          <div className="rk-scroll">
            <table className="rk-table">
              <thead><tr><th scope="col">Name</th><th scope="col">Value</th><th scope="col">Of the book</th><th scope="col">Held by</th><th scope="col" className="l">Sector</th></tr></thead>
              <tbody className="rk-num">
                {risk.names.map((row) => (
                  <tr key={row.symbol}>
                    <td><a href={`/terminal/company/${encodeURIComponent(row.symbol)}`}>{row.symbol}</a></td>
                    <td>{inr(row.value)}</td>
                    <td>{pct(row.share, 2)}</td>
                    <td>{row.held_by}</td>
                    <td className="l name" style={{ maxWidth: 170 }}>{row.sector}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {risk.names.length === 0 && <p className="rk-fine">Nothing is held.</p>}
        </section>
      </div>

      <div className="rk-row">
        <section className="rk-card wide">
          <h3>Do the deployments lose together?</h3>
          <p className="rk-sub">
            How closely each pair&rsquo;s daily results have moved together over {risk.history_days} days. 1.0 means identical; near zero means unrelated. A pair above 0.8 is close to being one strategy. A dash means that deployment holds nothing.
          </p>
          {shown ? (
            <>
              <div className="rk-heat" role="img" aria-label={`Correlation between ${risk.correlation.titles.length} deployments.`} style={{ gridTemplateColumns: `minmax(120px, 220px) repeat(${risk.correlation.titles.length}, minmax(0, 1fr))` }}>
                <div />
                {risk.correlation.titles.map((title, i) => (
                  <div className="axis-label top" key={`top-${risk.correlation.ids[i]}`} title={title}>{i + 1}</div>
                ))}
                {risk.correlation.matrix.map((row, i) => (
                  <div key={risk.correlation.ids[i]} style={{ display: 'contents' }}>
                    <div className="axis-label" title={risk.correlation.titles[i]}>{i + 1}. {risk.correlation.titles[i]}</div>
                    {row.map((value, j) => (
                      <div className="rk-cell" key={risk.correlation.ids[j]} data-band={i === j ? 0 : band(value)} title={`${risk.correlation.titles[i]} and ${risk.correlation.titles[j]}`}>
                        {value === null ? '—' : i === j ? '1' : value.toFixed(2)}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
              <div className="rk-legend" style={{ marginTop: 14 }}>
                <span>Less alike</span>
                {[1, 2, 3, 4].map((step) => (
                  <span key={step} className="rk-cell" data-band={step} style={{ width: 28, height: 10, display: 'inline-block' }} />
                ))}
                <span>More alike</span>
              </div>
            </>
          ) : (
            <p className="rk-fine">More than six deployments: the pairs that move most alike are listed on the right.</p>
          )}
        </section>

        <section className="rk-card narrow">
          <h3>What this page is telling you</h3>
          <p className="rk-sub">Read from the numbers on this page, in plain words.</p>
          <Findings risk={risk} crossing={crossing.length} />
          <div className="rk-facts">
            <div><span>Beta of the book to the Nifty</span><b className="rk-num">{b.beta === null ? '—' : b.beta.toFixed(2)}</b></div>
            <div><span>Invested</span><b className="rk-num">{lakh(b.invested)} · {pct(b.exposure, 1)}</b></div>
            <div><span>Cash</span><b className="rk-num">{lakh(b.cash)}</b></div>
            <div><span>Short positions</span><b className="rk-num">{risk.names.some((n) => n.value < 0) ? 'yes' : 'none'}</b></div>
          </div>
        </section>
      </div>
    </>
  );
}

/** Sentences built only from figures in the payload. None when nothing stands out. */
function Findings({ risk, crossing }: { risk: RiskBook; crossing: number }) {
  const lines: { head: string; body: string }[] = [];
  for (const pair of risk.alike.slice(0, 2)) {
    lines.push({ head: 'Two deployments are close to one bet.', body: `"${pair.a}" and "${pair.b}" move together (${pair.correlation.toFixed(2)}).` });
  }
  const heavy = risk.deployments.find((d) => risk.enough_history && d.var_share > 0.25 && d.var_share > 2 * d.capital_share);
  if (heavy) {
    lines.push({ head: 'One deployment carries most of the risk.', body: `"${heavy.title}" is ${pct(heavy.capital_share, 0)} of the money and ${pct(heavy.var_share, 0)} of the VaR.` });
  }
  const idle = risk.deployments.filter((d) => d.flat).reduce((sum, d) => sum + d.capital_share, 0);
  if (idle > 0.5) {
    lines.push({ head: 'Most of the money holds nothing at the close.', body: `${pct(idle, 0)} of the book is in deployments with no position now, so the VaR here describes the other ${pct(1 - idle, 0)}.` });
  }
  for (const row of risk.limits.filter((l) => l.state !== 'ok').slice(0, 2)) {
    lines.push({ head: row.state === 'over' ? 'A limit is passed.' : 'A limit is close.', body: `${row.name}: ${pct(row.used, 0)} used.` });
  }
  if (crossing > 0) {
    lines.push({ head: 'A bad day would pass the drawdown watch level.', body: `${crossing} of the scenarios above reach it.` });
  }
  if (lines.length === 0) return <p className="rk-fine">Nothing on this page stands out: no limit is close, no pair of deployments moves as one, and no scenario reaches the watch level.</p>;
  return (
    <ol style={{ margin: 0, paddingLeft: 20, display: 'flex', flexDirection: 'column', gap: 12, fontSize: 13, lineHeight: 1.5, color: 'var(--ink-2)' }}>
      {lines.map((line) => (
        <li key={line.head + line.body}><b style={{ color: 'var(--ink)' }}>{line.head}</b> {line.body}</li>
      ))}
    </ol>
  );
}
