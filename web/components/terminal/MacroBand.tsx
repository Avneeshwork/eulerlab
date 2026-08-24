'use client';

/**
 * The macro band — yields, energy, metals and risk.
 *
 * Sourced from TradingView's public scanner rather than FMP, because FMP's
 * free plan answers 402 for WTI, natural gas and the dollar index, and serves
 * no sovereign yields at all. The scanner returns all seventeen series in one
 * request with no key, which is also why this can refresh often.
 *
 * The yields are shown as a curve, not a list, because the shape is the point:
 * a reader is looking for whether the front end sits above the long end, and
 * four numbers in a row do not answer that at a glance.
 */

import type { MacroReading } from '@/lib/api';

const pctRaw = (value: number, digits = 2) =>
  `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(digits)}%`;

function Tile({ reading }: { reading: MacroReading }) {
  const up = reading.change_pct >= 0;
  return (
    <div className="mtile" title={`${reading.name} · ${reading.symbol}`}>
      <span className="mname">{reading.name}</span>
      <span className="mlast">
        {reading.last.toLocaleString('en-US', {
          minimumFractionDigits: 2,
          maximumFractionDigits: reading.last < 20 ? 3 : 2,
        })}
        {reading.unit && <i className="munit">{reading.unit}</i>}
      </span>
      <span className={up ? 'mchg up' : 'mchg dn'}>{pctRaw(reading.change_pct)}</span>
    </div>
  );
}

/** The US curve drawn as a curve. Inversion is a shape, not a number. */
function Curve({ rows, spread }: { rows: MacroReading[]; spread?: number | null }) {
  const us = rows.filter((r) => r.name.startsWith('US ') && r.unit === '%');
  if (us.length < 2) return null;

  const rates = us.map((r) => r.last);
  const low = Math.min(...rates);
  const high = Math.max(...rates);
  const span = high - low || 1;
  const width = 100;
  const height = 46;

  const points = us.map((r, index) => {
    const x = (index / (us.length - 1)) * width;
    const y = height - ((r.last - low) / span) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const inverted = spread !== null && spread !== undefined && spread < 0;

  return (
    <div className="curvebox">
      <div className="curvehead">
        <span className="mname">US CURVE</span>
        {spread !== null && spread !== undefined && (
          <b className={inverted ? 'dn' : 'up'}>
            2s10s {spread >= 0 ? '+' : '−'}
            {Math.abs(spread).toFixed(2)}
          </b>
        )}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="curvesvg">
        <polyline
          points={points.join(' ')}
          fill="none"
          stroke={inverted ? '#c9524a' : 'var(--neon-deep)'}
          strokeWidth="1.6"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="curveaxis">
        {us.map((r) => (
          <span key={r.symbol}>{r.name.replace('US ', '')}</span>
        ))}
      </div>
      <div className="tfine">
        {inverted
          ? 'Inverted — the two-year yields more than the ten.'
          : 'Upward sloping — no inversion at the 2s10s.'}
      </div>
    </div>
  );
}

const GROUPS: [string, string][] = [
  ['yields', 'Sovereign yields'],
  ['energy', 'Energy'],
  ['metals', 'Metals'],
  ['risk', 'Risk'],
];

export function MacroBand({
  rows,
  spread,
  stale,
}: {
  rows: MacroReading[];
  spread?: number | null;
  stale?: boolean;
}) {
  if (!rows.length) return null;
  return (
    <section>
      <h3 className="report-h">
        Macro
        <span
          className="tfine hstat"
          title="TradingView's public scanner — one request, no key. FMP's free plan answers 402 for WTI, natural gas and the dollar index, and serves no sovereign yields at all."
        >
          {stale ? 'from the last sweep' : 'live'} · 17 series
          <abbr className="whyq">?</abbr>
        </span>
      </h3>

      <div className="macrogrid">
        <Curve rows={rows} spread={spread} />
        {GROUPS.map(([group, label]) => {
          const kept = rows.filter((r) => r.group === group);
          if (!kept.length) return null;
          return (
            <div className="mgroup" key={group}>
              <div className="mgrouphead">{label}</div>
              <div className="mtiles">
                {kept.map((r) => (
                  <Tile key={r.symbol} reading={r} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
