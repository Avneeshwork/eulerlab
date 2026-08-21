'use client';

/**
 * The five primitives that carry nine tenths of every screen.
 *
 * Built before any surface so that each screen does not invent its own version
 * of a Sharpe bar or an evidence badge and drift. Published spec: "The Honest
 * Strategy Terminal", section 09 step 1.
 *
 * Two of these encode a research decision rather than a visual one, and those
 * are the ones worth reading:
 *
 * - `EvidenceBadge` renders a rung the backend DERIVED from the trial ledger.
 *   It has no `set` counterpart and no override, because a strategy that could
 *   be told it was validated would eventually be told so by a bug.
 *
 * - `SharpeVsBar` draws every Sharpe against the noise bar at a fixed scale, so
 *   the bar tick lands at the same x on every row. Sorting a library by raw
 *   Sharpe *is* the selection procedure the overfitting tests measure, so the
 *   component makes "clears the bar" the visual signal and magnitude secondary.
 */

import type { Stage } from '@/lib/api';

// --- 1. evidence badge -----------------------------------------------------

const RUNG_LABEL: Record<string, string> = {
  registered: 'screened',
  backtested: 'backtested',
  forward_testing: 'forward',
  live: 'live',
  retired: 'retired',
};

const RUNG_CLASS: Record<string, string> = {
  registered: 'ev--screened',
  backtested: 'ev--backtested',
  forward_testing: 'ev--validated',
  live: 'ev--live',
  retired: 'ev--retired',
};

const RUNG_TITLE: Record<string, string> = {
  registered:
    'It ran, and nothing more. Screening in the workbench spends no trial — which means this is real search the noise bar does not know you performed.',
  backtested: 'Evaluated on the event-driven engine and recorded in the trial ledger.',
  forward_testing: 'Survived the validation battery: CPCV, deflated Sharpe, PBO and stress.',
  live: 'Real capital, real fills.',
  retired: 'Withdrawn. Kept visible because a strategy that failed is evidence too.',
};

export function EvidenceBadge({ stage }: { stage: Stage }) {
  return (
    <span className={`ev ${RUNG_CLASS[stage] ?? ''}`} title={RUNG_TITLE[stage] ?? ''}>
      {RUNG_LABEL[stage] ?? stage}
    </span>
  );
}

// --- 2. Sharpe against the noise bar ---------------------------------------

export function SharpeVsBar({
  sharpe,
  bar,
  note,
}: {
  // null means never measured. It is NOT zero — zero is a measurement meaning
  // "no edge", null means nobody looked — and the two must never render alike.
  sharpe: number | null;
  bar: number;
  note?: string;
}) {
  // Fixed scale so the bar tick lands at the same x on every row in the table.
  // A per-row scale would make each row internally sensible and the column
  // meaningless.
  const scale = Math.max(bar * 1.6, 0.01);
  const barLeft = Math.min((bar / scale) * 100, 100);
  const clears = sharpe !== null && sharpe >= bar;
  const fill = sharpe === null ? 0 : Math.max(Math.min((sharpe / scale) * 100, 100), 0);

  return (
    <div className="sb">
      <span
        className={`sb-v${clears ? ' sb-v--pass' : ''}${sharpe === null ? ' sb-v--none' : ''}`}
        title={note}
      >
        {sharpe === null ? (note ?? 'not measured') : sharpe.toFixed(2)}
      </span>
      <span className="sb-track" aria-hidden="true">
        <span className="sb-line" />
        {sharpe !== null && (
          <span className={`sb-fill${clears ? ' sb-fill--pass' : ''}`} style={{ width: `${fill}%` }} />
        )}
        <span className="sb-bar" style={{ left: `${barLeft}%` }} />
      </span>
    </div>
  );
}

// --- 3. sparkline ----------------------------------------------------------

export function Sparkline({
  values,
  width = 64,
  height = 20,
}: {
  values: number[];
  width?: number;
  height?: number;
}) {
  if (values.length < 2) {
    return <span className="t-mono" style={{ fontSize: 10, color: 'var(--ink-3)' }}>—</span>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = width / (values.length - 1);
  const points = values
    .map((v, i) => `${(i * step).toFixed(1)},${(height - ((v - min) / span) * height).toFixed(1)}`)
    .join(' ');

  // Coloured by direction, which is an outcome and therefore allowed to use the
  // semantic palette. A flat series gets the neutral ink.
  const last = values[values.length - 1];
  const first = values[0];
  const stroke =
    last > first ? 'var(--up)' : last < first ? 'var(--down)' : 'var(--ink-3)';

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline fill="none" stroke={stroke} strokeWidth="1.3" points={points} />
    </svg>
  );
}

// --- 4. stat grid ----------------------------------------------------------

export type Stat = {
  label: string;
  value: string;
  tone?: 'up' | 'down' | 'warn';
  help?: string;
};

export function StatGrid({ stats }: { stats: Stat[] }) {
  return (
    <div className="stats">
      {stats.map((s) => (
        <div className="stat" key={s.label} title={s.help}>
          <div className="stat-k">{s.label}</div>
          <div className={`stat-v${s.tone ? ` stat-v--${s.tone}` : ''}`}>{s.value}</div>
        </div>
      ))}
    </div>
  );
}

// --- 5. tag ----------------------------------------------------------------

export function Tag({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <span className="tag" title={title}>
      {children}
    </span>
  );
}
