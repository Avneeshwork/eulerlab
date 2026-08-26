'use client';

/**
 * The full analysis of one run.
 *
 * Four things the library row cannot hold: the metrics that do not fit, what
 * each instrument contributed, the order ledger, and the reconciliation between
 * the two.
 *
 * The reconciliation is shown first and unavoidably. A per-instrument
 * decomposition that does not sum to the headline result is worse than no
 * decomposition, because it invites the reader to trust an attribution that is
 * wrong — so whether it adds up is stated rather than assumed.
 */

import { useEffect, useMemo, useState } from 'react';
import { EquityChart } from '@/components/terminal/EquityChart';
import { api } from '@/lib/api';
import { assetClassLabel } from '@/lib/assetClasses';
import type { FleetStrategy, FullReport, RunChoice } from '@/lib/api';

type Tab = 'Summary' | 'Instruments' | 'Orders';

/**
 * Currency follows the market the run was on.
 *
 * This wrote ₹ unconditionally, which was right while every backtest here was
 * NSE and became wrong the moment a US run could be opened: a QQQ report showed
 * "₹25,894" for a figure in dollars, off by the exchange rate and reading as
 * directly comparable to the India runs beside it in the same picker.
 */
const SYMBOL: Record<string, string> = { us: '$', crypto: '$', fx: '$' };

const moneyIn = (assetClass: string) => (value: number) => {
  const symbol = SYMBOL[assetClass] ?? '₹';
  const locale = symbol === '₹' ? 'en-IN' : 'en-US';
  return `${symbol}${value.toLocaleString(locale, { maximumFractionDigits: 0 })}`;
};
const pct = (value: number | null | undefined, digits = 1) =>
  value === null || value === undefined
    ? '—'
    : `${value >= 0 ? '' : '−'}${Math.abs(value * 100).toFixed(digits)}%`;

