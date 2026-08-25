'use client';

/**
 * Every parameter setting a sweep tried for one strategy, with its exact result.
 *
 * This lives inside the Library row rather than on a tab of its own, because a
 * sweep result is a fact *about a strategy* — the same kind of fact as its
 * Sharpe or its universe — and putting it elsewhere asks the reader to hold two
 * places in their head to answer one question.
 *
 * Every setting is listed, not just the winner. A sweep reporting only its best
 * has found the maximum of N draws, which rises with N whether or not anything
 * real is there; the grid is what lets a reader see whether the best was a peak
 * or a plateau. The median row is marked for the same reason.
 */

import type { OptimizeRow } from '@/lib/api';

/**
 * The currency a market's P&L is denominated in.
 *
 * The rest of this app writes ₹ because every backtest in it was NSE. US bars
 * are the first that are not — Alpaca quotes dollars and the SEC and FINRA fees
 * are dollar amounts — so a US row carrying a rupee sign is wrong by the
 * exchange rate and reads as comparable to the India rows when it is not.
 */
const CURRENCY: Record<string, string> = { us: '$', crypto: '$', equity: '₹' };

function money(value: number, market: string): string {
  const symbol = CURRENCY[market] ?? '₹';
  const locale = symbol === '₹' ? 'en-IN' : 'en-US';
  const sign = value < 0 ? '−' : '';
  return `${sign}${symbol}${Math.abs(Math.round(value)).toLocaleString(locale)}`;
}

function labelParams(params: Record<string, number>): string {
  return Object.entries(params)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => `${key.replace(/_/g, ' ')} ${value}`)
    .join(' · ');
}

/** How much of the best sits above the median, as a share of the best. */
function tailShare(row: OptimizeRow): number | null {
  if (row.best_pnl <= 0) return null;
  return Math.max(0, row.beats_its_median_by) / row.best_pnl;
}

function reading(row: OptimizeRow): { label: string; tone: string; detail: string } {
  if (row.error) {
    return { label: 'did not complete', tone: 'error', detail: row.error };
  }
  if (!row.profitable) {
    return {
      label: 'loses on every setting',
      tone: 'loss',
      detail:
        'No parameter in the grid made money. That is a cleaner result than a ' +
        'marginal win: there is nothing here for a parameter choice to rescue.',
    };
  }
  const share = tailShare(row);
  if (share !== null && share > 0.5) {
    return {
      label: 'best is over half tail',
      tone: 'tail',
      detail:
        `More than half of the best result sits above the median setting, so most ` +
        `of what the winner earned is not shared by the rest of the grid. The ` +
        `maximum of ${row.candidates} draws rises with the count whether or not ` +
        `anything real is there.`,
    };
  }
  if (share !== null && share < 0.2) {
    return {
      label: 'flat across the grid',
      tone: 'flat',
      detail:
        'The best and the median are close, so the result barely depends on the ' +
        'parameter. That is the shape a real effect makes — and the shape a ' +
        'consistent bias makes too.',
    };
  }
  return {
    label: 'profitable',
    tone: 'ok',
    detail: 'Profitable at best, with a moderate gap to the typical setting.',
  };
}

export function SweepPanel({ row, running }: { row: OptimizeRow; running?: boolean }) {
  const settings = [...(row.settings ?? [])].sort((a, b) => b.net_pnl - a.net_pnl);
  const verdict = reading(row);
  const bestPnl = settings.length ? settings[0].net_pnl : row.best_pnl;
  // Index of the median in a descending list of an odd-length grid.
  const medianIndex = settings.length ? Math.floor((settings.length - 1) / 2) : -1;

  return (
    <div className="sweep">
      <div className="sweep-head">
        <h4>
          Parameter sweep <span className="sweep-sym">{row.symbol}</span>
        </h4>
        <span className={`verdict verdict-${verdict.tone}`}>{verdict.label}</span>
      </div>

      {running && (
        <p className="sweep-read dim">
          A sweep is running now. These are this strategy&rsquo;s finished settings — its
          own grid is complete — while other strategies are still being swept.
        </p>
      )}

      <p className="sweep-read">{verdict.detail}</p>

      {row.tested_on && (
        <p className="sweep-read dim">
          Swept on {row.symbol} because the paper tested {row.tested_on}.
        </p>
      )}

      {settings.length > 0 ? (
        <div className="sweep-scroll">
          <table className="sweep-table">
            <thead>
              <tr>
                <th>Setting</th>
                <th className="r">Net P&amp;L</th>
                <th className="r">Fills</th>
                <th className="r">Wins</th>
                <th className="r">Win rate</th>
                <th className="r">Sessions</th>
              </tr>
            </thead>
            <tbody>
              {settings.map((setting, index) => {
                const isBest = index === 0;
                const isMedian = index === medianIndex;
                return (
                  <tr
                    key={labelParams(setting.params)}
                    className={isBest ? 'is-best' : isMedian ? 'is-median' : ''}
                  >
                    <td>
                      {labelParams(setting.params)}
                      {isBest && <span className="mark">best</span>}
                      {isMedian && <span className="mark dim">median</span>}
                    </td>
                    <td className={`r ${setting.net_pnl < 0 ? 'neg' : 'pos'}`}>
                      {money(setting.net_pnl, row.market)}
                    </td>
                    <td className="r">{setting.fills}</td>
                    <td className="r">{setting.wins}</td>
                    <td className="r">
                      {setting.fills > 0
                        ? `${Math.round((setting.wins / setting.fills) * 100)}%`
                        : '—'}
                    </td>
                    <td className="r">{setting.sessions}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="sweep-read dim">
          {row.error
            ? row.error
            : 'This sweep was recorded before per-setting results were kept. Re-run ' +
              'make optimize to fill the grid in.'}
        </p>
      )}

      <div className="sweep-facts">
        <div>
          <span>Best</span>
          <b className={bestPnl < 0 ? 'neg' : 'pos'}>{money(row.best_pnl, row.market)}</b>
        </div>
        <div>
          <span>Median</span>
          <b className={row.median_pnl < 0 ? 'neg' : 'pos'}>
            {money(row.median_pnl, row.market)}
          </b>
        </div>
        <div>
          <span>Best ÷ median</span>
          {/* Withheld, not zeroed, when the median is not positive: a ratio
              against a losing median is arithmetic without meaning, delivered
              in the vocabulary of a healthy result. */}
          <b>{row.spread_ratio === null ? '—' : `${row.spread_ratio.toFixed(2)}×`}</b>
        </div>
        <div>
          <span>Settings tried</span>
          <b>{row.candidates}</b>
        </div>
      </div>

      {row.paper_url && (
        <p className="sweep-read">
          <a href={row.paper_url} target="_blank" rel="noreferrer">
            Read the paper ↗
          </a>
          {row.paper_pdf && (
            <>
              {' · '}
              <a href={row.paper_pdf} target="_blank" rel="noreferrer">
                PDF ↓
              </a>
            </>
          )}
        </p>
      )}
    </div>
  );
}
