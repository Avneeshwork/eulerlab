'use client';

/**
 * The shared parts every terminal screen is built from (ADR-084).
 *
 * The rules they carry: numbers and pictures on the page, explanation only
 * behind `Info`; an arrow beside every red or green; nothing wider than a
 * phone. A screen that needs a part not here adds it here rather than
 * drawing its own, so the screens stay one language.
 */

import './ui.css';

import { Info } from './Info';

export { Info };

// --- numbers ---------------------------------------------------------------------

/** A fraction as a signed percent. A move that rounds to nothing has no sign:
 *  "−0.0%" read as a fall. */
export function signed(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return '—';
  const size = Math.abs(fraction * 100).toFixed(digits);
  if (Number(size) === 0) return `${size}%`;
  return `${fraction >= 0 ? '+' : '−'}${size}%`;
}

/** Colour class and arrow for a change; within `flat` either side is flat. */
export function direction(value: number | null | undefined, flat = 0.0005) {
  if (value === null || value === undefined || Number.isNaN(value)) return { cls: '', arrow: '' };
  if (value > flat) return { cls: 'up', arrow: '↑' };
  if (value < -flat) return { cls: 'down', arrow: '↓' };
  return { cls: '', arrow: '→' };
}

/** A signed change with its arrow. `percent` false shows the value as given. */
export function Move({
  value,
  digits = 1,
  text,
}: {
  value: number | null | undefined;
  digits?: number;
  /** What to print instead of the percent, keeping the arrow and colour. */
  text?: string;
}) {
  const d = direction(value);
  return (
    <span className={`ui-move ${d.cls}`}>
      {d.arrow && <i aria-hidden="true">{d.arrow}</i>}
      {text ?? signed(value, digits)}
    </span>
  );
}

export const inr = (value: number, digits = 0) =>
  `₹${value.toLocaleString('en-IN', { maximumFractionDigits: digits })}`;

// --- layout ----------------------------------------------------------------------

/** A section heading: title, a short data label, and its explanation behind Info. */
export function Heading({
  title,
  sub,
  info,
  children,
  as: Tag = 'h3',
}: {
  title: React.ReactNode;
  sub?: React.ReactNode;
  info?: React.ReactNode;
  children?: React.ReactNode;
  as?: 'h2' | 'h3';
}) {
  return (
    <Tag className="report-h ui-heading">
      {title}
      {sub !== undefined && sub !== null && sub !== '' && <span className="ui-sub">{sub}</span>}
      {info && <Info>{info}</Info>}
      {children && <span className="ui-heading-end">{children}</span>}
    </Tag>
  );
}

/** One figure: a small label, the value, an optional second line. */
export function Stat({
  label,
  value,
  sub,
  tone,
  info,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: 'up' | 'down' | '';
  info?: React.ReactNode;
}) {
  return (
    <div className="ui-stat">
      <span className="ui-stat-label">
        {label}
        {info && <Info>{info}</Info>}
      </span>
      <b className={`ui-stat-value ${tone ?? ''}`}>{value}</b>
      {sub !== undefined && sub !== null && sub !== '' && <span className="ui-stat-sub">{sub}</span>}
    </div>
  );
}

/** A row of Stats that wraps on a phone. */
export function Stats({ children }: { children: React.ReactNode }) {
  return <div className="ui-stats">{children}</div>;
}

/** A small pill, e.g. a verdict or a tag. */
export function Chip({ children, tone = '' }: { children: React.ReactNode; tone?: 'up' | 'down' | 'warn' | '' }) {
  return <span className={`ui-chip ${tone}`}>{children}</span>;
}

/** A segmented switch between a few options. */
export function Seg<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: [T, string][];
  onChange: (next: T) => void;
  label: string;
}) {
  return (
    <div className="ui-seg" role="tablist" aria-label={label}>
      {options.map(([key, text]) => (
        <button
          key={key}
          type="button"
          role="tab"
          aria-selected={value === key}
          className={value === key ? 'on' : ''}
          onClick={() => onChange(key)}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

/** "Not available", said once, with the reason behind Info. */
export function Empty({ reason }: { reason?: string }) {
  return (
    <div className="ui-empty">
      —{reason && <Info>{reason}</Info>}
    </div>
  );
}

// --- small charts --------------------------------------------------------------------

/** A line in a stretched box with strokes that do not scale; `average` dashed
 *  on the same scale. Tone colours the line and its fill. */
export function Sparkline({
  values,
  average,
  tone = 'neutral',
  height = 44,
}: {
  values: number[];
  average?: number[];
  tone?: 'up' | 'down' | 'neutral';
  height?: number;
}) {
  if (values.length < 2) return null;
  const all = [...values, ...(average ?? [])];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = hi - lo || 1;
  const x = (i: number, n: number) => (i / (n - 1)) * 100;
  const y = (v: number) => 4 + (1 - (v - lo) / span) * 92;
  const line = (series: number[]) =>
    series.map((v, i) => `${i ? 'L' : 'M'}${x(i, series.length).toFixed(2)},${y(v).toFixed(2)}`).join('');
  return (
    <svg
      className={`ui-spark ${tone}`}
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      style={{ height }}
      aria-hidden="true"
    >
      <path className="ui-spark-area" d={`${line(values)}L100,100L0,100Z`} />
      {average && average.length > 1 && <path className="ui-spark-avg" d={line(average)} />}
      <path className="ui-spark-line" d={line(values)} />
    </svg>
  );
}

/** A horizontal bar for one value against a scale; signed values grow from the
 *  middle. For bars inside table cells. */
export function Bar({
  value,
  max,
  signed: centred = false,
  tone,
}: {
  value: number;
  max: number;
  signed?: boolean;
  tone?: 'up' | 'down' | 'accent';
}) {
  const share = Math.min(1, Math.abs(value) / (max || 1));
  const colour = tone ?? (value >= 0 ? 'up' : 'down');
  return (
    <span className={`ui-bar ${centred ? 'centred' : ''}`} aria-hidden="true">
      <i
        className={colour}
        style={
          centred
            ? value >= 0
              ? { left: '50%', width: `${share * 50}%` }
              : { right: '50%', width: `${share * 50}%` }
            : { left: 0, width: `${share * 100}%` }
        }
      />
    </span>
  );
}
