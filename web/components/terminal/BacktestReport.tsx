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
 *
 * The same page reports a paper or live deployment (`deployment` set): the
 * server builds the same payload from its own record (`deploy/analysis.py`),
 * with the curve time-weighted so money added or withdrawn is not a return,
 * the rupees made beside it, and the strategy's backtest figures alongside.
 */

import { useEffect, useMemo, useState } from 'react';
import { Info } from '@/components/terminal/ui';
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
import type { Attribution, AttributionDetail, FleetStrategy, FullReport, RunChoice, Tuning } from '@/lib/api';

type Tab = 'overview' | 'equity' | 'drawdown' | 'returns' | 'trades' | 'instruments' | 'attribution' | 'orders' | 'tuning';

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
  deployment,
  bar,
  workspace,
  onBack,
  backLabel = 'Strategies',
}: {
  strategy: FleetStrategy;
  /** A deployment id: report its paper or live record instead of a backtest. */
  deployment?: string;
  backLabel?: string;
  /** The noise bar, so the Sharpe card can say whether it clears it. */
  bar: number | null;
  workspace: string;
  onBack: () => void;
}) {
  const [report, setReport] = useState<FullReport | null>(null);
  const [attribution, setAttribution] = useState<Attribution | null>(null);
  const [runs, setRuns] = useState<RunChoice[]>([]);
  const [chosen, setChosen] = useState('');
  const [error, setError] = useState('');
  const [tab, setTab] = useState<Tab>('overview');
  const [query, setQuery] = useState('');
  const [tuning, setTuning] = useState<Tuning | null>(null);

  useEffect(() => {
    let live = true;
    if (deployment) return;
    api
      .tuning(strategy.id)
      .then((found) => live && setTuning(found.ran ? found : null))
      .catch(() => live && setTuning(null));
    return () => {
      live = false;
    };
  }, [strategy.id, deployment]);

  useEffect(() => {
    setError('');
    setReport(null);
    if (deployment) {
      api
        .deploymentReport(deployment, workspace)
        .then((response) => {
          if (response.ok && response.report) {
            setReport(response.report);
            setAttribution(response.attribution ?? null);
          } else setError(response.error ?? 'This deployment has nothing to report yet.');
        })
        .catch((problem) => setError(problem instanceof Error ? problem.message : String(problem)));
      return;
    }
    api
      .report(strategy.id, workspace, chosen)
      .then((response) => {
        setRuns(response.runs ?? []);
        if (response.ok && response.report) {
          setReport(response.report);
          setAttribution(response.attribution ?? null);
        }
        else setError(response.error ?? 'This strategy has no stored run to report on yet.');
      })
      .catch((problem) => setError(problem instanceof Error ? problem.message : String(problem)));
  }, [strategy.id, deployment, workspace, chosen]);

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
          <ArrowLeft size={14} aria-hidden="true" /> {backLabel}
        </button>
        <h1>
          {deployment && <span className="assettag">{report?.deployment?.mode === 'live' ? 'Live' : 'Paper'}</span>}{' '}
          {strategy.title}
        </h1>
        <p>
          {report ? (
            <>
              <span className="assettag">{assetClassLabel(market)}</span>{' '}
              {report.instruments.length > 0
                ? report.instruments.slice(0, 6).join(', ') +
                  (report.instruments.length > 6 ? ` +${report.instruments.length - 6} more` : '')
                : report.universe}{' '}
              · {report.period[0]} to {report.period[1]} ·{' '}
              {report.deployment ? (
                <>
                  {report.deployment.status} since {report.deployment.start} · {money(report.deployment.put_in)} put in
                </>
              ) : (
                <>
                  tier {report.tier} · starting capital {money(report.starting_cash)}
                </>
              )}
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
  const dep = report.deployment;
  // A deployment's curve is time-weighted; its rupees made are its own figure.
  const net = dep ? dep.made : report.final_equity - report.starting_cash;
  const clears = bar !== null && m.sharpe >= bar;

  const TABS: { id: Tab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'equity', label: 'Equity' },
    { id: 'drawdown', label: 'Drawdown' },
    { id: 'returns', label: 'Returns' },
    { id: 'trades', label: `Trades (${stats.closed})` },
    { id: 'instruments', label: `Instruments (${report.constituents.length})` },
    ...(attribution ? [{ id: 'attribution' as const, label: 'Attribution' }] : []),
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
        <Stat
          label="Net profit"
          value={money(net)}
          // The % is the rupees over the money behind them, so the pair always
          // agrees. metrics.total_return starts from the first day's close, after
          // that day's costs, and read 58.87% beside Rs 5,87,725 on Rs 10 lakh.
          sub={pct(net / (dep ? dep.put_in : report.starting_cash))}
          tone={tone(net)}
        />
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

      {dep && report.backtest && <AgainstBacktest report={report} />}

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
                <Card title={`Passive hold · ${report.benchmark.symbol}`} sub="Same instrument, bought on the first session and held; the market index comparison is in Attribution.">
                  <KV
                    rows={[
                      ['This strategy', money(net), net >= 0 ? 'pos' : 'neg'],
                      [
                        `Holding ${report.benchmark.symbol}`,
                        money(report.benchmark.net_pnl),
                        report.benchmark.net_pnl >= 0 ? 'pos' : 'neg',
                      ],
                      [
                        'Strategy minus passive hold',
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
              {dep && (
                <Card title="Money" sub="Deposits and withdrawals move these rupees, never the returns.">
                  <KV
                    rows={[
                      [`Starting capital, ${dep.start}`, money(dep.starting_capital)],
                      ...dep.flows.map((flow): [string, string, 'pos' | 'neg'] => [
                        `${flow.amount >= 0 ? 'Added' : 'Withdrawn'} ${flow.day}`,
                        money(flow.amount),
                        flow.amount >= 0 ? 'pos' : 'neg',
                      ]),
                      ['Put in', money(dep.put_in)],
                      ['Equity now', money(dep.equity)],
                      ['Made', money(dep.made), dep.made >= 0 ? 'pos' : 'neg'],
                      ['Return, time-weighted', pct(dep.time_weighted_return)],
                      ['Slippage assumed', `${dep.slippage_bps} bp a fill`],
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
            <span className="ui-chip">{report.reconciliation.exact ? 'Contributions reconcile' : 'Contributions do not reconcile'}</span>
            <Info>
            {report.reconciliation.exact
              ? `Per-instrument contributions add up to the equity change of ${money(report.reconciliation.equity_change)} exactly.`
              : `Per-instrument contributions (${money(report.reconciliation.attributed)}) do not add up to the equity change (${money(report.reconciliation.equity_change)}); the residual is ${money(report.reconciliation.residual)}. Treat the attribution as incomplete.`}
            {report.reconciliation.unmarked_symbols.length > 0 &&
              ` Unpriced at the end: ${report.reconciliation.unmarked_symbols.join(', ')}.`}
            </Info>
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

      {tab === 'attribution' && attribution && (
        <AttributionTab
          a={attribution}
          money={money}
          loadDetail={() =>
            deployment
              ? api.deploymentAttribution(deployment, workspace)
              : api.reportAttribution(strategy.id, workspace, chosen || report.configuration)
          }
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
  sub?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="tpanel rpt-card">
      <h3 className="rpt-card-title">
        {title}
        {sub && <Info>{sub}</Info>}
      </h3>
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
          1,000 / {shown.length.toLocaleString('en-IN')}
          <Info>Showing the first 1,000. The CSV has all of them.</Info>
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
          500 / {orders.length.toLocaleString('en-IN')}
          <Info>Showing the first 500. Filter by symbol to narrow it.</Info>
        </p>
      )}
    </Card>
  );
}

/** A deployment's figures beside its strategy's backtest, metric by metric. */
function AgainstBacktest({ report }: { report: FullReport }) {
  const tested = report.backtest;
  if (!tested) return null;
  const m = report.metrics;
  const rows: [string, number | null | undefined, number | null | undefined, (v: number | null | undefined) => string][] = [
    ['Total return', m.total_return, tested.metrics.total_return, (v) => pct(v)],
    ['CAGR', m.annualised, tested.metrics.annualised, (v) => pct(v)],
    ['Sharpe', m.sharpe, tested.metrics.sharpe, (v) => num(v)],
    ['Sortino', m.sortino, tested.metrics.sortino, (v) => num(v)],
    ['Volatility, a year', m.volatility, tested.metrics.volatility, (v) => pct(v, 1)],
    ['Max drawdown', m.drawdown.depth, tested.max_drawdown, (v) => pct(v)],
    ['Up days', m.hit_rate, tested.metrics.hit_rate, (v) => pct(v, 1)],
    ['Best day', m.best_day, tested.metrics.best_day, (v) => pct(v)],
    ['Worst day', m.worst_day, tested.metrics.worst_day, (v) => pct(v)],
    ['Return given up to costs', m.cost_drag, tested.metrics.cost_drag, (v) => pct(v)],
  ];
  const mode = report.deployment?.mode === 'live' ? 'Live' : 'Paper';
  return (
    <Card
      title={`${mode} against its backtest`}
      sub={`This record (${m.trading_days} days) beside the strategy's longest stored backtest${tested.period ? `, ${tested.period[0]} to ${tested.period[1]}` : ''}. A few weeks is a small sample: annualised figures over it are noisy.`}
    >
      <table className="ttable">
        <thead>
          <tr>
            <th scope="col">Metric</th>
            <th scope="col">{mode}</th>
            <th scope="col">Backtest</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, ours, theirs, show]) => (
            <tr key={label}>
              <td>{label}</td>
              <td>{show(ours)}</td>
              <td>{show(theirs)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

/** Where the return came from: holdings, sectors, years and the market. */
function AttributionTab({
  a,
  money,
  loadDetail,
}: {
  a: Attribution;
  money: (value: number) => string;
  loadDetail: () => Promise<{ ok: boolean; detail?: AttributionDetail; error?: string }>;
}) {
  const [view, setView] = useState<'overview' | 'results' | 'detail'>('overview');
  const [detail, setDetail] = useState<AttributionDetail | null>(null);
  const [detailState, setDetailState] = useState<'idle' | 'loading' | 'error'>('idle');
  const [detailError, setDetailError] = useState('');
  const runDetail = () => {
    setDetailState('loading');
    loadDetail()
      .then((answer) => {
        if (answer.ok && answer.detail) {
          setDetail(answer.detail);
          setDetailState('idle');
        } else {
          setDetailError(answer.error ?? 'No detail came back.');
          setDetailState('error');
        }
      })
      .catch((problem) => {
        setDetailError(problem instanceof Error ? problem.message : String(problem));
        setDetailState('error');
      });
  };
  const h = a.holdings;
  const m = a.market;
  const share = (v: number | null | undefined) => pct(v ?? null, 0);
  const holdingsBars = [...h.best, ...h.worst]
    .sort((x, y) => y.contribution - x.contribution)
    .map((row) => ({ label: row.symbol, value: row.contribution, detail: share(h.net_profit ? row.contribution / h.net_profit : null) }));
  return (
    <>
      <section className="att-summary">
        <div className="att-summary-copy">
          <span className="att-eyebrow">RETURN DRIVERS</span>
          <h2>Where did the return come from?</h2>
          <p>Start with the names that moved the result, then check whether the gains were broad, steady, and independent of the market.</p>
        </div>
        <div className="att-kpis">
          <div><span>Net contribution</span><b className={h.net_profit >= 0 ? 'pos' : 'neg'}>{money(h.net_profit)}</b><small>{h.names} names traded</small></div>
          <div><span>Win rate by name</span><b>{share(h.names ? h.winners / h.names : null)}</b><small>{h.winners} winners · {h.losers} losers</small></div>
        </div>
      </section>

      <nav className="att-nav" aria-label="Attribution views">
        {([
          ['overview', 'Overview', true],
          ['results', 'Performance drivers', true],
          ['detail', 'Full analysis', true],
        ] as const).map(([id, label, available]) => <button key={id} type="button" disabled={!available} aria-pressed={view === id} onClick={() => setView(id)}>{label}{id === 'detail' && detail && <span className="att-nav-ready">Ready</span>}</button>)}
      </nav>

      <div hidden={view !== 'overview'}>
      <div className="att-grid att-primary-grid">
        <Card title="Holdings that moved the result" sub="Best and worst instrument contribution, after costs. Share is relative to net profit.">
          <ContributionTiles rows={holdingsBars} money={money} />
          <div className="att-chart-legend"><span><i className="att-dot gain" /> Added return</span><span><i className="att-dot loss" /> Reduced return</span><span className="att-chart-hint">Tile area shows contribution size</span></div>
        </Card>
        <Card title="Profit concentration" sub="Share of gross gains from winning holdings. Losses do not shrink the denominator. Use the exclusion returns to see whether the strategy stayed profitable without its biggest contributors.">
          <div className="att-concentration">
            <div className="att-donut" style={{ background: `conic-gradient(var(--up) 0 ${Math.max(0, Math.min(100, (h.share_of_gross_profit.top_5 ?? 0) * 100))}%, var(--surface-3) 0 100%)` }}><div><b>{share(h.share_of_gross_profit.top_5)}</b><span>top five winners</span></div></div>
            <div className="att-concentration-stats">
              <div><span>Top winner</span><b>{share(h.share_of_gross_profit.top_1)}</b></div>
              <div><span>Top ten winners</span><b>{share(h.share_of_gross_profit.top_10)}</b></div>
              <div className="att-concentration-divider" />
              <div><span>Excluding top name</span><b className={(h.without_top_1.annualised ?? 0) < 0 ? 'neg' : 'pos'}>{pct(h.without_top_1.annualised)}</b><small>Total {pct(h.without_top_1.total_return)}</small></div>
              <div><span>Excluding top five</span><b className={(h.without_top_5.annualised ?? 0) < 0 ? 'neg' : 'pos'}>{pct(h.without_top_5.annualised)}</b><small>Total {pct(h.without_top_5.total_return)}</small></div>
              <div><span>Winners for 50% / 80% of gains</span><b>{h.names_for_half ?? '—'} / {h.names_for_four_fifths ?? '—'}</b></div>
            </div>
          </div>
        </Card>
      </div>

      {a.note && (
        <p className="tfine att-note">
          Method <Info>{a.note}</Info>
        </p>
      )}
      </div>

      <section className="att-view" hidden={view !== 'results'}>
        <div className="att-view-heading"><div><span className="att-eyebrow">PERFORMANCE DRIVERS</span><h2>How did the strategy perform?<Info>Read sector and industry contribution, performance over time, and market exposure together.</Info></h2></div><span className="att-view-count">{a.years.filter((y) => (y.return ?? 0) > 0).length} positive years · {h.names} names</span></div>
        <div className="att-results-grid">
          {a.sectors && (['sector', 'industry'] as const).map((level) => <Card key={level} title={`${level === 'sector' ? 'Sector' : 'Industry'} contribution`} sub="Net contribution after costs; bar detail shows share and breadth of winners."><ContributionBars rows={a.sectors![level].map((r) => ({ label: r.name, value: r.contribution, detail: `${share(r.share)} · ${r.winners}/${r.names} positive` }))} money={money} compact /></Card>)}
          {m && <Card title={`Market comparison · ${m.index}`} sub={`${m.from} to ${m.through} · close-to-close price return, excluding distributions · ${m.days} matched sessions. The annual residual is the raw-return regression intercept; no risk-free rate is available.${m.days < 60 ? ' Cumulative comparison only; beta and residual need 60 sessions.' : ''}`}>
            <div className="att-market-hero"><div><span>Strategy cumulative</span><b className={(m.strategy_total ?? 0) < 0 ? 'neg' : 'pos'}>{pct(m.strategy_total)}</b></div><div><span>{m.index} price return</span><b className={(m.market_total ?? 0) < 0 ? 'neg' : 'pos'}>{pct(m.market_total)}</b></div></div>
            <div className="att-market-grid">{[['Market-model residual / year', pct(m.alpha_annual)], ['Market-linked return / year', pct(m.from_market_annual)], ['Beta', num(m.beta)], ['Correlation', num(m.correlation)], ['R² explained', pct(m.r_squared, 0)]].map(([label, value]) => <div key={label}><span>{label}</span><b>{value}</b></div>)}</div>
          </Card>}
          <div className="att-result-years"><Card title="Annual return profile" sub="Return, net trading profit, and leading contributor for each year."><YearBars rows={a.years.map((y) => ({ label: y.year, value: y.return, detail: y.top_symbol ?? '—', subdetail: share(y.top_share), profit: y.trading_profit, topProfit: y.top_profit }))} money={money} /></Card></div>
        </div>
        {!detail && <p className="att-insight">Run <button className="att-inline-link" type="button" onClick={() => setView('detail')}>Full analysis</button> to see Brinson allocation and selection effects, factor exposures, risk drivers, drawdowns, and trade behavior.</p>}
      </section>

      <section className="att-view" hidden={view !== 'detail'}>
        <div className="att-view-heading"><div><span className="att-eyebrow">MODEL DIAGNOSTICS</span><h2>Full analysis<Info>Rebuilt holdings, sector effects, factors, risk, drawdowns, trade behavior and capacity.</Info></h2></div><span className="att-view-count">{detail ? `Rebuilt in ${detail.seconds}s` : 'On-demand'}</span></div>

      {!detail && <Card title="Build full analysis" sub="Rebuild the trade history, then calculate sector effects, factor exposure, risk and execution diagnostics.">
        <div className="att-analysis-launch">
          <button className="tbtn go" type="button" disabled={detailState === 'loading'} onClick={runDetail}>
            {detailState === 'loading' ? 'Rebuilding portfolio history… (about a minute the first time)' : 'Run full analysis'}
          </button>
          {detailState !== 'loading' && <span>Calculates once, then the result stays open while you inspect the sections.</span>}
        </div>
        {detailState === 'error' && <div className="tnote bad">{detailError}</div>}
      </Card>}
      {detail && <DetailViews d={detail} money={money} />}
      </section>
    </>
  );
}

function ContributionBars({ rows, money, compact = false, formatValue }: { rows: { label: string; value: number; detail?: string }[]; money: (value: number) => string; compact?: boolean; formatValue?: (value: number) => string }) {
  const max = Math.max(1, ...rows.map((row) => Math.abs(row.value)));
  if (!rows.length) return <p className="tfine">No contributions to show.</p>;
  return <div className={`att-bars${compact ? ' compact' : ''}`}>
    {rows.map((row) => <div className="att-bar-row" key={row.label}>
      <b className="att-bar-label" title={row.label}>{row.label}</b>
      <div className="att-bar-track"><div className={`att-bar-fill ${row.value < 0 ? 'loss' : 'gain'}`} style={{ width: `${Math.max(1, Math.abs(row.value) / max * 50)}%` }} /></div>
      <strong className={row.value < 0 ? 'neg' : 'pos'}>{formatValue ? formatValue(row.value) : money(row.value)}</strong>
      {row.detail && <span className="att-bar-detail">{row.detail}</span>}
    </div>)}
  </div>;
}

function ContributionTiles({ rows, money, large = false }: { rows: { label: string; value: number; detail?: string }[]; money: (value: number) => string; large?: boolean }) {
  const max = Math.max(1, ...rows.map((row) => Math.abs(row.value)));
  return <div className={`att-tiles${large ? ' large' : ''}`}>
    {rows.map((row) => <div key={row.label} className={`att-tile ${row.value < 0 ? 'loss' : 'gain'}`} style={{ gridColumn: `span ${Math.max(2, Math.min(6, Math.round((Math.abs(row.value) / max) * 6)))}` }}>
      <span>{row.label}</span><b>{row.value < 0 ? '−' : '+'}{money(Math.abs(row.value))}</b>{row.detail && <small>{row.detail} of net</small>}
    </div>)}
  </div>;
}

function YearBars({ rows, money }: { rows: { label: string; value: number | null; detail: string; subdetail: string; profit?: number; topProfit?: number | null }[]; money?: (value: number) => string }) {
  const max = Math.max(0.01, ...rows.map((row) => Math.abs(row.value ?? 0)));
  return <div className="att-years">
    {rows.map((row) => <div className="att-year" key={row.label}>
      <b className={(row.value ?? 0) < 0 ? 'neg' : 'pos'}>{pct(row.value, 0)}</b>
      <div className="att-year-plot"><div className={`att-year-bar ${(row.value ?? 0) < 0 ? 'loss' : ''}`} style={{ height: `${Math.max(4, Math.abs(row.value ?? 0) / max * 100)}%` }} /></div>
      <span className="att-year-label">{row.label}</span><small>{row.detail} · {row.subdetail} share</small>
      {row.profit !== undefined && money && <small className={row.profit < 0 ? 'neg' : 'pos'}>Net {money(row.profit)}</small>}
      {row.topProfit !== undefined && row.topProfit !== null && money && <small>Driver {money(row.topProfit)}</small>}
    </div>)}
  </div>;
}

function MonthBars({ rows, money }: { rows: { month: string; return: number | null; drivers: { symbol: string; profit: number }[] }[]; money: (value: number) => string }) {
  const max = Math.max(0.01, ...rows.map((row) => Math.abs(row.return ?? 0)));
  return <div className="att-month-list">{rows.map((row) => <div className="att-month-row" key={row.month}>
    <b>{row.month}</b><div className="att-month-track"><div className={(row.return ?? 0) < 0 ? 'loss' : 'gain'} style={{ width: `${Math.max(3, Math.abs(row.return ?? 0) / max * 100)}%` }} /></div>
    <strong className={(row.return ?? 0) < 0 ? 'neg' : 'pos'}>{pct(row.return, 1)}</strong><span>{row.drivers.map((driver) => `${driver.symbol} ${money(driver.profit)}`).join(' · ')}</span>
  </div>)}</div>;
}

function RollingRows({ rows }: { rows: { month: string; beta: number | null; alpha_annual: number | null }[] }) {
  const max = Math.max(0.01, ...rows.map((row) => Math.abs(row.alpha_annual ?? 0)));
  return <div className="att-rolling-rows">{rows.map((row) => {
    const alpha = row.alpha_annual ?? 0;
    return <div className="att-rolling-row" key={row.month}>
      <b>{row.month}</b><div className="att-rolling-track"><i className={alpha < 0 ? 'loss' : 'gain'} style={{ width: `${Math.max(1, Math.abs(alpha) / max * 50)}%`, ...(alpha < 0 ? { right: '50%' } : { left: '50%' }) }} /></div>
      <span className={alpha < 0 ? 'neg' : 'pos'}>{pct(row.alpha_annual, 1)} residual</span><span>β {num(row.beta)}</span>
    </div>;
  })}</div>;
}

/** The detailed attribution, section by section. */
function DetailViews({ d, money }: { d: AttributionDetail; money: (value: number) => string }) {
  const share = (v: number | null | undefined, digits = 0) => pct(v ?? null, digits);
  const tone2 = (v: number | null | undefined) => ((v ?? 0) >= 0 ? 'pos' : 'neg');
  const e = d.exposure;
  return (
    <>
      <div className={`tnote ${d.rebuild.trusted ? 'ok' : 'warn'}`}>
        <span className="mk">{d.rebuild.trusted ? '✓' : '!'}</span>
        <div>
          Rebuilt book matches the stored equity to within {share(d.rebuild.max_gap, 2)}. {d.rebuild.trusted ? '' : 'Holdings-based views are provisional because the rebuild does not agree with the run.'}{' '}
          {d.rebuild.note}
        </div>
      </div>

      <section className="att-analysis-section">
        <div className="att-analysis-heading"><div><span className="att-eyebrow">RETURNS & DRIVERS</span><h3>What produced the return?<Info>Sector decisions and style exposure, with sample size and model limits alongside the estimates.</Info></h3></div><span className="att-view-count">{d.factors ? `${d.factors.months} monthly observations` : 'Coverage notes below'}</span></div>
        <div className="att-analysis-grid">
          {d.brinson && <div className="att-analysis-card att-analysis-brinson">
            <Card title="Brinson–Fachler attribution" sub={`Sector effects use the ${d.brinson.benchmark} reference basket over ${d.brinson.months} months, linked with Carino and current NSE sector labels. This model is separate from the NIFTYBEES / S&P 500 market comparison in Performance drivers.`}>
              <div className="att-brinson-metrics">
                {[
                  ['Actual strategy', share(d.brinson.actual_total, 1), d.brinson.actual_total],
                  ['Month-start portfolio', share(d.brinson.portfolio_buy_hold, 1), d.brinson.portfolio_buy_hold],
                  ['Benchmark total', share(d.brinson.benchmark_total, 1), d.brinson.benchmark_total],
                  ['Benchmark annual', share(d.brinson.benchmark_annual, 1), d.brinson.benchmark_annual],
                ].map(([label, value, raw]) => <div key={String(label)}><span>{String(label)}</span><b className={tone2(Number(raw))}>{String(value)}</b></div>)}
              </div>
              <div className="att-detail-viz">
                <div className="att-detail-viz-title"><b>Active return drivers</b><span>Annualised contributions</span></div>
                <ContributionBars rows={[
                  { label: 'Allocation', value: d.brinson.allocation ?? 0 },
                  { label: 'Selection', value: d.brinson.selection ?? 0 },
                  { label: 'Interaction', value: d.brinson.interaction ?? 0 },
                  { label: 'Trading', value: d.brinson.trading ?? 0 },
                ]} money={money} formatValue={(v) => pct(v, 1)} compact />
              </div>
              <div className="tscroll"><table className="ttable">
                <thead><tr><th>Sector</th><th className="r">Weight (bench.)</th><th className="r">Allocation</th><th className="r">Selection</th><th className="r">Interaction</th><th className="r">Total</th></tr></thead>
                <tbody>{d.brinson.sectors.map((r) => <tr key={r.sector}>
                  <td>{r.sector}</td><td className="r">{share(r.average_weight)} ({share(r.benchmark_weight)})</td>
                  <td className={`r ${tone2(r.allocation)}`}>{share(r.allocation, 1)}</td><td className={`r ${tone2(r.selection)}`}>{share(r.selection, 1)}</td>
                  <td className={`r ${tone2(r.interaction)}`}>{share(r.interaction, 1)}</td><td className={`r ${tone2(r.total)}`}>{share(r.total, 1)}</td>
                </tr>)}</tbody>
              </table></div>
            </Card>
          </div>}

          <div className="att-analysis-card att-analysis-factors"><FactorModelCard factors={d.factors} note={d.factor_note} /></div>
          {!d.brinson && d.brinson_note && <div className="att-analysis-card att-analysis-brinson-note"><Card title="Sector attribution coverage" sub={d.brinson_note}><div className="ui-empty">—</div></Card></div>}
        </div>
      </section>

      <section className="att-analysis-section">
        <div className="att-analysis-heading"><div><span className="att-eyebrow">PORTFOLIO & RISK</span><h3>How the book was invested<Info>Exposure, concentration of risk, and the periods that hurt most.</Info></h3></div></div>
        <div className="att-analysis-grid">
          {e && <div className="att-analysis-card">
            <Card title="Portfolio exposure" sub={e.note}>
              <div className="att-market-hero"><div><span>Average invested</span><b>{share(e.invested_mean)}</b></div><div><span>Peak invested</span><b>{share(e.invested_max)}</b></div></div>
              {(e.invested_max ?? 0) > 1.02 && <div className="tnote warn"><span className="mk">!</span><div>This run was more than fully invested: {share(e.invested_mean)} on average, up to {share(e.invested_max)}. Cash went negative, so part of the return was earned on money the strategy did not have.</div></div>}
              <div className="att-detail-viz"><div className="att-detail-viz-title"><b>Capital deployed by year</b><span>Average invested</span></div>
                <div className="att-exposure-bars">{e.by_year.map((y) => <div key={y.year} className="att-exposure-row"><b>{y.year}</b><div className="att-bar-track"><div className="att-bar-fill gain" style={{ width: `${Math.max(0, Math.min(100, (y.invested ?? 0) * 100))}%` }} /></div><strong>{share(y.invested, 0)}</strong><span>{num(y.holdings, 1)} holdings · {num(y.effective_holdings, 1)} effective</span></div>)}</div>
              </div>
              {e.frozen.length > 0 && <div className="tscroll"><p className="tfine"><b>Frozen positions</b><Info>Held after the stock&apos;s last price in the data (renamed or delisted).</Info></p><table className="ttable"><thead><tr><th>Symbol</th><th>Last price</th><th>Held until</th><th className="r">Value then</th></tr></thead><tbody>{e.frozen.map((f) => <tr key={f.symbol}><td>{f.symbol}</td><td>{f.last_price}</td><td>{f.held_until}</td><td className="r">{money(f.value)}</td></tr>)}</tbody></table></div>}
            </Card>
          </div>}

          {d.risk && <div className="att-analysis-card">
            <Card title="Risk contribution" sub={`Book as of ${d.risk.as_of} · volatility ${share(d.risk.volatility_annual)} a year · ${share(d.risk.invested)} invested. Contributions use Euler allocation.`}>
              <ContributionBars rows={d.risk.holdings.map((h) => ({ label: h.symbol, value: h.share_of_risk ?? 0, detail: `${share(h.weight, 1)} weight` }))} money={money} formatValue={(v) => share(v, 1)} compact />
              <div className="att-detail-viz"><div className="att-detail-viz-title"><b>Risk by sector</b><span>Share of portfolio risk</span></div><ContributionBars rows={d.risk.sectors.map((r) => ({ label: r.sector, value: r.share_of_risk ?? 0 }))} money={money} formatValue={(v) => share(v, 1)} compact /></div>
            </Card>
          </div>}

          {d.drawdowns.length > 0 && <div className="att-analysis-card">
            <Card title="Drawdown episodes" sub="Peak to trough, recovery status, and the holdings that contributed most to each loss.">
              <div className="att-drawdown-list">{d.drawdowns.map((x) => <div className="att-drawdown-row" key={x.peak}>
                <div className="att-dd-depth"><b>{share(x.depth)}</b><span>{x.days_to_trough} days to trough</span></div>
                <div className="att-dd-timeline"><b>{x.peak} → {x.trough}</b><span>{x.recovered ? `Recovered ${x.recovered}` : 'Not recovered'}</span></div>
                <div className="att-dd-drivers">{x.worst.map((w) => <span key={w.symbol}>{w.symbol} <b>{money(w.loss)}</b> · {share(w.share)} of episode</span>)}</div>
              </div>)}</div>
            </Card>
          </div>}

          {d.months.best.length > 0 && <div className="att-analysis-card">
            <Card title="Best and worst months" sub="Monthly outcome with the three holdings that moved most.">
              <MonthBars rows={[...d.months.best, ...d.months.worst]} money={money} />
            </Card>
          </div>}
        </div>
      </section>

      <section className="att-analysis-section">
        <div className="att-analysis-heading"><div><span className="att-eyebrow">TRADING & ROBUSTNESS</span><h3>Does the edge survive execution and time?<Info>Trade outcomes, capacity limits, and rolling market-adjusted results.</Info></h3></div></div>
        <div className="att-analysis-grid">
          {d.trades.by_holding_period && <div className="att-analysis-card">
            <Card title="Trade outcomes by holding period" sub={`${d.trades.closed} closed trades · best 1% (${d.trades.best_1pct_trades}) generated ${share(d.trades.best_1pct_share_of_gross_profit)} of gross profit · win/loss payoff ${num(d.trades.payoff_ratio)}.`}>
              <ContributionBars rows={d.trades.by_holding_period.map((b) => ({ label: b.holding, value: b.net, detail: `${b.trades} trades · ${share(b.win_rate)} won · avg ${share(b.average_return, 1)}` }))} money={money} compact />
            </Card>
          </div>}
          {d.trades.by_sector && <div className="att-analysis-card">
            <Card title="Trade outcomes by sector" sub={`${d.trades.closed} closed trades · net result and sector win rate.`}>
              <ContributionBars rows={d.trades.by_sector.map((b) => ({ label: b.sector, value: b.net, detail: `${b.trades} trades · ${share(b.win_rate)} won` }))} money={money} compact />
            </Card>
          </div>}
          {d.capacity && <div className="att-analysis-card">
            <Card title="Strategy capacity" sub={`${d.capacity.entries} buys measured against median daily turnover over the preceding 60 sessions, at ${share(d.capacity.participation)} participation.`}>
              <div className="att-capacity-kpis"><div><span>Typical buy, days to trade</span><b>{num(d.capacity.median_days_to_trade, 3)}</b></div><div><span>90th percentile</span><b>{num(d.capacity.p90_days_to_trade, 3)} <small>days</small></b></div><div><span>Capital for 90% same day</span><b>{money(d.capacity.capital_where_90pct_trade_in_a_day)}</b></div><div><span>Capital for half same day</span><b>{money(d.capacity.capital_where_median_trades_in_a_day)}</b></div></div>
              {d.capacity.note && <p className="tfine">Note <Info>{d.capacity.note}</Info></p>}
              <div className="att-tightest"><b>Most constrained buys</b>{d.capacity.tightest.map((t) => <div key={`${t.symbol}-${t.day}`}><span>{t.symbol} · {t.day}</span><b>{money(t.capital_for_one_day)}</b></div>)}</div>
            </Card>
          </div>}
          {d.rolling.length > 0 && <div className="att-analysis-card att-analysis-rolling">
            <Card title={`Rolling twelve-month market model · ${d.market_label}`} sub="Market beta and the annualized regression residual through time. Raw returns are used, with no risk-free rate.">
              <RollingRows rows={d.rolling} />
            </Card>
          </div>}
        </div>
      </section>
    </>
  );
}

const houseFactorCatalog: Record<string, { label: string; short: string; construction: string }> = {
  market: {
    label: 'Market',
    short: 'Broad market exposure',
    construction: 'A beta near 1 means the strategy moved about one-for-one with the reference market in this sample.',
  },
  size: {
    label: 'Size · turnover proxy',
    short: 'Lower-turnover minus higher-turnover stocks',
    construction: 'Within the 500 most-traded stocks, the bottom half by turnover minus the top half. Turnover stands in for size because point-in-time market capitalisation is not held.',
  },
  momentum: {
    label: 'Momentum · 12–1',
    short: 'Recent winners minus recent losers',
    construction: 'Within the same 500-stock universe, the top 30% minus bottom 30% by return from 12 months ago to 1 month ago. The skipped month reduces short-term reversal overlap.',
  },
  low_volatility: {
    label: 'Low volatility',
    short: 'Lower-volatility minus higher-volatility stocks',
    construction: 'Within the same universe, the bottom 30% minus top 30% by trailing 12-month monthly volatility.',
  },
};

const officialUsFactorCatalog: Record<string, { label: string; short: string; construction: string }> = {
  market: { label: 'Market · Mkt-RF', short: 'U.S. market excess return', construction: 'Broad U.S. market return less the published one-month risk-free rate. The strategy exposure is measured against this factor; the S&P 500 comparison is shown separately using SPY.' },
  size: { label: 'Size · SMB', short: 'Small minus big stocks', construction: 'The published Small Minus Big return factor from Kenneth French’s U.S. factor library.' },
  value: { label: 'Value · HML', short: 'High minus low book-to-market', construction: 'The published High Minus Low book-to-market return factor.' },
  profitability: { label: 'Profitability · RMW', short: 'Robust minus weak profitability', construction: 'The published Robust Minus Weak operating-profitability return factor.' },
  investment: { label: 'Investment · CMA', short: 'Conservative minus aggressive investment', construction: 'The published Conservative Minus Aggressive investment return factor.' },
  momentum: { label: 'Momentum · Mom', short: 'Prior winners minus prior losers', construction: 'The published winner-minus-loser factor, formed from prior returns over months −12 to −2.' },
};

function FactorModelCard({ factors, note }: { factors: AttributionDetail['factors']; note: string | null }) {
  if (!factors) return <Card title="Factor model unavailable" sub={note ?? 'The return history does not support a factor estimate yet.'}><div className="ui-empty">—</div></Card>;
  const catalog = factors.model_name.startsWith('Fama/French') ? officialUsFactorCatalog : houseFactorCatalog;
  const factorLabel = (key: string) => catalog[key]?.label ?? (key === 'risk_free' ? 'Risk-free return' : key.replaceAll('_', ' '));
  const contributionRows = [
    ...Object.entries(factors.exposures).map(([key, value]) => ({
      label: factorLabel(key),
      value: value.contribution_annual ?? 0,
      detail: `β ${num(value.beta)} · t ${num(value.t)}`,
    })),
    ...(factors.risk_free_annual == null ? [] : [{ label: 'Risk-free return', value: factors.risk_free_annual, detail: 'Published RF' }]),
    { label: 'Model residual', value: factors.alpha_annual ?? 0, detail: `t ${num(factors.alpha_t)}` },
  ];
  return <Card title="Factor attribution" sub={`${factors.model_name} · ${factors.period_from ?? '—'} to ${factors.period_through ?? '—'} · ${factors.months} monthly observations · ${factors.factors}.`}>
    {note && <div className="att-factor-note"><b>Model coverage<Info>{note}</Info></b>{factors.source_url && <a href={factors.source_url} target="_blank" rel="noreferrer">Data source</a>}</div>}
    <div className="att-factor-kpis">
      <div><span>Strategy average / year</span><b className={(factors.strategy_annual ?? 0) < 0 ? 'neg' : 'pos'}>{pct(factors.strategy_annual, 1)}</b><small>Arithmetic monthly mean × 12</small></div>
      <div><span>Model intercept / year</span><b className={(factors.alpha_annual ?? 0) < 0 ? 'neg' : 'pos'}>{pct(factors.alpha_annual, 1)}</b><small>Regression intercept × 12</small></div>
      <div><span>Model fit</span><b>{pct(factors.r_squared, 0)}</b><small>R² · adjusted {pct(factors.adjusted_r_squared, 0)}</small></div>
      <div><span>Sample</span><b>{factors.months} <small>months</small></b><small>{factors.period_from ?? '—'} — {factors.period_through ?? '—'}</small></div>
    </div>

    <div className="att-detail-viz att-factor-waterfall">
      <div className="att-detail-viz-title"><b>What the model assigns to each driver<Info>Factor contributions + model residual reconcile to the strategy&apos;s annualized arithmetic return, within rounding. This regression describes co-movement; it does not prove that a factor caused the return.</Info></b><span>Annualized arithmetic contribution</span></div>
      <ContributionBars rows={contributionRows} money={() => ''} compact formatValue={(value) => pct(value, 1)} />

    </div>

    <div className="att-factor-details">
      {Object.entries(factors.exposures).map(([key, value]) => {
        const meta = catalog[key] ?? { label: key.replaceAll('_', ' '), short: 'Custom return spread', construction: 'Custom long-short spread constructed from the available equity panel.' };
        const construction = key === 'market' && factors.risk_free_annual == null ? `Monthly close-to-close return on ${factors.market_label}. ${meta.construction}` : meta.construction;
        const tValue = value.t ?? 0;
        return <article className="att-factor-detail" key={key}>
          <div className="att-factor-detail-top"><div><b>{meta.label}</b><span>{meta.short}</span></div><i className={Math.abs(tValue) >= 2 ? 'evidence' : ''}>t {num(value.t)}</i></div>
          <div className="att-factor-detail-metrics">
            <div><span>Strategy exposure (β)</span><b>{num(value.beta)}</b></div>
            <div><span>Factor return / year</span><b className={(value.factor_annual ?? 0) < 0 ? 'neg' : 'pos'}>{pct(value.factor_annual, 1)}</b></div>
            <div><span>Return contribution / year</span><b className={(value.contribution_annual ?? 0) < 0 ? 'neg' : 'pos'}>{pct(value.contribution_annual, 1)}</b></div>
          </div>
          <span className="att-factor-how">How it is built <Info>{construction}</Info></span>
        </article>;
      })}
    </div>

    {factors.yearly.length > 1 && <div className="att-factor-years">
      <div className="att-detail-viz-title"><b>Factor contribution by year<Info>Factor pieces use full-period betas; the residual is the observed return left after those pieces in that year, so each row reconciles. Values are annualized monthly averages, not compounded annual returns. The final partial year uses only its observed months.</Info></b><span>Full-period exposures held fixed</span></div>
      <FactorYearRows periods={factors.yearly} officialUs={factors.model_name.startsWith('Fama/French')} />
    </div>}

    <p className="tfine att-factor-method">Model assumptions and reliability <Info>Monthly ordinary least squares. The model uses {factors.inference}; t-statistics are a noise check, not a pass/fail test. As a rough convention, |t| below 2 means the estimate is uncertain in this sample. {factors.risk_free_annual == null ? 'No risk-free rate is available for this model.' : 'The published risk-free rate is included for this model.'} The intercept is not proof of skill or future alpha.</Info></p>
  </Card>;
}

function FactorYearRows({ periods, officialUs }: { periods: NonNullable<AttributionDetail['factors']>['yearly']; officialUs: boolean }) {
  const catalog = officialUs ? officialUsFactorCatalog : houseFactorCatalog;
  const keys = Object.keys(periods[0]?.contributions ?? {});
  const maxSide = Math.max(0.01, ...periods.map((row) => {
    const values = Object.values(row.contributions).map((value) => value ?? 0);
    return Math.max(values.filter((value) => value > 0).reduce((sum, value) => sum + value, 0), Math.abs(values.filter((value) => value < 0).reduce((sum, value) => sum + value, 0)));
  }));
  const color: Record<string, string> = { market: 'market', size: 'size', value: 'value', profitability: 'profitability', investment: 'investment', momentum: 'momentum', low_volatility: 'lowvol', risk_free: 'riskfree', residual: 'residual' };
  return <div className="att-factor-year-list">
    <div className="att-factor-year-legend">{keys.map((key) => <span key={key}><i className={color[key] ?? 'other'} />{key === 'residual' ? 'Residual' : key === 'risk_free' ? 'Risk-free return' : catalog[key]?.label ?? key}</span>)}</div>
    {periods.map((period) => {
      let leftUsed = 0;
      let rightUsed = 0;
      return <div className="att-factor-year-entry" key={period.year}>
        <div className="att-factor-year-row">
          <b>{period.year}<small>{period.months} mo</small></b>
          <div className="att-factor-year-track" aria-label={`Factor contributions in ${period.year}`}>
            {keys.map((key) => {
              const value = period.contributions[key] ?? 0;
              const width = Math.abs(value) / maxSide * 50;
              const left = value >= 0 ? 50 + rightUsed : 50 - leftUsed - width;
              if (value >= 0) rightUsed += width;
              else leftUsed += width;
              return width > 0 ? <i key={key} title={`${key === 'residual' ? 'Residual' : key === 'risk_free' ? 'Risk-free return' : catalog[key]?.label ?? key}: ${pct(value, 1)}`} className={color[key] ?? 'other'} style={{ left: `${left}%`, width: `${width}%` }} /> : null;
            })}
          </div>
          <strong className={(period.strategy_annual ?? 0) < 0 ? 'neg' : 'pos'}>{pct(period.strategy_annual, 1)}</strong>
        </div>
        <div className="att-factor-year-values">{keys.map((key) => <span key={key} title={key === 'residual' ? 'Model residual' : key === 'risk_free' ? 'Risk-free return' : catalog[key]?.label ?? key}><i className={color[key] ?? 'other'} />{pct(period.contributions[key], 1)}</span>)}</div>
      </div>;
    })}
  </div>;
}
