'use client';

/**
 * The India dashboard's context: numbers and pictures, with every word of
 * explanation behind an info button (research 120 and 121, ADR-080 to 082).
 *
 * The operator asked for no running text on the page and for charts chosen to
 * be read at a glance, so each figure here has the shape that answers its
 * question fastest: a dial for "how much of the range", a line for "which way",
 * a split bar for "how many of 100", a range bar for "cheap or dear against its
 * own past", a quadrant for "who is leading and turning". None of it has passed
 * the gate: it is context, not a signal.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { BreadthName, Horizon, MarketContext, PulseCard, ValuationCell } from '@/lib/api';
import { Info } from './Info';
import './marketcontext.css';

const signed = (fraction: number | null | undefined, digits = 1) => {
  if (fraction === null || fraction === undefined) return '—';
  const size = Math.abs(fraction * 100).toFixed(digits);
  // A move that rounds to nothing has no sign: "−0.0%" read as a fall.
  if (Number(size) === 0) return `${size}%`;
  return `${fraction >= 0 ? '+' : '−'}${size}%`;
};

const points = (fraction: number | null | undefined, digits = 1) =>
  fraction === null || fraction === undefined
    ? '—'
    : `${fraction >= 0 ? '+' : '−'}${Math.abs(fraction * 100).toFixed(digits)} pts`;

/** Colour class and arrow together: colour is never the only signal. */
const move = (value: number | null | undefined, flat = 0.0005) =>
  value === null || value === undefined
    ? { cls: '', arrow: '' }
    : value > flat
      ? { cls: 'pos', arrow: '↑' }
      : value < -flat
        ? { cls: 'neg', arrow: '↓' }
        : { cls: '', arrow: '→' };

function Move({ value, digits = 1 }: { value: number | null | undefined; digits?: number }) {
  const m = move(value);
  return (
    <span className={`mc-move ${m.cls}`}>
      {m.arrow && <i aria-hidden="true">{m.arrow}</i>}
      {signed(value, digits)}
    </span>
  );
}

const fmt = (value: number, digits = 2) =>
  value.toLocaleString('en-IN', { maximumFractionDigits: digits });

const lakh = (contracts: number) => {
  const sign = contracts >= 0 ? '+' : '−';
  const size = Math.abs(contracts);
  return size >= 1e5 ? `${sign}${(size / 1e5).toFixed(2)}L` : `${sign}${size.toLocaleString('en-IN')}`;
};

/** Fetches once, then again every 5 s while a section is still filling (the
 *  panel loading after a restart, or participant history arriving from the
 *  bucket), at most 24 times. */
export function useMarketContext(): { data: MarketContext | null; error: string } {
  const [data, setData] = useState<MarketContext | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    let tries = 0;
    let timer = 0;
    const read = () => {
      api
        .marketContext()
        .then((next) => {
          if (!alive) return;
          setData(next);
          setError('');
          const pending =
            !next.breadth.available ||
            ('filling' in next.positioning && Boolean(next.positioning.filling));
          if (pending && tries++ < 24) timer = window.setTimeout(read, 5000);
        })
        .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    };
    read();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, []);
  return { data, error };
}

function Heading({ title, info, sub }: { title: string; info?: React.ReactNode; sub?: string }) {
  return (
    <h3 className="report-h mc-h">
      {title}
      {sub && <span className="tfine mc-sub">{sub}</span>}
      {info && <Info>{info}</Info>}
    </h3>
  );
}

function Missing({ title, reason }: { title: string; reason: string }) {
  return (
    <section>
      <Heading title={title} info={`Not available: ${reason}.`} />
      <div className="tpanel mc-missing">—</div>
    </section>
  );
}

// --- small charts ----------------------------------------------------------------

/** A line in a stretched box, strokes that do not scale. `average` is drawn
 *  dashed on the same scale. */
