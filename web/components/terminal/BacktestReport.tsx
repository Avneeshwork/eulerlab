'use client';

/**
 * The backtest report, as a page.
 *
 * Laid out after OpenAlgo's backtest results (frontend/src/pages/
 * PortfolioBacktesterResults.tsx and components/trading/BacktestResultTabs.tsx):
 * a title with the period under it, a grid of stat cards, and one tab per
 * question — the curve, the drawdown, the calendar, the trades, the
 * instruments, the fills. It replaces a dialog that put all of it in one
 * scrolling column and had no list of trades at all, only fills.
 *
 * Trades, drawdown episodes and calendar returns are derived from the equity
 * curve and the fill ledger the endpoint already returns (lib/backtestStats).
 * The reconciliation stays visible, because an attribution that does not add
 * up should never be read without saying so.
 */

import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Download } from 'lucide-react';
import { EquityChart } from '@/components/terminal/EquityChart';
import { TuningView } from '@/components/terminal/TuningPanel';
import { api } from '@/lib/api';
import { assetClassLabel } from '@/lib/assetClasses';
import {
  calendarReturns,
  drawdowns,
  episodes,
  roundTrips,
  tradeStats,
  type Trade,
} from '@/lib/backtestStats';
import { moneyIn } from '@/lib/money';
import type { FleetStrategy, FullReport, RunChoice, Tuning } from '@/lib/api';

type Tab = 'overview' | 'equity' | 'drawdown' | 'returns' | 'trades' | 'instruments' | 'orders' | 'tuning';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const pct = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? '—'
    : `${value < 0 ? '−' : ''}${Math.abs(value * 100).toFixed(digits)}%`;

const num = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined || !Number.isFinite(value) ? '—' : value.toFixed(digits);

function tone(value: number | null | undefined): 'good' | 'bad' | undefined {
  if (value === null || value === undefined || value === 0) return undefined;
  return value > 0 ? 'good' : 'bad';
}