export function ReportDialog({
  strategy,
  workspace,
  onClose,
}: {
  strategy: FleetStrategy;
  workspace: string;
  onClose: () => void;
}) {
  const [report, setReport] = useState<FullReport | null>(null);
  const [runs, setRuns] = useState<RunChoice[]>([]);
  const [chosen, setChosen] = useState('');
  const [error, setError] = useState('');
  const [tab, setTab] = useState<Tab>('Summary');
  const [orderQuery, setOrderQuery] = useState('');

  useEffect(() => {
    setError('');
    setReport(null);
    api
      .report(strategy.id, workspace, chosen)
      .then((response) => {
        setRuns(response.runs ?? []);
        if (response.ok && response.report) setReport(response.report);
        else setError(response.error ?? 'no report');
      })
      .catch((problem) => setError(problem instanceof Error ? problem.message : String(problem)));
  }, [strategy.id, workspace, chosen]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const orders = useMemo(() => {
    if (!report) return [];
    const needle = orderQuery.trim().toUpperCase();
    return needle ? report.orders.filter((o) => o.symbol.includes(needle)) : report.orders;
  }, [report, orderQuery]);

  const metrics = report?.metrics;
  // Bound to the loaded report's market rather than fixed at module level, so
  // switching runs in the picker switches the currency with them.
  const money = moneyIn(report?.asset_class ?? strategy.asset_class ?? 'equity');

  return (
    <div className="pal-scrim" role="dialog" aria-modal="true" aria-label="Backtest report" onClick={onClose}>
      <div className="dlg wide tall" onClick={(event) => event.stopPropagation()}>
        <header className="dlg-head">
          <div style={{ minWidth: 0 }}>
            <div className="theyebrow">Backtest report</div>
            <h2>{strategy.title}</h2>
            {report && (
              <div className="tfine" style={{ marginTop: 4 }}>
                {/* The market first. Every number below is denominated in it,
                    and a dollar figure read as rupees is wrong by the exchange
                    rate while looking entirely plausible. */}
                <span className="assettag">{assetClassLabel(report.asset_class ?? "equity")}</span>
                {report.instruments.length > 0 ? report.instruments.join(', ') : report.universe} ·{' '}
                {report.window_days}d · {report.period[0]} to {report.period[1]}
              </div>
            )}
          </div>
          <button className="ticon" type="button" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        {/* No run picker. `prune-runs` keeps one stored run per strategy — the
            adopted one, which is both the configuration the strategy is defined
            to use and its most recent measurement — so there is nothing to
            choose between. A picker offering three numbers asked the reader to
            know which of them was the strategy. */}
        <div className="dlg-modes">
          {(['Summary', 'Instruments', 'Orders'] as Tab[]).map((name) => (
            <button
              key={name}
              className="tchip"
              type="button"
              aria-pressed={tab === name}
              onClick={() => setTab(name)}
            >
              {name}
            </button>
          ))}
          {runs.length > 1 && (
            <span className="tfine" style={{ marginLeft: 'auto' }}>
              stands in for {runs.length - 1} superseded run
              {runs.length > 2 ? 's' : ''}
            </span>
          )}
        </div>

        <div className="dlg-body">
          {error && (
            <div className="tnote bad">
              <span className="mk">▲</span>
              <div>{error}</div>
            </div>
          )}
          {!report && !error && <div className="tempty">Reading the report…</div>}

          {report && metrics && (
            <>
              {report.warnings.map((warning) => (
                <p className="tfine" key={warning} style={{ marginBottom: 14 }}>
                  {warning}
                </p>
              ))}

              <div className="recon" data-exact={report.reconciliation.exact}>
                <div>
                  <span>Equity change</span>
                  <b>{money(report.reconciliation.equity_change)}</b>
                </div>
                <div>
                  <span>Attributed to instruments</span>
                  <b>{money(report.reconciliation.attributed)}</b>
                </div>
                <div>
                  <span>Residual</span>
                  <b>{money(report.reconciliation.residual)}</b>
                </div>
                <p>
                  {report.reconciliation.exact
                    ? 'The per-instrument breakdown adds up to the result exactly.'
                    : 'The breakdown does not add up to the result. Treat the attribution below as incomplete.'}
                  {report.reconciliation.unmarked_symbols.length > 0 &&
                    ` Unpriced at the end: ${report.reconciliation.unmarked_symbols.join(', ')}.`}
                </p>
              </div>

              {tab === 'Summary' && (
                <>
                  <div className="report-hero">
                    <div>
                      <div className="theyebrow">Final equity</div>
                      <div className="thnum">
                        <b>{money(report.final_equity)}</b>
                        <span className="unit">from {money(report.starting_cash)}</span>
                      </div>
                    </div>
                  </div>

                  <EquityChart
                    values={report.equity.values}
                    days={report.equity.days}
                    startingCash={report.starting_cash}
                    money={money}
                  />

                  <h4 className="report-h">Return and risk</h4>
                  <div className="tfacts">
                    <Metric label="Sharpe" value={metrics.sharpe.toFixed(2)} />
                    <Metric label="Sortino" value={metrics.sortino?.toFixed(2) ?? '—'} />
                    <Metric label="Total return" value={pct(metrics.total_return)} />
                    <Metric label="Annualised" value={pct(metrics.annualised)} />
                    <Metric label="Volatility" value={pct(metrics.volatility)} />
                    <Metric label="Skew" value={metrics.skew.toFixed(2)} />
                    <Metric label="Kurtosis" value={metrics.kurtosis.toFixed(2)} />
                    <Metric label="Years" value={String(metrics.years)} />
                  </div>

                  <h4 className="report-h">Drawdown</h4>
                  <div className="tfacts">
                    <Metric label="Worst fall" value={pct(metrics.drawdown.depth)} negative />
                    <Metric label="From" value={metrics.drawdown.peak_day ?? '—'} />
                    <Metric label="To" value={metrics.drawdown.trough_day ?? '—'} />
                    <Metric
                      label="Recovered"
                      value={
                        metrics.drawdown.still_underwater
                          ? 'not yet'
                          : (metrics.drawdown.recovered_day ?? '—')
                      }
                      negative={metrics.drawdown.still_underwater}
                    />
                  </div>

                  <h4 className="report-h">Activity</h4>
                  <div className="tfacts">
                    <Metric label="Trading days" value={String(metrics.trading_days)} />
                    <Metric
                      label="Invested"
                      value={pct(metrics.invested_fraction, 0)}
                      negative={metrics.invested_fraction < 0.5}
                    />
                    <Metric label="Flat days" value={String(metrics.flat_days)} />
                    <Metric label="First move" value={metrics.first_move_day ?? '—'} />
                    <Metric label="Hit rate" value={pct(metrics.hit_rate)} />
                    <Metric label="…when invested" value={pct(metrics.hit_rate_invested)} />
                    <Metric label="Best day" value={pct(metrics.best_day, 2)} />
                    <Metric label="Worst day" value={pct(metrics.worst_day, 2)} negative />
                  </div>

                  <h4 className="report-h">Cost of trading</h4>
                  <div className="tfacts">
                    <Metric label="Costs paid" value={money(metrics.costs)} />
                    <Metric label="Cost drag" value={pct(metrics.cost_drag, 2)} negative />
                    <Metric label="Value traded" value={money(metrics.traded_value)} />
                    <Metric label="Turnover" value={`${metrics.turnover_x ?? '—'}×`} />
                    <Metric label="Orders" value={String(report.orders.length)} />
                    <Metric label="Rejections" value={String(report.rejections.length)} />
                  </div>
                </>
              )}

              {tab === 'Instruments' && (
                <div className="tscroll" style={{ maxHeight: '52vh' }}>
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
                      {report.constituents.map((row) => (
                        <tr key={row.symbol}>
                          <td>
                            <b>{row.symbol}</b>
                          </td>
                          <td className={`r${row.contribution < 0 ? ' neg' : ''}`}>
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
              )}

              {tab === 'Orders' && (
                <>
                  <input
                    className="tsearch"
                    style={{ marginBottom: 12 }}
                    placeholder="Filter by symbol…"
                    value={orderQuery}
                    onChange={(event) => setOrderQuery(event.target.value)}
                    aria-label="Filter orders"
                  />
                  <div className="tfine" style={{ marginBottom: 8 }}>
                    {orders.length.toLocaleString('en-IN')} of{' '}
                    {report.orders.length.toLocaleString('en-IN')} fills.
                    {report.rejections.length > 0 &&
                      ` ${report.rejections.length} orders were rejected.`}
                  </div>
                  <div className="tscroll" style={{ maxHeight: '46vh' }}>
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
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  negative,
}: {
  label: string;
  value: string;
  negative?: boolean;
}) {
  return (
    <div className="tfact">
      <span>{label}</span>
      <b className={negative ? 'neg' : ''}>{value}</b>
    </div>
  );
}