function Sparkline({
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
  const area = `${line(values)}L100,100L0,100Z`;
  return (
    <svg className={`mc-spark ${tone}`} viewBox="0 0 100 100" preserveAspectRatio="none" style={{ height }} aria-hidden="true">
      <path className="mc-spark-area" d={area} />
      {average && average.length > 1 && <path className="mc-spark-avg" d={line(average)} />}
      <path className="mc-spark-line" d={line(values)} />
    </svg>
  );
}

/** A half-circle dial, 0-100, three coloured zones and a needle. `colours`
 *  names the zone roles low to high: 'bad', 'mid', 'good'. */
function Dial({
  value,
  zones,
  colours,
  labels,
}: {
  value: number;
  zones: [number, number];
  colours: [string, string, string];
  labels: [string, string, string];
}) {
  const r = 40;
  const cx = 50;
  const cy = 50;
  const at = (v: number) => {
    const angle = Math.PI * (1 - Math.min(100, Math.max(0, v)) / 100);
    return [cx + r * Math.cos(angle), cy - r * Math.sin(angle)];
  };
  const arc = (from: number, to: number) => {
    const [x1, y1] = at(from);
    const [x2, y2] = at(to);
    return `M${x1.toFixed(2)},${y1.toFixed(2)}A${r},${r} 0 0 1 ${x2.toFixed(2)},${y2.toFixed(2)}`;
  };
  const [nx, ny] = at(value);
  const bounds: [number, number][] = [
    [0, zones[0]],
    [zones[0], zones[1]],
    [zones[1], 100],
  ];
  return (
    <figure className="mc-dial">
      <svg viewBox="0 0 100 58" role="img" aria-label={`${value.toFixed(0)} of 100`}>
        {bounds.map(([from, to], k) => (
          <path key={k} className={`mc-dial-zone ${colours[k]}`} d={arc(from, to)} />
        ))}
        <line className="mc-dial-needle" x1={cx} y1={cy} x2={nx} y2={ny} />
        <circle className="mc-dial-hub" cx={cx} cy={cy} r={3} />
      </svg>
      <figcaption>
        {labels.map((label) => (
          <span key={label}>{label}</span>
        ))}
      </figcaption>
    </figure>
  );
}

/** Of 100: the long share as a filled bar, a tick where it usually sits. */
function SplitBar({ share, usual }: { share: number; usual?: number | null }) {
  const long = Math.max(0, Math.min(100, share * 100));
  return (
    <div className="mc-split" aria-label={`${long.toFixed(0)} of 100 long`}>
      <i className="long" style={{ width: `${long}%` }}>
        {long >= 9 ? long.toFixed(0) : ''}
      </i>
      <i className="short" style={{ width: `${100 - long}%` }}>
        {100 - long >= 9 ? (100 - long).toFixed(0) : ''}
      </i>
      {usual !== null && usual !== undefined && (
        <b className="mc-split-usual" style={{ left: `${usual * 100}%` }} title={`usual ${(usual * 100).toFixed(0)}`} />
      )}
    </div>
  );
}

/** Lowest to highest since a date, a tick at the median, a dot for today. */
function RangeBar({ cell, label }: { cell: ValuationCell; label: string }) {
  if (!cell || cell.low === null || cell.high === null || cell.high <= cell.low) {
    return (
      <div className="mc-range-row">
        <span className="mc-range-label">{label}</span>
        <span className="mc-quiet">—</span>
      </div>
    );
  }
  const where = (v: number) => ((v - (cell.low ?? 0)) / ((cell.high ?? 1) - (cell.low ?? 0))) * 100;
  return (
    <div className="mc-range-row" title={`${label} since ${cell.since}: low ${cell.low}, median ${cell.median}, high ${cell.high}`}>
      <span className="mc-range-label">{label}</span>
      <span className="mc-range">
        <span className="mc-range-track" />
        {cell.median !== null && <i className="mc-range-median" style={{ left: `${where(cell.median)}%` }} />}
        <b className="mc-range-dot" style={{ left: `${where(cell.value)}%` }} />
      </span>
      <span className="mc-range-value">{cell.value.toFixed(2)}</span>
      <span className="mc-range-ends mc-quiet">
        {cell.low.toFixed(1)}–{cell.high.toFixed(1)}
      </span>
    </div>
  );
}

const HORIZONS: [Horizon, string][] = [
  ['1d', '1D'],
  ['1w', '1W'],
  ['1m', '1M'],
  ['3m', '3M'],
  ['1y', '1Y'],
];

/** Five coloured blocks, one per horizon; the shade deepens with the size. */
function HeatStrip({ change, neutral = false }: { change: Record<Horizon, number | null>; neutral?: boolean }) {
  return (
    <div className="mc-heat">
      {HORIZONS.map(([h, label]) => {
        const v = change[h];
        const level = v === null ? 0 : Math.min(3, Math.ceil(Math.abs(v) / 0.03));
        const side = neutral || v === null || Math.abs(v) < 0.0005 ? 'flat' : v > 0 ? 'pos' : 'neg';
        return (
          <span key={h} className={`mc-heat-cell ${side} l${level}`} title={`${label} ${signed(v)}`}>
            <em>{label}</em>
            <b>{signed(v)}</b>
          </span>
        );
      })}
    </div>
  );
}

// --- Overview ------------------------------------------------------------------

const ARROW: Record<PulseCard['direction'], string> = { up: '↑', down: '↓', flat: '→' };

function Gauge({ card }: { card: PulseCard }) {
  if (card.key === 'trend' && card.spark) {
    return (
      <>
        <Sparkline
          values={card.spark}
          average={card.spark_average}
          tone={card.tone === 'good' ? 'up' : card.tone === 'bad' ? 'down' : 'neutral'}
          height={52}
        />
        <div className="mc-card-facts">
          <span>
            3M <Move value={card.value} />
          </span>
          <span>
            200D <b>{card.average ? fmt(card.average, 0) : '—'}</b>
          </span>
        </div>
      </>
    );
  }
  if ((card.key === 'participation' || card.key === 'fear') && card.zones) {
    const fear = card.key === 'fear';
    return (
      <>
        <Dial
          value={card.value}
          zones={card.zones}
          colours={fear ? ['good', 'mid', 'bad'] : ['bad', 'mid', 'good']}
          labels={fear ? ['Calm', 'Normal', 'Elevated'] : ['Narrow', 'Mixed', 'Broad']}
        />
        <div className="mc-card-facts">
          {fear ? (
            <>
              <span>
                VIX <b>{card.level?.toFixed(1)}</b>
              </span>
              <span>
                Rank <b>{card.value.toFixed(0)}</b>
              </span>
            </>
          ) : (
            <>
              <span>
                Above 50D <b>{card.value.toFixed(0)}%</b>
              </span>
              <span>
                Highs <b className="pos">{card.new_highs}</b> · Lows <b className="neg">{card.new_lows}</b>
              </span>
            </>
          )}
        </div>
      </>
    );
  }
  if (card.key === 'money') {
    return (
      <>
        <SplitBar share={card.value} usual={card.usual} />
        {card.spark && card.spark.length > 1 && <Sparkline values={card.spark} height={36} />}
        <div className="mc-card-facts">
          <span>
            Long <b>{(card.value * 100).toFixed(0)}</b>/100
          </span>
          <span>
            Rank <b>{card.percentile?.toFixed(0)}</b>
          </span>
        </div>
      </>
    );
  }
  return null;
}

/** Four verdicts: a word, an arrow, a colour and a gauge. */
export function PulseCards({ ctx }: { ctx: MarketContext }) {
  const p = ctx.pulse;
  if (!p.available) return <Missing title="Market pulse" reason={p.reason} />;
  return (
    <section>
      <Heading title="Market pulse" info={p.note} />
      <div className="mc-pulse">
        {p.cards.map((card) => (
          <article key={card.key} className={`mc-card ${card.tone}`}>
            <div className="mc-card-head">
              <span className="mc-card-title">{card.title}</span>
              <Info align="right">{card.info}</Info>
            </div>
            <b className="mc-card-word">
              <i aria-hidden="true">{ARROW[card.direction]}</i> {card.word}
            </b>
            <Gauge card={card} />
          </article>
        ))}
      </div>
    </section>
  );
}

const PLAIN_NAME: Record<string, string> = {
  'Nifty 50': 'Nifty 50',
  'Nifty Midcap 150': 'Midcap 150',
  'Nifty Smallcap 250': 'Smallcap 250',
  'Nifty 500': 'Nifty 500',
  'Nifty Bank': 'Bank Nifty',
  'India VIX': 'India VIX',
  'Nifty 10 yr Benchmark G-Sec': '10Y G-Sec',
};

/** One tile per index: level, today, a year's line, five horizons. */
export function IndexContext({ ctx }: { ctx: MarketContext }) {
  const strip = ctx.strip;
  const valuation = ctx.valuation;
  if (!strip.available) return <Missing title="Indices" reason={strip.reason} />;
  return (
    <>
      <section>
        <Heading
          title="Indices"
          sub={strip.indices[0]?.as_of}
          info={
            <>
              Closing levels. The line is the past year. The five blocks are the change over a day,
              a week, a month, three months and a year; deeper shades are bigger moves. Nifty 50 is
              large companies, Midcap 150 mid-sized, Smallcap 250 small. {strip.vix?.note} VIX is
              drawn without green or red: a rise means traders pay more for protection.{' '}
              {strip.gsec_note}
            </>
          }
        />
        <div className="mc-tiles">
          {strip.indices.map((row) => {
            const neutral = row.name === 'India VIX';
            const day = row.change['1d'];
            return (
              <article key={row.name} className="mc-tile">
                <div className="mc-tile-head">
                  <span>{PLAIN_NAME[row.name] ?? row.name}</span>
                  {neutral ? <span className="mc-quiet">{signed(day)}</span> : <Move value={day} />}
                </div>
                <b className="mc-tile-close">{fmt(row.close)}</b>
                <Sparkline
                  values={row.spark}
                  tone={neutral ? 'neutral' : (row.change['1y'] ?? 0) >= 0 ? 'up' : 'down'}
                />
                <HeatStrip change={row.change} neutral={neutral} />
              </article>
            );
          })}
        </div>
      </section>
      {valuation.available && (
        <section>
          <Heading
            title="Valuation"
            sub="against its own history"
            info={
              <>
                Each bar runs from the lowest to the highest reading since the date shown; the tick
                is the median and the dot is today. For PE and PB, a dot to the left is cheaper than
                usual; for dividend yield, a dot to the right is. {valuation.note}
              </>
            }
          />
          <div className="mc-tiles wide">
            {valuation.indices.map((row) => (
              <article key={row.name} className="mc-tile">
                <div className="mc-tile-head">
                  <span>{PLAIN_NAME[row.name] ?? row.name}</span>

                </div>
                <RangeBar label="PE" cell={row.pe} />
                <RangeBar label="PB" cell={row.pb} />
                <RangeBar label="Yield" cell={row.dy} />
              </article>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

// --- Sectors -------------------------------------------------------------------

type Span = '1w' | '1m' | '3m';
const SPANS: [Span, string][] = [
  ['1w', '1W'],
  ['1m', '1M'],
  ['3m', '3M'],
];

const PHASE: Record<string, string> = {
  leading: 'Leading',
  weakening: 'Weakening',
  improving: 'Improving',
  lagging: 'Lagging',
};

function Seg<T extends string>({
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
    <div className="mc-seg" role="tablist" aria-label={label}>
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

type SectorRow = Extract<MarketContext['sectors'], { available: true }>['sectors'][number];

function SectorBars({ rows, span }: { rows: SectorRow[]; span: Span }) {
  const sorted = [...rows].sort((a, b) => (b.relative[span] ?? -9) - (a.relative[span] ?? -9));
  const widest = Math.max(0.01, ...sorted.map((r) => Math.abs(r.relative[span] ?? 0)));
  return (
    <ul className="mc-bars">
      {sorted.map((row) => {
        const value = row.relative[span];
        const width = value === null ? 0 : (Math.abs(value) / widest) * 50;
        return (
          <li key={row.name}>
            <span className="mc-bar-name">{row.name.replace(/^Nifty /, '')}</span>
            <span className="mc-bar-track" aria-hidden="true">
              <i
                className={value !== null && value >= 0 ? 'pos' : 'neg'}
                style={
                  value !== null && value >= 0
                    ? { left: '50%', width: `${width}%` }
                    : { right: '50%', width: `${width}%` }
                }
              />
            </span>
            <span className="mc-bar-value">
              <Move value={value} />
            </span>
            <span className="mc-bar-phase">
              {row.phase && (
                <span className={`mc-phase ${row.phase}`}>
                  {row.rising ? '↗' : '↘'} {PHASE[row.phase]}
                </span>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** Each sector as a dot: across, 3-month strength against Nifty; up, whether
 *  that strength has grown over the last week. Four quadrants, four phases. */
function SectorQuadrant({ rows }: { rows: SectorRow[] }) {
  const placed = rows.filter((r) => r.relative['3m'] !== null && r.momentum !== null);
  const xs = Math.max(0.02, ...placed.map((r) => Math.abs(r.relative['3m'] ?? 0)));
  const ys = Math.max(0.005, ...placed.map((r) => Math.abs(r.momentum ?? 0)));
  const x = (v: number) => 50 + (v / xs) * 44;
  const y = (v: number) => 50 - (v / ys) * 42;
  // A label that would sit on a neighbour's goes to the dot's other side; if
  // both sides are taken it steps down. Widths are estimated from the name's
  // length (about 0.55% of the chart per character), so the test is approximate.
  const name = (row: SectorRow) => row.name.replace(/^Nifty /, '').replace(' Index', '');
  const spots = placed
    .map((row) => ({ row, left: x(row.relative['3m'] ?? 0), top: y(row.momentum ?? 0) }))
    .sort((a, b) => a.left - b.left);
  const boxes: [number, number, number][] = spots.map((s) => [s.left - 0.4, s.left + 0.4, s.top]);
  const labelled = spots.map((spot) => {
    const width = name(spot.row).length * 0.55 + 1.2;
    const span = (side: 'r' | 'l'): [number, number] =>
      side === 'r' ? [spot.left + 0.8, spot.left + 0.8 + width] : [spot.left - 0.8 - width, spot.left - 0.8];
    const free = (side: 'r' | 'l', top: number) => {
      const [a, b] = span(side);
      return a > 0 && b < 100 && !boxes.some(([l, r, t]) => Math.abs(t - top) < 3.6 && a < r && b > l);
    };
    let side: 'r' | 'l' = 'r';
    let top = spot.top;
    if (!free('r', top)) side = free('l', top) ? 'l' : 'r';
    while (!free(side, top) && top < 94) top += 3.6;
    const [a, b] = span(side);
    boxes.push([a, b, top]);
    return { ...spot, side, shift: top - spot.top };
  });
  return (
    <div className="mc-quad">
      <span className="mc-quad-label tl">Improving</span>
      <span className="mc-quad-label tr">Leading</span>
      <span className="mc-quad-label bl">Lagging</span>
      <span className="mc-quad-label br">Weakening</span>
      <span className="mc-quad-axis x" />
      <span className="mc-quad-axis y" />
      {labelled.map(({ row, left, top, side, shift }) => (
        <span
          key={row.name}
          className={`mc-quad-dot ${row.phase ?? ''} ${side === 'l' ? 'flip' : ''}`}
          style={{ left: `${left}%`, top: `${top}%` }}
          title={`${row.name}: 3M vs Nifty ${signed(row.relative['3m'])}, 1M change over the week ${points(row.momentum)}`}
        >
          <i />
          {shift > 0 && <b className="mc-quad-lead" style={{ height: `${shift * 3.8}px` }} />}
          {/* 3.8 px per % of the 380 px chart: the label alone moves down. */}
          <em style={shift ? { top: `${shift * 3.8}px` } : undefined}>
            {row.name.replace(/^Nifty /, '').replace(' Index', '')}
          </em>
        </span>
      ))}
      <span className="mc-quad-caption x">3M vs Nifty →</span>
      <span className="mc-quad-caption y">Gaining ↑</span>
    </div>
  );
}

/** Sector indices against Nifty 50: ranked bars, or the rotation quadrant. */
export function SectorContext({ ctx }: { ctx: MarketContext }) {
  const [shape, setShape] = useState<'bars' | 'quadrant'>('bars');
  const [span, setSpan] = useState<Span>('1m');
  const s = ctx.sectors;
  if (!s.available) return <Missing title="Sectors vs Nifty" reason={s.reason} />;
  return (
    <section>
      <Heading
        title="Sectors vs Nifty"
        info={
          <>
            Bars: how much better (right) or worse (left) than Nifty 50 each sector did over the
            period chosen. Rotation: each dot is a sector; to the right it is ahead of Nifty over 3
            months, higher up its 1-month lead grew over the last week. Top right Leading, bottom
            right Weakening, bottom left Lagging, top left Improving. Our own stated rule, not a
            Relative Rotation Graph, whose smoothing is proprietary. {s.note}
          </>
        }
      />
      <div className="tpanel">
        <div className="mc-controls">
          <Seg
            label="Chart"
            value={shape}
            options={[
              ['bars', 'Bars'],
              ['quadrant', 'Rotation'],
            ]}
            onChange={setShape}
          />
          {shape === 'bars' && <Seg label="Period" value={span} options={SPANS} onChange={setSpan} />}
        </div>
        {shape === 'bars' ? <SectorBars rows={s.sectors} span={span} /> : <SectorQuadrant rows={s.sectors} />}
      </div>
    </section>
  );
}

// --- Big money -----------------------------------------------------------------

const WHO: Record<string, string> = {
  FII: 'FII',
  DII: 'DII',
  Pro: 'Pro',
  Client: 'Client',
};

/** A 0-100 line chart with guides, drawn at a fixed pixel height with labels
 *  in HTML so the text stays the same size at any width. */
function ShareChart({
  days,
  lines,
  guides = [25, 50, 75],
  max = 100,
  height = 140,
}: {
  days: string[];
  lines: { label: string; values: (number | null)[]; role: string }[];
  guides?: number[];
  max?: number;
  height?: number;
}) {
  const n = Math.max(days.length - 1, 1);
  const x = (i: number) => (i / n) * 1000;
  const y = (v: number) => (1 - v / max) * 100;
  const path = (values: (number | null)[]) => {
    let d = '';
    let open = false;
    values.forEach((v, i) => {
      if (v === null || Number.isNaN(v)) {
        open = false;
        return;
      }
      d += `${open ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(2)}`;
      open = true;
    });
    return d;
  };
  const ticks = [0, Math.floor(n / 2), n].filter((i, k, all) => all.indexOf(i) === k);
  return (
    <figure className="mc-chart">
      <div className="mc-plot" style={{ height }}>
        <svg
          viewBox="0 0 1000 100"
          preserveAspectRatio="none"
          role="img"
          aria-label={lines.map((l) => l.label).join(', ')}
        >
          {guides.map((g) => (
            <line key={g} className="mc-guide" x1={0} x2={1000} y1={y(g)} y2={y(g)} />
          ))}
          {lines.map((line) => (
            <path key={line.label} className={`mc-line ${line.role}`} d={path(line.values)} />
          ))}
        </svg>
        {guides.map((g) => (
          <span key={g} className="mc-axis mc-y" style={{ top: `${y(g)}%` }}>
            {g}
          </span>
        ))}
      </div>
      <div className="mc-x">
        {ticks.map((i) => (
          <span key={i} className="mc-axis">
            {days[i]}
          </span>
        ))}
      </div>
      <figcaption>
        {lines.map((line) => (
          <span key={line.label} className="mc-key">
            <i className={line.role} />
            {line.label}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

/** Nifty, the range options price by expiry, and max pain, on one line. */
function MoveLine({
  forward,
  low,
  high,
  pain,
}: {
  forward: number;
  low: number;
  high: number;
  pain: number | null;
}) {
  const lo = Math.min(low, pain ?? low) - (high - low) * 0.25;
  const hi = Math.max(high, pain ?? high) + (high - low) * 0.25;
  const at = (v: number) => ((v - lo) / (hi - lo)) * 100;
  return (
    <div className="mc-moveline">
      <span className="mc-moveline-track" />
      <span className="mc-moveline-band" style={{ left: `${at(low)}%`, width: `${at(high) - at(low)}%` }} />
      <span className="mc-moveline-mark spot" style={{ left: `${at(forward)}%` }}>
        <em>Nifty {fmt(forward, 0)}</em>
      </span>
      {pain !== null && (
        <span className="mc-moveline-mark pain" style={{ left: `${at(pain)}%` }}>
          <em>Max pain {fmt(pain, 0)}</em>
        </span>
      )}
      <span className="mc-moveline-end" style={{ left: `${at(low)}%` }}>
        {fmt(low, 0)}
      </span>
      <span className="mc-moveline-end" style={{ left: `${at(high)}%` }}>
        {fmt(high, 0)}
      </span>
    </div>
  );
}

/** Who holds index futures, and what options price. */
export function PositioningContext({ ctx }: { ctx: MarketContext }) {
  const p = ctx.positioning;
  const o = ctx.options;
  return (
    <>
      <section>
        <Heading
          title="Index futures: long of 100"
          sub={p.available ? `${p.as_of}${p.filling ? ' · loading history' : ''}` : undefined}
          info={
            p.available ? (
              <>
                Of every 100 Nifty and Bank Nifty futures contracts each group holds, how many are
                bets on a rise (green) against a fall (red). The white tick is the group&apos;s median
                over the past year. FII: funds, banks and insurers based outside India. DII: Indian
                mutual funds, banks and insurers; their shorts are often hedges. Pro: brokers trading
                their own money. Client: everyone else, retail and companies alike. 1D and 5D are
                changes in points out of 100; Rank places today among the group&apos;s own past year
                (0 lowest, 100 highest). Index options, net contracts:{' '}
                {p.participants
                  .map((r) => `${r.participant} calls ${lakh(r.index_calls_net)}, puts ${lakh(r.index_puts_net)}`)
                  .join('; ')}
                . {p.note}
              </>
            ) : (
              `Not available: ${p.reason}.`
            )
          }
        />
        {p.available && (
          <div className="tpanel">
            <ul className="mc-who">
              {p.participants.map((row) => (
                <li key={row.participant}>
                  <b className="mc-who-name">{WHO[row.participant] ?? row.participant}</b>
                  <SplitBar share={row.index_futures_long_share ?? 0} usual={row.usual} />
                  <span className="mc-who-facts">
                    <span>
                      1D <b className={move(row.change_1d).cls}>{points(row.change_1d)}</b>
                    </span>
                    <span>
                      5D <b className={move(row.change_5d).cls}>{points(row.change_5d)}</b>
                    </span>
                    <span>
                      Rank <b>{row.percentile?.toFixed(0) ?? '—'}</b>
                    </span>
                  </span>
                </li>
              ))}
            </ul>
            <ShareChart
              days={p.series.days}
              lines={[
                { label: 'FII', values: p.series.FII.map((v) => (v === null ? null : v * 100)), role: 'mc-a' },
                { label: 'Client', values: p.series.Client.map((v) => (v === null ? null : v * 100)), role: 'mc-b' },
                { label: 'Pro', values: p.series.Pro.map((v) => (v === null ? null : v * 100)), role: 'mc-c' },
              ]}
            />
          </div>
        )}
      </section>

      <section>
        <Heading
          title="Nifty options"
          sub={o.available ? `${o.expiry}${o.days_to_expiry !== null ? ` · ${o.days_to_expiry}D` : ''}` : undefined}
          info={
            o.available ? (
              <>
                The shaded band is the range options price by expiry: Nifty plus or minus the
                at-the-money straddle (call plus put). Put-call ratio: open put contracts per open
                call contract. Implied volatility: the yearly swing option prices assume. Max pain:
                the strike where option buyers as a group would lose most at expiry. The small
                figure under PCR and IV is its value on {o.since}. Sensibull, which popularised PCR and max pain, says
                they &ldquo;do not have high predictive power&rdquo;: read them as where the open
                interest sits, not where the index goes. {o.note}
              </>
            ) : (
              `Not available: ${o.reason}.`
            )
          }
        />
        {o.available && (
          <div className="tpanel">
            {o.expected_move && o.spot_forward && (
              <>
                <div className="mc-bigline">
                  ±{(o.expected_move.share * 100).toFixed(1)}%
                  <span className="mc-quiet"> ±{fmt(o.expected_move.points, 0)} pts</span>
                </div>
                <MoveLine
                  forward={o.spot_forward}
                  low={o.expected_move.low}
                  high={o.expected_move.high}
                  pain={o.max_pain}
                />
              </>
            )}
            <div className="tfacts mc-facts">
              <div className="tfact">
                <span>PCR</span>
                <b>{o.pcr_oi?.toFixed(2) ?? '—'}</b>
                <i>{o.pcr_oi_before !== null ? `5D ago ${o.pcr_oi_before.toFixed(2)}` : ''}</i>
              </div>
              <div className="tfact">
                <span>IV</span>
                <b>{o.atm_iv !== null ? `${(o.atm_iv * 100).toFixed(1)}%` : '—'}</b>
                <i>{o.atm_iv_before !== null ? `5D ago ${(o.atm_iv_before * 100).toFixed(1)}%` : ''}</i>
              </div>
              <div className="tfact">
                <span>Max pain</span>
                <b>{o.max_pain !== null ? fmt(o.max_pain, 0) : '—'}</b>
              </div>
            </div>
          </div>
        )}
      </section>
    </>
  );
}

// --- Stocks to watch ------------------------------------------------------------

function NameList({
  title,
  info,
  rows,
  found,
}: {
  title: string;
  info: string;
  rows: BreadthName[];
  found: number;
}) {
  const widest = Math.max(0.01, ...rows.map((r) => Math.abs(r.change_1d ?? 0)));
  return (
    <div className="tpanel">
      <h3 className="mc-h">
        {title}
        <span className="tfine mc-sub">
          {rows.length}/{found}
        </span>
        <Info>{info}</Info>
      </h3>
      {rows.length ? (
        <table className="ttable mc-num">
          <tbody>
            {rows.map((row) => (
              <tr key={row.symbol}>
                <td>{row.symbol}</td>
                <td>{row.close.toLocaleString('en-IN')}</td>
                <td className="mc-cellbar">
                  <span
                    className={`mc-fill ${(row.change_1d ?? 0) >= 0 ? 'up' : 'down'}`}
                    style={{ width: `${(Math.abs(row.change_1d ?? 0) / widest) * 100}%` }}
                  />
                  <Move value={row.change_1d} />
                </td>
                <td className="mc-quiet">₹{row.turnover_cr}Cr</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="mc-missing">—</div>
      )}
    </div>
  );
}

/** New highs and lows and delivery spikes, beside the movers on the same tab. */
export function WatchContext({ ctx }: { ctx: MarketContext }) {
  const b = ctx.breadth;
  const d = ctx.delivery;
  const liquid = 'Listed when the stock trades ₹10 crore a day or more (20-day median). The figure after the title is listed / all.';
  const top = d.available ? Math.max(1.5, ...d.stocks.map((r) => r.ratio)) : 1;
  return (
    <>
      {b.available ? (
        <section>
          <Heading title="52-week highs and lows" sub={b.as_of} />
          <div className="tgrid mc-two">
            <NameList
              title="New highs"
              info={`Closed above every close of the past year. ${liquid}`}
              rows={b.new_high_names}
              found={b.latest.new_highs}
            />
            <NameList
              title="New lows"
              info={`Closed below every close of the past year. ${liquid}`}
              rows={b.new_low_names}
              found={b.latest.new_lows}
            />
          </div>
        </section>
      ) : (
        <Missing title="52-week highs and lows" reason={b.reason} />
      )}
      {d.available ? (
        <section>
          <Heading
            title="Delivery spikes"
            sub={`${d.found} · ${d.as_of}`}
            info={
              <>
                Delivery % is the share of traded shares settled by delivery, bought to hold rather
                than squared off the same day. The bar is today against the stock&apos;s own average
                over the previous {d.sessions} sessions; listed at 1.5× or more, among names trading
                ₹10 crore a day. It does not say which side was buying.
              </>
            }
          />
          <div className="tpanel">
            {d.stocks.length ? (
              <div className="mc-scroll">
                <table className="ttable mc-num">
                  <thead>
                    <tr>
                      <th>Stock</th>
                      <th>Times usual</th>
                      <th>Delivered</th>
                      <th>Usual</th>
                      <th>1D</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.stocks.map((row) => (
                      <tr key={row.symbol}>
                        <td>{row.symbol}</td>
                        <td className="mc-cellbar">
                          <span className="mc-fill acc" style={{ width: `${(row.ratio / top) * 100}%` }} />
                          <b>{row.ratio.toFixed(1)}×</b>
                        </td>
                        <td>{row.delivery_pct.toFixed(0)}%</td>
                        <td className="mc-quiet">{row.usual_pct.toFixed(0)}%</td>
                        <td>
                          <Move value={row.change_1d} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="mc-missing">—</div>
            )}
          </div>
        </section>
      ) : (
        <Missing title="Delivery spikes" reason={d.reason} />
      )}
    </>
  );
}
