'use client';

/**
 * The equity path and its drawdown, drawn large enough to read.
 *
 * The report carried a 280x64 sparkline, which is a shape rather than a chart:
 * you can see that a line went up, and not when, by how much, or how far it
 * fell on the way. A backtest report whose only picture is a thumbnail asks
 * the reader to take the metrics on faith.
 *
 * Two panels, sharing one x-axis:
 *
 * **Equity**, with the starting balance drawn as a baseline. Without that line
 * a chart of a losing run and a winning run have the same silhouette — the
 * y-axis auto-scales and both look like a line wandering across a box.
 *
 * **Drawdown**, underneath, as depth below the running peak. It is the shape
 * the equity curve hides: a strategy that ends up 3% can spend two months 5%
 * down, and only the second panel says so.
 *
 * Rendered as inline SVG with no chart library — the page has no bundler budget
 * for one and the marks here are two paths and an axis.
 */

const WIDTH = 720;
const EQUITY_HEIGHT = 200;
const DRAWDOWN_HEIGHT = 84;
const PAD_LEFT = 4;

type Props = {
  values: number[];
  days: string[];
  startingCash: number;
  money: (value: number) => string;
};

function drawdownSeries(values: number[]): number[] {
  let peak = values[0] ?? 0;
  return values.map((value) => {
    peak = Math.max(peak, value);
    return peak > 0 ? (value - peak) / peak : 0;
  });
}

export function EquityChart({ values, days, startingCash, money }: Props) {
  if (values.length < 2) {
    return <p className="tfine">Not enough points to draw a curve.</p>;
  }

  const drops = drawdownSeries(values);
  const worst = Math.min(...drops, 0);
  const low = Math.min(...values, startingCash);
  const high = Math.max(...values, startingCash);
  // A flat run would divide by zero and, worse, draw a line at an arbitrary
  // height; a floor keeps it on the baseline where it belongs.
  const span = high - low || 1;

  const x = (i: number) => PAD_LEFT + (i / (values.length - 1)) * (WIDTH - PAD_LEFT * 2);
  const y = (v: number) => EQUITY_HEIGHT - ((v - low) / span) * EQUITY_HEIGHT;
  const dy = (v: number) => (worst < 0 ? (v / worst) * DRAWDOWN_HEIGHT : 0);

  const line = values.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const area = `${line} L${x(values.length - 1).toFixed(1)},${EQUITY_HEIGHT} L${x(0).toFixed(1)},${EQUITY_HEIGHT} Z`;
  const under = drops
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${dy(v).toFixed(1)}`)
    .join(' ');
  const underArea = `${under} L${x(drops.length - 1).toFixed(1)},0 L${x(0).toFixed(1)},0 Z`;

  const up = values[values.length - 1] >= startingCash;
  const base = y(startingCash);
  const worstIndex = drops.indexOf(Math.min(...drops));

  return (
    <figure className="eqchart">
      <svg
        viewBox={`0 0 ${WIDTH} ${EQUITY_HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Equity from ${money(startingCash)} to ${money(values[values.length - 1])}`}
      >
        <path d={area} className={up ? 'eq-fill up' : 'eq-fill down'} />
        {/* The starting balance. Without it the reader cannot tell a run that
            doubled from one that halved — the y-axis scales to fit either. */}
        <line x1="0" y1={base} x2={WIDTH} y2={base} className="eq-base" />
        <path d={line} className={up ? 'eq-line up' : 'eq-line down'} />
      </svg>

      <svg
        viewBox={`0 0 ${WIDTH} ${DRAWDOWN_HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Worst drawdown ${(worst * 100).toFixed(1)} percent`}
      >
        <path d={underArea} className="dd-fill" />
        <path d={under} className="dd-line" />
      </svg>

      <figcaption>
        <span>
          {days[0] ?? '—'} → {days[days.length - 1] ?? '—'}
        </span>
        <span className={up ? 'pos' : 'neg'}>
          {money(values[values.length - 1])} from {money(startingCash)}
        </span>
        <span className="neg">
          worst drawdown {(worst * 100).toFixed(1)}%
          {days[worstIndex] ? ` on ${days[worstIndex]}` : ''}
        </span>
      </figcaption>
    </figure>
  );
}
