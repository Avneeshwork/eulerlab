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

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { MacroReading } from '@/lib/api';
import { MacroLine, type MacroPoint } from '@/components/terminal/MacroLine';

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
          stroke={inverted ? 'var(--down)' : 'var(--neon-deep)'}
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

/** "30 Oct, 23:35 IST" from a UTC ISO stamp. */
const sweepTime = (iso: string) => {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso.slice(0, 16);
  return (
    when.toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }) + ' IST'
  );
};

const GROUPS: [string, string][] = [
  ['yields', 'Sovereign yields'],
  ['energy', 'Energy'],
  ['metals', 'Metals'],
  ['risk', 'Risk'],
];

const RANGES: [string, number][] = [
  ['1M', 31],
  ['3M', 92],
  ['6M', 183],
];

const level = (v: number) =>
  v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: v < 20 ? 3 : 2 });

/** Points within the last `days` of the series' own last reading. */
function within(points: MacroPoint[], days: number): MacroPoint[] {
  if (!points.length) return points;
  const end = Date.parse(points[points.length - 1].at);
  return points.filter((p) => end - Date.parse(p.at) <= days * 86_400_000);
}

/** Change over the window, in percent of the first reading (or points for a yield). */
function change(points: MacroPoint[], unit: string): string {
  if (points.length < 2) return '—';
  const first = points[0].value;
  const last = points[points.length - 1].value;
  if (unit === '%') {
    const bp = (last - first) * 100;
    return `${bp >= 0 ? '+' : '−'}${Math.abs(bp).toFixed(0)} bp`;
  }
  if (!first) return '—';
  const pct = ((last - first) / first) * 100;
  return `${pct >= 0 ? '+' : '−'}${Math.abs(pct).toFixed(1)}%`;
}

export function MacroBand({
  rows,
  spread,
  stale,
  sweptAt,
}: {
  rows: MacroReading[];
  spread?: number | null;
  stale?: boolean;
  /** When the sweep behind these numbers ran (UTC ISO). */
  sweptAt?: string | null;
}) {
  const [view, setView] = useState<'charts' | 'numbers'>('charts');
  const [history, setHistory] = useState<Record<string, MacroPoint[]>>({});
  const [focus, setFocus] = useState('');
  const [range, setRange] = useState(92);
  useEffect(() => {
    let live = true;
    api
      .macroHistory(180)
      .then((found) => live && setHistory(found.series ?? {}))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  if (!rows.length) return null;
  const chosen = rows.find((r) => r.name === focus) ?? rows.find((r) => r.name === 'US 10Y') ?? rows[0];
  const big = within(history[chosen.name] ?? [], range);
  return (
    <section>
      <h3 className="report-h">
        Macro
        <span className="tfine hstat">
          {stale ? 'last good sweep' : 'sweep'}
          {sweptAt ? ` of ${sweepTime(sweptAt)}` : ''}
        </span>
      </h3>

      <div className="mkttoggle" style={{ marginBottom: 12 }}>
        {(['charts', 'numbers'] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            className={view === mode ? 'on' : ''}
            onClick={() => setView(mode)}
          >
            {mode === 'charts' ? 'Charts' : 'Numbers'}
          </button>
        ))}
      </div>

      {view === 'numbers' ? (
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
      ) : (
        <>
          <div className="ownchart mfocus">
            <div className="mfocus-head">
              <div>
                <b>{chosen.name}</b>
                <span className="mfocus-last">
                  {level(chosen.last)}
                  {chosen.unit && <i className="munit">{chosen.unit}</i>}
                </span>
                <span className={chosen.change_pct >= 0 ? 'mchg up' : 'mchg dn'}>
                  {pctRaw(chosen.change_pct)} today
                </span>
                <span className="tfine">
                  {change(big, chosen.unit)} over {RANGES.find(([, d]) => d === range)?.[0]}
                </span>
              </div>
              <div className="mkttoggle">
                {RANGES.map(([label, days]) => (
                  <button key={label} type="button" className={range === days ? 'on' : ''} onClick={() => setRange(days)}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <MacroLine key={`${chosen.name}-${range}`} points={big} height={340} />
          </div>

          {GROUPS.map(([group, label]) => {
            const kept = rows.filter((r) => r.group === group);
            if (!kept.length) return null;
            return (
              <div key={group} className="mcards-group">
                <div className="mgrouphead">{label}</div>
                <div className="mcards">
                  {kept.map((r) => {
                    const pts = within(history[r.name] ?? [], range);
                    return (
                      <button
                        key={r.symbol}
                        type="button"
                        className={`mcard${r.name === chosen.name ? ' on' : ''}`}
                        onClick={() => setFocus(r.name)}
                      >
                        <span className="mcard-top">
                          <b>{r.name}</b>
                          <span className={r.change_pct >= 0 ? 'mchg up' : 'mchg dn'}>{pctRaw(r.change_pct)}</span>
                        </span>
                        <span className="mcard-last">
                          {level(r.last)}
                          {r.unit && <i className="munit">{r.unit}</i>}
                          <span className="tfine"> {change(pts, r.unit)}</span>
                        </span>
                        <MacroLine points={pts} height={56} compact />
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </>
      )}
    </section>
  );
}