export function BacktestReport({
  strategy,
  bar,
  workspace,
  onBack,
}: {
  strategy: FleetStrategy;
  /** The noise bar, so the Sharpe card can say whether it clears it. */
  bar: number | null;
  workspace: string;
  onBack: () => void;
}) {
  const [report, setReport] = useState<FullReport | null>(null);
  const [runs, setRuns] = useState<RunChoice[]>([]);
  const [chosen, setChosen] = useState('');
  const [error, setError] = useState('');
  const [tab, setTab] = useState<Tab>('overview');
  const [query, setQuery] = useState('');
  const [tuning, setTuning] = useState<Tuning | null>(null);

  useEffect(() => {
    let live = true;
    api
      .tuning(strategy.id)
      .then((found) => live && setTuning(found.ran ? found : null))
      .catch(() => live && setTuning(null));
    return () => {
      live = false;
    };
  }, [strategy.id]);

  useEffect(() => {
    setError('');
    setReport(null);
    api
      .report(strategy.id, workspace, chosen)
      .then((response) => {
        setRuns(response.runs ?? []);
        if (response.ok && response.report) setReport(response.report);
        else setError(response.error ?? 'This strategy has no stored run to report on yet.');
      })
      .catch((problem) => setError(problem instanceof Error ? problem.message : String(problem)));
  }, [strategy.id, workspace, chosen]);

  const market = report?.asset_class ?? strategy.asset_class ?? 'equity';
  const money = moneyIn(market);

  const derived = useMemo(() => {
    if (!report) return null;
    const { days, values } = report.equity;
    const trades = roundTrips(report.orders);
    return {
      trades,
      stats: tradeStats(trades),
      drawdown: drawdowns(values),
      episodes: episodes(days, values, 8),
      calendar: calendarReturns(days, values, report.starting_cash),
    };
  }, [report]);

  const header = (
    <div className="rpt-head">
      <div style={{ minWidth: 0 }}>
        <button className="rpt-back" type="button" onClick={onBack}>
          <ArrowLeft size={14} aria-hidden="true" /> Strategies
        </button>
        <h1>{strategy.title}</h1>
        <p>
          {report ? (
            <>
              <span className="assettag">{assetClassLabel(market)}</span>{' '}
              {report.instruments.length > 0
                ? report.instruments.slice(0, 6).join(', ') +
                  (report.instruments.length > 6 ? ` +${report.instruments.length - 6} more` : '')
                : report.universe}{' '}
              · {report.period[0]} to {report.period[1]} · tier {report.tier} · starting capital{' '}
              {money(report.starting_cash)}
            </>
          ) : (
            'Backtest report'
          )}
        </p>
      </div>
      {runs.length > 1 && (
        <div className="rpt-runs" aria-label="Stored runs">
          <span>Run</span>
          {runs
            .slice()
            .sort((a, b) => b.window_days - a.window_days)
            .map((run) => (
              <button
                key={run.configuration}
                className="tchip sm"
                type="button"
                aria-pressed={run.configuration === (chosen || report?.configuration)}
                onClick={() => setChosen(run.configuration)}
                title={`${run.universe} · tier ${run.tier} · Sharpe ${run.sharpe.toFixed(2)} · ${run.at}`}
              >
                {run.window_days}d · {run.universe}
              </button>
            ))}
        </div>
      )}
    </div>
  );

  if (error) {
    return (
      <>
        {header}
        <div className="tnote bad">
          <span className="mk">▲</span>
          <div>{error}</div>
        </div>
      </>
    );
  }
  if (!report || !derived) {
    return (
      <>
        {header}
        <div className="tempty">Reading the report…</div>
      </>
    );
  }

  const m = report.metrics;
  const { trades, stats } = derived;
  const net = report.final_equity - report.starting_cash;
  const clears = bar !== null && m.sharpe >= bar;

  const TABS: { id: Tab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'equity', label: 'Equity' },
    { id: 'drawdown', label: 'Drawdown' },
    { id: 'returns', label: 'Returns' },
    { id: 'trades', label: `Trades (${stats.closed})` },
    { id: 'instruments', label: `Instruments (${report.constituents.length})` },
    { id: 'orders', label: `Orders (${report.orders.length})` },
    ...(tuning ? [{ id: 'tuning' as const, label: 'Optimisation' }] : []),
  ];

  return (
    <>
      {header}

      {report.warnings.length > 0 && (
        <div className="tnote warn">
          <span className="mk">!</span>
          <div>
            {report.warnings.map((warning) => (
              <p key={warning} style={{ margin: 0 }}>
                {warning}
              </p>
            ))}
          </div>
        </div>
      )}

      <div className="rpt-grid">
        <Stat label="Net profit" value={money(net)} sub={pct(m.total_return)} tone={tone(net)} />
        <Stat
          label="CAGR"
          value={pct(m.annualised)}
          sub={`over ${num(m.years, 1)} years`}
          tone={tone(m.annualised)}
        />
        <Stat
          label="Max drawdown"
          value={pct(m.drawdown.depth)}
          sub={
            m.drawdown.still_underwater
              ? 'not yet recovered'
              : m.drawdown.recovered_day
                ? `recovered ${m.drawdown.recovered_day}`
                : undefined
          }
          tone="bad"
        />
        <Stat
          label="Sharpe"
          value={num(m.sharpe)}
          sub={bar === null ? undefined : clears ? `clears the bar of ${num(bar)}` : `bar is ${num(bar)}`}
          tone={clears ? 'clear' : undefined}
        />
        <Stat label="Sortino" value={num(m.sortino)} sub={`volatility ${pct(m.volatility, 1)}`} />
        <Stat
          label="Win rate"
          value={pct(stats.winRate, 1)}
          sub={`${stats.wins} of ${stats.closed} trades`}
        />
        <Stat
          label="Profit factor"
          value={num(stats.profitFactor)}
          sub="gross profit ÷ gross loss"
        />
        <Stat
          label="Costs"
          value={money(m.costs)}
          sub={`${pct(m.cost_drag)} of return · ${m.turnover_x ?? '—'}× turnover`}
        />
      </div>

      <div className="rpt-tabs" role="tablist" aria-label="Report sections">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <>
          <Card title="Equity curve" sub={`${money(report.starting_cash)} on ${report.period[0]} to ${money(report.final_equity)}`}>
            <EquityChart
              values={report.equity.values}
              days={report.equity.days}
              startingCash={report.starting_cash}
              money={money}
            />
          </Card>

          <div className="rpt-two">
            <Card title="Trade analysis" sub="Round trips matched first in, first out from the fills.">
              <KV
                rows={[
                  ['Closed trades', String(stats.closed)],
                  ['Still open', String(stats.open)],
                  ['Winners', `${stats.wins} (${pct(stats.winRate, 1)})`],
                  ['Losers', String(stats.losses)],
                  ['Gross profit', money(stats.grossProfit), 'pos'],
                  ['Gross loss', money(stats.grossLoss), 'neg'],
                  ['Average win', stats.averageWin === null ? '—' : money(stats.averageWin), 'pos'],
                  ['Average loss', stats.averageLoss === null ? '—' : money(stats.averageLoss), 'neg'],
                  ['Largest win', stats.largestWin === null ? '—' : money(stats.largestWin), 'pos'],
                  ['Largest loss', stats.largestLoss === null ? '—' : money(stats.largestLoss), 'neg'],
                  ['Expectancy per trade', stats.expectancy === null ? '—' : money(stats.expectancy)],
                ]}
              />
            </Card>

            <div className="rpt-stack">
              {report.benchmark && (
                <Card title={`Against holding ${report.benchmark.symbol}`} sub="Same sessions, bought on the first and held.">
                  <KV
                    rows={[
                      ['This strategy', money(net), net >= 0 ? 'pos' : 'neg'],
                      [
                        `Holding ${report.benchmark.symbol}`,
                        money(report.benchmark.net_pnl),
                        report.benchmark.net_pnl >= 0 ? 'pos' : 'neg',
                      ],
                      [
                        'Difference',
                        money(net - report.benchmark.net_pnl),
                        net - report.benchmark.net_pnl >= 0 ? 'pos' : 'neg',
                      ],
                      ['Benchmark Sharpe', num(report.benchmark.sharpe)],
                      ['Benchmark worst fall', pct(-Math.abs(report.benchmark.max_drawdown), 1)],
                      ['Time in the market', pct(m.invested_fraction, 0)],
                    ]}
                  />
                </Card>
              )}
              <Card title="Costs" sub="What trading cost, from the schedule for this market.">
                <KV
                  rows={[
                    ['Costs paid', money(m.costs)],
                    ['Return given up', pct(m.cost_drag)],
                    ['Value traded', money(m.traded_value)],
                    ['Turnover', `${m.turnover_x ?? '—'}×`],
                    ['Fills', String(report.orders.length)],
                    ['Rejected orders', String(report.rejections.length)],
                  ]}
                />
              </Card>
            </div>
          </div>

          <p className={`rpt-recon${report.reconciliation.exact ? '' : ' bad'}`}>
            {report.reconciliation.exact
              ? `Per-instrument contributions add up to the equity change of ${money(report.reconciliation.equity_change)} exactly.`
              : `Per-instrument contributions (${money(report.reconciliation.attributed)}) do not add up to the equity change (${money(report.reconciliation.equity_change)}); the residual is ${money(report.reconciliation.residual)}. Treat the attribution as incomplete.`}
            {report.reconciliation.unmarked_symbols.length > 0 &&
              ` Unpriced at the end: ${report.reconciliation.unmarked_symbols.join(', ')}.`}
          </p>
        </>
      )}

      {tab === 'equity' && (
        <>
          <Card title="Equity curve" sub="The starting balance is the dashed line.">
            <EquityChart
              values={report.equity.values}
              days={report.equity.days}
              startingCash={report.starting_cash}
              money={money}
            />
          </Card>
          <Card title="Return and risk">
            <KV
              columns
              rows={[
                ['Total return', pct(m.total_return)],
                ['CAGR', pct(m.annualised)],
                ['Volatility', pct(m.volatility)],
                ['Sharpe', num(m.sharpe)],
                ['Sortino', num(m.sortino)],
                ['Trading days', String(m.trading_days)],
                ['Invested', pct(m.invested_fraction, 0)],
                ['First trade', m.first_move_day ?? '—'],
              ]}
            />
          </Card>
        </>
      )}

      {tab === 'drawdown' && (
        <>
          <Card title="Underwater" sub="Distance below the highest equity reached so far.">
            <Underwater days={report.equity.days} values={derived.drawdown} />
          </Card>
          <Card title="Worst drawdowns">
            <div className="tscroll">
              <table className="ttable">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Started</th>
                    <th>Bottom</th>
                    <th>Recovered</th>
                    <th className="r">Depth</th>
                    <th className="r">Sessions</th>
                  </tr>
                </thead>
                <tbody>
                  {derived.episodes.map((episode, index) => (
                    <tr key={`${episode.start}-${index}`}>
                      <td>{index + 1}</td>
                      <td>{episode.start}</td>
                      <td>{episode.trough}</td>
                      <td>{episode.end ?? <span className="neg">not yet</span>}</td>
                      <td className="r neg">{pct(episode.depth)}</td>
                      <td className="r">{episode.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {derived.episodes.length === 0 && (
                <div className="tempty">Equity never fell below an earlier high.</div>
              )}
            </div>
          </Card>
        </>
      )}

      {tab === 'returns' && (
        <>
          <Card title="Monthly returns" sub="Compounded from the equity curve; a blank cell is a month the run did not cover.">
            <Heatmap months={derived.calendar.months} years={derived.calendar.years} />
          </Card>
          <Card title="Daily distribution">
            <KV
              columns
              rows={[
                ['Best day', pct(m.best_day)],
                ['Worst day', pct(m.worst_day)],
                ['Average up day', pct(m.average_gain)],
                ['Average down day', pct(m.average_loss)],
                ['Up days', pct(m.hit_rate, 1)],
                ['Up days when invested', pct(m.hit_rate_invested, 1)],
                ['Skew', num(m.skew)],
                ['Excess kurtosis', num(m.kurtosis)],
              ]}
            />
          </Card>
        </>
      )}

      {tab === 'trades' && (
        <TradeList
          trades={trades}
          query={query}
          onQuery={setQuery}
          money={money}
          filename={`${strategy.id}-trades.csv`}
        />
      )}

      {tab === 'instruments' && (
        <Card title="Contribution by instrument" sub="Sorted by what each one added to or took from the result.">
          <div className="tscroll" style={{ maxHeight: '60vh' }}>
            <table className="ttable">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="r">Contribution</th>
                  <th className="r">Fills</th>
                  <th className="r">Bought</th>
                  <th className="r">Sold</th>
                  <th className="r">Costs</th>
                  <th className="r">Still held</th>
                  <th className="r">Last traded</th>
                </tr>
              </thead>
              <tbody>
                {[...report.constituents]
                  .sort((a, b) => b.contribution - a.contribution)
                  .map((row) => (
                    <tr key={row.symbol}>
                      <td>
                        <b>{row.symbol}</b>
                      </td>
                      <td className={`r ${row.contribution < 0 ? 'neg' : 'pos'}`}>
                        {money(row.contribution)}
                      </td>
                      <td className="r">{row.fills}</td>
                      <td className="r">{money(row.bought_value)}</td>
                      <td className="r">{money(row.sold_value)}</td>
                      <td className="r">{money(row.costs)}</td>
                      <td className="r">
                        {row.open_qty ? money(row.open_value) : <span className="tdim">—</span>}
                      </td>
                      <td className="r">{row.last_day}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
            {report.constituents.length === 0 && (
              <div className="tempty">Nothing traded, so there is nothing to attribute.</div>
            )}
          </div>
        </Card>
      )}

      {tab === 'orders' && (
        <OrderList report={report} query={query} onQuery={setQuery} money={money} />
      )}
      {tab === 'tuning' && tuning && <TuningView data={tuning} />}
    </>
  );
}

function Stat({
  label,
  value,
  sub,
  tone: kind,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: 'good' | 'bad' | 'clear';
}) {
  return (
    <div className="tstat-card">
      <span>{label}</span>
      <b className={kind === 'good' ? 'pos' : kind === 'bad' ? 'neg' : kind === 'clear' ? 'on' : ''}>
        {value}
      </b>
      {sub && <i>{sub}</i>}
    </div>
  );
}

function Card({
  title,
  sub,
  children,
}: {
  title: string;
  sub?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="tpanel rpt-card">
      <h3>{title}</h3>
      {sub && <p className="rpt-sub">{sub}</p>}
      {children}
    </section>
  );
}

function KV({
  rows,
  columns,
}: {
  rows: [string, string, ('pos' | 'neg')?][];
  columns?: boolean;
}) {
  return (
    <dl className={columns ? 'rpt-kv cols' : 'rpt-kv'}>
      {rows.map(([key, value, kind]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd className={kind ?? ''}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Underwater({ days, values }: { days: string[]; values: number[] }) {
  if (values.length < 2) return <p className="tfine">Not enough points to draw.</p>;
  const W = 720;
  const H = 180;
  const worst = Math.min(...values, 0);
  const x = (i: number) => (i / (values.length - 1)) * W;
  const y = (v: number) => (worst < 0 ? (v / worst) * H : 0);
  const line = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const worstIndex = values.indexOf(worst);
  return (
    <figure className="eqchart">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`Deepest drawdown ${pct(worst)}`}>
        <path d={`${line} L${W},0 L0,0 Z`} className="dd-fill" />
        <path d={line} className="dd-line" />
      </svg>
      <figcaption>
        <span>
          {days[0]} → {days[days.length - 1]}
        </span>
        <span className="neg">
          deepest {pct(worst)}
          {days[worstIndex] ? ` on ${days[worstIndex]}` : ''}
        </span>
      </figcaption>
    </figure>
  );
}

function cellTone(value: number): string {
  const step = Math.min(3, Math.ceil(Math.abs(value) / 0.02));
  if (value === 0 || step === 0) return 'heat-0';
  return value > 0 ? `heat-up${step}` : `heat-dn${step}`;
}

function Heatmap({ months, years }: { months: Map<string, number>; years: Map<string, number> }) {
  const yearList = [...years.keys()];
  if (yearList.length === 0) return <p className="tfine">No complete period to show.</p>;
  return (
    <div className="tscroll">
      <table className="ttable heat">
        <thead>
          <tr>
            <th>Year</th>
            {MONTHS.map((name) => (
              <th key={name} className="r">
                {name}
              </th>
            ))}
            <th className="r">Year</th>
          </tr>
        </thead>
        <tbody>
          {yearList.map((year) => (
            <tr key={year}>
              <td>
                <b>{year}</b>
              </td>
              {MONTHS.map((_, index) => {
                const key = `${year}-${String(index + 1).padStart(2, '0')}`;
                const value = months.get(key);
                return (
                  <td key={key} className={`r ${value === undefined ? '' : cellTone(value)}`}>
                    {value === undefined ? '' : pct(value, 1)}
                  </td>
                );
              })}
              <td className={`r ${cellTone(years.get(year) ?? 0)}`}>
                <b>{pct(years.get(year), 1)}</b>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function csv(trades: Trade[]): string {
  const head = 'symbol,side,entry_day,entry_price,exit_day,exit_price,quantity,net,return\n';
  return (
    head +
    trades
      .map((t) =>
        [
          t.symbol,
          t.side,
          t.entryDay,
          t.entryPrice.toFixed(4),
          t.exitDay ?? '',
          t.exitPrice?.toFixed(4) ?? '',
          t.quantity,
          t.net.toFixed(2),
          t.returnPct.toFixed(6),
        ].join(',')
      )
      .join('\n')
  );
}

function TradeList({
  trades,
  query,
  onQuery,
  money,
  filename,
}: {
  trades: Trade[];
  query: string;
  onQuery: (value: string) => void;
  money: (value: number) => string;
  filename: string;
}) {
  const needle = query.trim().toUpperCase();
  const shown = needle ? trades.filter((t) => t.symbol.toUpperCase().includes(needle)) : trades;
  const download = () => {
    const url = URL.createObjectURL(new Blob([csv(shown)], { type: 'text/csv' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Card title="List of trades" sub="One row per closing fill. A bracket exited in two legs is two trades; costs of both legs are netted in.">
      <div className="ttools" style={{ marginBottom: 12 }}>
        <input
          className="tsearch"
          placeholder="Filter by symbol…"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          aria-label="Filter trades"
        />
        <button className="tbtn" type="button" onClick={download} disabled={shown.length === 0}>
          <Download size={14} aria-hidden="true" style={{ marginRight: 6, verticalAlign: -2 }} />
          CSV
        </button>
      </div>
      <div className="tscroll" style={{ maxHeight: '60vh' }}>
        <table className="ttable">
          <thead>
            <tr>
              <th>#</th>
              <th>Symbol</th>
              <th>Side</th>
              <th>Entry</th>
              <th className="r">Entry price</th>
              <th>Exit</th>
              <th className="r">Exit price</th>
              <th className="r">Qty</th>
              <th className="r">Net P&amp;L</th>
              <th className="r">Return</th>
            </tr>
          </thead>
          <tbody>
            {shown.slice(0, 1000).map((t, index) => (
              <tr key={`${t.symbol}-${t.entryDay}-${index}`}>
                <td className="tdim">{index + 1}</td>
                <td>
                  <b>{t.symbol}</b>
                </td>
                <td>
                  <span className={`ttag ${t.side === 'Long' ? 'long' : 'short'}`}>{t.side}</span>
                </td>
                <td>{t.entryDay}</td>
                <td className="r">{t.entryPrice.toFixed(2)}</td>
                <td>{t.open ? <span className="tdim">open</span> : t.exitDay}</td>
                <td className="r">{t.exitPrice === null ? '—' : t.exitPrice.toFixed(2)}</td>
                <td className="r">{t.quantity}</td>
                <td className={`r ${t.open ? '' : t.net >= 0 ? 'pos' : 'neg'}`}>
                  {t.open ? '—' : money(t.net)}
                </td>
                <td className={`r ${t.open ? '' : t.net >= 0 ? 'pos' : 'neg'}`}>
                  {t.open ? '—' : pct(t.returnPct)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {shown.length === 0 && <div className="tempty">No trades.</div>}
      </div>
      {shown.length > 1000 && (
        <p className="tfine" style={{ marginTop: 8 }}>
          Showing the first 1,000 of {shown.length.toLocaleString('en-IN')}. The CSV has all of them.
        </p>
      )}
    </Card>
  );
}

function OrderList({
  report,
  query,
  onQuery,
  money,
}: {
  report: FullReport;
  query: string;
  onQuery: (value: string) => void;
  money: (value: number) => string;
}) {
  const needle = query.trim().toUpperCase();
  const orders = needle ? report.orders.filter((o) => o.symbol.toUpperCase().includes(needle)) : report.orders;
  return (
    <Card title="Fills" sub={`${orders.length.toLocaleString('en-IN')} of ${report.orders.length.toLocaleString('en-IN')} fills${report.rejections.length ? `, ${report.rejections.length} orders rejected` : ''}.`}>
      <input
        className="tsearch"
        style={{ marginBottom: 12 }}
        placeholder="Filter by symbol…"
        value={query}
        onChange={(event) => onQuery(event.target.value)}
        aria-label="Filter fills"
      />
      <div className="tscroll" style={{ maxHeight: '60vh' }}>
        <table className="ttable">
          <thead>
            <tr>
              <th>Day</th>
              <th>Symbol</th>
              <th>Side</th>
              <th className="r">Qty</th>
              <th className="r">Price</th>
              <th className="r">Notional</th>
              <th className="r">Cost</th>
              <th>Client order id</th>
            </tr>
          </thead>
          <tbody>
            {orders.slice(0, 500).map((order, index) => (
              <tr key={`${order.client_order_id}-${index}`}>
                <td>{order.day}</td>
                <td>
                  <b>{order.symbol}</b>
                </td>
                <td>
                  <span className="ttag">{order.side}</span>
                </td>
                <td className="r">{order.quantity}</td>
                <td className="r">{order.price.toFixed(2)}</td>
                <td className="r">{money(order.notional)}</td>
                <td className="r">{order.cost.toFixed(2)}</td>
                <td className="tdim" style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>
                  {order.client_order_id || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {orders.length > 500 && (
        <p className="tfine" style={{ marginTop: 8 }}>
          Showing the first 500. Filter by symbol to narrow it.
        </p>
      )}
    </Card>
  );
}
