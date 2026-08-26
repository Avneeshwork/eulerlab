'use client';

/**
 * The full backtest report for the strategy as it actually runs.
 *
 * This is the main result. It is one run on one parameter set — the one a
 * recorded sweep selected — rather than a summary of nine, because nine
 * summaries answer "which setting won" and a reader of the library is asking
 * "what does this strategy do".
 *
 * The sweep grid is still available below it, and belongs below it: it is the
 * evidence for the parameter choice, not the result of the strategy.
 */

import type { AdoptedResult } from '@/lib/api';

const CURRENCY: Record<string, string> = { us: '$', crypto: '$', equity: '₹' };

function money(value: number, market: string): string {
  const symbol = CURRENCY[market] ?? '₹';
  const locale = symbol === '₹' ? 'en-IN' : 'en-US';
  const sign = value < 0 ? '−' : '';
  return `${sign}${symbol}${Math.abs(Math.round(value)).toLocaleString(locale)}`;
}

/** The equity path, drawn large enough to read rather than as a sparkline. */
function Curve({ curve, market }: { curve: number[]; market: string }) {
  if (curve.length < 2) return null;
  const width = 560;
  const height = 120;
  const low = Math.min(0, ...curve);
  const high = Math.max(0, ...curve);
  const span = high - low || 1;
  const x = (i: number) => (i / (curve.length - 1)) * width;
  const y = (v: number) => height - ((v - low) / span) * height;
  const path = curve.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const zero = y(0);
  const ends = curve[curve.length - 1] >= 0;

  return (
    <svg className="adopted-curve" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Cumulative profit and loss by session">
      {/* Zero drawn explicitly. Without it a chart of a losing strategy and one
          of a winning strategy have the same shape. */}
      <line x1="0" y1={zero} x2={width} y2={zero} className="adopted-zero" />
      <path d={path} className={ends ? 'adopted-line pos' : 'adopted-line neg'} />
    </svg>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="adopted-stat">
      <span>{label}</span>
      <b className={tone}>{value}</b>
    </div>
  );
}

export function AdoptedReport({
  result,
  bar,
  heading = 'Backtest',
  note,
}: {
  result: AdoptedResult;
  bar: number;
  heading?: string;
  note?: string;
}) {
  const clears = result.sharpe !== null && result.sharpe >= bar;
  const params = Object.entries(result.params)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`)
    .join(' · ');
  const rejected = Object.entries(result.rejections).sort((a, b) => b[1] - a[1]);
  const exits = Object.entries(result.exits).sort((a, b) => b[1] - a[1]);

  return (
    <div className="adopted">
      <div className="adopted-head">
        <h4>{heading}</h4>
        <span className="adopted-where">
          {result.symbol} · {result.start} → {result.end}
        </span>
        <span className={`verdict ${clears ? 'verdict-ok' : 'verdict-loss'}`}>
          {result.sharpe === null
            ? 'not measurable'
            : clears
              ? `Sharpe ${result.sharpe.toFixed(2)} — clears the ${bar.toFixed(2)} bar`
              : `Sharpe ${result.sharpe.toFixed(2)} — under the ${bar.toFixed(2)} bar`}
        </span>
      </div>

      {note && <p className="adopted-params">{note}</p>}

      <p className="adopted-params">
        Running {result.adopted ? params : 'the paper’s published parameters'}
        {result.adopted && ' — the best of the settings a recorded sweep tried.'}
      </p>

      <Curve curve={result.curve} market={result.market} />

      <div className="adopted-stats">
        <Stat
          label="Net P&L"
          value={money(result.net_pnl, result.market)}
          tone={result.net_pnl < 0 ? 'neg' : 'pos'}
        />
        <Stat label="Gross" value={money(result.gross_pnl, result.market)} />
        {/* Costs beside gross, always. The crypto result here is 88% fees, and
            a net figure alone hides which of the two facts it is. */}
        <Stat label="Costs" value={money(-Math.abs(result.costs), result.market)} tone="neg" />
        <Stat label="Sharpe" value={result.sharpe === null ? '—' : result.sharpe.toFixed(2)} tone={clears ? 'pos' : undefined} />
        <Stat
          label="Max drawdown"
          value={money(result.max_drawdown, result.market)}
          tone={result.max_drawdown < 0 ? 'neg' : undefined}
        />
        <Stat label="Fills" value={String(result.fills)} />
        <Stat
          label="Win rate"
          value={result.fills ? `${Math.round((result.wins / result.fills) * 100)}%` : '—'}
        />
        <Stat label="Sessions" value={String(result.sessions)} />
        <Stat label="Best session" value={money(result.best_session, result.market)} />
        <Stat label="Worst session" value={money(result.worst_session, result.market)} tone="neg" />
      </div>

      {(exits.length > 0 || rejected.length > 0) && (
        <div className="adopted-breakdown">
          {exits.length > 0 && (
            <div>
              <h5>How trades ended</h5>
              <ul>
                {exits.map(([reason, count]) => (
                  <li key={reason}>
                    <span>{reason}</span>
                    <b>{count}</b>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {rejected.length > 0 && (
            <div>
              <h5>Why it declined</h5>
              {/* A signal that refuses 12,000 times and fires 23 is a different
                  object from one that fires constantly, and the two can report
                  the same P&L. */}
              <ul>
                {rejected.map(([reason, count]) => (
                  <li key={reason}>
                    <span>{reason}</span>
                    <b>{count.toLocaleString()}</b>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <p className="adopted-fine">
        {result.sessions} sessions and {result.fills} fills. Annualised at √252 on the session
        count, which treats sessions as independent — reasonable for a strategy flat by every
        close, and still an assumption rather than a measurement.
      </p>
    </div>
  );
}
