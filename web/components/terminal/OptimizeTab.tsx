'use client';

/**
 * What the last parameter sweep found, with the number that makes it readable.
 *
 * The table leads with best *and* median, side by side and equally weighted,
 * because the maximum of N draws from noise rises with N: a sweep that reports
 * only its winner has found the right tail of a sample. The ratio between them
 * is the tell, and it is shown as its own column rather than left for the
 * reader to divide.
 *
 * There is no button here that starts a sweep, and that omission is deliberate.
 * Every candidate evaluated spends a permanent trial against the
 * deflated-Sharpe denominator and raises the bar for every result this platform
 * holds. That cost belongs to an operator running `make optimize` on purpose,
 * not to whoever clicked a tab.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Optimize, OptimizeRow } from '@/lib/api';

const MARKET_LABEL: Record<string, string> = {
  us: 'US',
  crypto: 'Crypto',
  equity: 'India',
};

function money(value: number): string {
  const sign = value < 0 ? '−' : '';
  return `${sign}₹${Math.abs(Math.round(value)).toLocaleString('en-IN')}`;
}

/** How much of the best is above the median, as a share of the best. */
function tailShare(row: OptimizeRow): number | null {
  if (row.best_pnl <= 0) return null;
  return Math.max(0, row.beats_its_median_by) / row.best_pnl;
}

function Verdict({ row }: { row: OptimizeRow }) {
  if (row.error) return <span className="verdict verdict-error">{row.error}</span>;
  if (!row.profitable) return <span className="verdict verdict-loss">loses on every setting</span>;

  const share = tailShare(row);
  if (share !== null && share > 0.5) {
    return <span className="verdict verdict-tail">best is mostly tail</span>;
  }
  if (share !== null && share < 0.2) {
    return <span className="verdict verdict-flat">flat across the grid</span>;
  }
  return <span className="verdict verdict-ok">profitable</span>;
}

export function OptimizeTab() {
  const [data, setData] = useState<Optimize | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .optimize()
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="muted">Could not load the sweep: {error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  if (!data.ran) {
    return (
      <div className="optimize">
        <p className="muted">{data.note ?? 'No sweep has been recorded.'}</p>
        <p className="muted">
          Run <code>make optimize</code>. It is not part of <code>make daily</code> on purpose —
          see the note below on what a sweep costs.
        </p>
      </div>
    );
  }

  const byMarket = new Map<string, OptimizeRow[]>();
  for (const row of data.rows) {
    const list = byMarket.get(row.market) ?? [];
    list.push(row);
    byMarket.set(row.market, list);
  }

  const profitable = data.rows.filter((r) => r.profitable).length;
  const tailHeavy = data.rows.filter((r) => {
    const share = tailShare(r);
    return share !== null && share > 0.5;
  }).length;

  return (
    <div className="optimize">
      <header className="optimize-head">
        <div>
          <h2>Parameter sweep</h2>
          <p className="muted">
            {data.start} → {data.end} · {data.rows.length} strategies · 9 settings each
            {data.dry_run ? ' · dry run, no trials spent' : ''}
          </p>
        </div>
        <div className="optimize-stat">
          <span className="stat-value">
            {profitable}/{data.rows.length}
          </span>
          <span className="stat-label">had any profitable setting</span>
        </div>
        <div className="optimize-stat">
          <span className="stat-value">{tailHeavy}</span>
          <span className="stat-label">whose best is mostly tail</span>
        </div>
        <div className="optimize-stat">
          <span className="stat-value">{data.trials_after ?? 0}</span>
          <span className="stat-label">
            trials spent, ever
            {data.dry_run ? '' : ` (+${(data.trials_after ?? 0) - (data.trials_before ?? 0)})`}
          </span>
        </div>
      </header>

      {[...byMarket.entries()].map(([market, rows]) => (
        <section key={market} className="optimize-market">
          <h3>
            {MARKET_LABEL[market] ?? market}
            <span className="muted"> · {rows[0]?.symbol}</span>
          </h3>
          <div className="table-scroll">
            <table className="optimize-table">
              <thead>
                <tr>
                  <th>Strategy</th>
                  <th className="num">Best</th>
                  <th className="num">Median</th>
                  <th className="num">Best ÷ median</th>
                  <th className="num">Fills</th>
                  <th>Reading</th>
                  <th>Paper</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.strategy_id} className={row.profitable ? '' : 'row-loss'}>
                    <td>
                      <span className="strategy-name">{row.title}</span>
                      <span className="muted strategy-id">{row.strategy_id}</span>
                    </td>
                    <td className={`num ${row.best_pnl < 0 ? 'neg' : 'pos'}`}>
                      {money(row.best_pnl)}
                    </td>
                    <td className={`num ${row.median_pnl < 0 ? 'neg' : 'pos'}`}>
                      {money(row.median_pnl)}
                    </td>
                    <td className="num">
                      {/* Blank, not "n/a" and not a number, when the median is
                          not positive: a ratio against a losing median would
                          read as reassuring precision about nothing. */}
                      {row.spread_ratio === null ? (
                        <span className="muted">—</span>
                      ) : (
                        `${row.spread_ratio.toFixed(1)}×`
                      )}
                    </td>
                    <td className="num">{row.fills}</td>
                    <td>
                      <Verdict row={row} />
                    </td>
                    <td>
                      {/* Link and PDF are separate affordances: the URL always
                          resolves, while the PDF exists only once fetch.sh has
                          run, and a download that 404s reads as broken
                          provenance rather than as a file nobody fetched. */}
                      {row.paper_url ? (
                        <span className="paperlinks">
                          <a href={row.paper_url} target="_blank" rel="noreferrer">
                            source ↗
                          </a>
                          {row.paper_pdf && (
                            <a href={row.paper_pdf} target="_blank" rel="noreferrer">
                              PDF ↓
                            </a>
                          )}
                        </span>
                      ) : (
                        <span className="muted" title="no published paper — practitioner rule">
                          —
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}

      <footer className="optimize-note">
        <h4>Why there is no “run sweep” button</h4>
        <p>
          Every setting a sweep evaluates is recorded as a trial, permanently. The
          deflated-Sharpe probability and the t-statistic in the mandate both take the{' '}
          <em>total</em> trial count as their denominator, so each sweep raises the bar for every
          result this platform has produced or ever will. A result now needs{' '}
          t &gt; {(data.required_t ?? 0).toFixed(2)} to clear it.
        </p>
        <p>
          That is a reason to sweep deliberately, not a reason never to sweep — so it runs from{' '}
          <code>make optimize</code>, by someone who meant to, and never from this page.
        </p>
        {data.skipped && data.skipped.length > 0 && (
          <p className="muted">
            Not swept, having no intraday bracket form: {data.skipped.join(', ')}
          </p>
        )}
      </footer>
    </div>
  );
}
