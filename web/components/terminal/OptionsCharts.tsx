/**
 * The derived views over one chain: smile, max pain, gamma, positioning.
 *
 * Drawn as inline SVG rather than with a charting library. Each of these is a
 * line or a bar over a few hundred points, and the whole thing is less code
 * than configuring a library would be — with no runtime to load and nothing
 * that can fail to render because a CDN was slow.
 *
 * Every chart states what it is measuring in its own caption, because the
 * difference between these tools is almost entirely in what the number means
 * rather than in how it is drawn: max pain is a description of open interest
 * and not a forecast, and the gamma sign rests on an assumption nobody can
 * verify from end-of-day data.
 */

'use client';

type Point = { x: number; y: number };

function path(points: Point[], width: number, height: number, pad = 6): string {
  if (points.length < 2) return '';
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  return points
    .map((p, i) => {
      const x = pad + ((p.x - minX) / spanX) * (width - pad * 2);
      const y = height - pad - ((p.y - minY) / spanY) * (height - pad * 2);
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
}

const W = 720;
const H = 200;

export function SmileChart({
  smile,
  atm,
}: {
  smile: { strike: number; call_iv: number | null; put_iv: number | null }[];
  atm: number | null;
}) {
  const calls = smile.filter((p) => p.call_iv !== null).map((p) => ({ x: p.strike, y: p.call_iv! }));
  const puts = smile.filter((p) => p.put_iv !== null).map((p) => ({ x: p.strike, y: p.put_iv! }));
  if (calls.length < 2 && puts.length < 2) return <p className="tfine">Not enough priced strikes.</p>;

  const all = [...calls, ...puts];
  const lo = Math.min(...all.map((p) => p.y));
  const hi = Math.max(...all.map((p) => p.y));

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', minWidth: 520, height: H }}>
        <path d={path(calls, W, H)} fill="none" stroke="var(--neon)" strokeWidth="1.5" />
        <path d={path(puts, W, H)} fill="none" stroke="var(--caveat)" strokeWidth="1.5" />
      </svg>
      <p className="tfine">
        <b style={{ color: 'var(--neon)' }}>calls</b> and{' '}
        <b style={{ color: 'var(--caveat)' }}>puts</b> plotted separately, not blended. Under
        parity they should agree at the same strike, so the gap between the two curves is a
        data-quality reading — averaging them throws away the one diagnostic the pair gives
        you. Vol ranges {(lo * 100).toFixed(1)}% to {(hi * 100).toFixed(1)}%
        {atm !== null && `, at-the-money strike ${atm.toLocaleString('en-IN')}`}.
      </p>
    </div>
  );
}

export function MaxPainChart({
  pain,
  forward,
}: {
  pain: { strike: number; payout: number; curve: [number, number][] } | null;
  forward: number | null;
}) {
  if (!pain) return <p className="tfine">No open interest to measure.</p>;
  const points = pain.curve.map(([x, y]) => ({ x, y }));
  const payouts = pain.curve.map(([, y]) => y);
  const flatness = Math.min(...payouts) / (Math.max(...payouts) || 1);

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', minWidth: 520, height: H }}>
        <path d={path(points, W, H)} fill="none" stroke="var(--ink-3)" strokeWidth="1.5" />
      </svg>
      <p className="tfine">
        Minimum at <b>{pain.strike.toLocaleString('en-IN')}</b>
        {forward !== null && ` against a forward of ${forward.toLocaleString('en-IN', {
          maximumFractionDigits: 0,
        })}`}
        . This is a description of where open interest sits, <b>not a forecast</b>: reading it
        as where price will settle requires believing writers can move spot and that today&rsquo;s
        open interest is their final position, and neither is established here. The whole curve
        is drawn because the minimum alone hides how sharp it is — the trough here is{' '}
        {(flatness * 100).toFixed(0)}% of the peak, and a flat curve makes the single number
        close to meaningless.
      </p>
    </div>
  );
}

export function GammaChart({
  gamma,
  atm,
}: {
  gamma: { total: number; flip: number | null; convention: string; points: { strike: number; exposure: number }[] };
  atm: number | null;
}) {
  const points = gamma.points;
  if (points.length < 2) return <p className="tfine">Not enough priced strikes.</p>;

  const xs = points.map((p) => p.strike);
  const minX = Math.min(...xs);
  const spanX = Math.max(...xs) - minX || 1;
  const peak = Math.max(...points.map((p) => Math.abs(p.exposure))) || 1;
  const mid = H / 2;

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', minWidth: 520, height: H }}>
        <line x1={0} y1={mid} x2={W} y2={mid} stroke="var(--rule-2)" strokeWidth="1" />
        {points.map((p) => {
          const x = 6 + ((p.strike - minX) / spanX) * (W - 12);
          const h = (Math.abs(p.exposure) / peak) * (mid - 10);
          const up = p.exposure >= 0;
          return (
            <rect
              key={p.strike}
              x={x - 1.5}
              y={up ? mid - h : mid}
              width={3}
              height={Math.max(h, 0.5)}
              fill={up ? 'var(--neon)' : 'var(--caveat)'}
            />
          );
        })}
      </svg>
      <p className="tfine">
        Gamma times open interest per strike. <b>The sign rests on an assumption</b>: the usual
        construction takes dealers to be long calls and short puts, and whether that held on any
        given day is a claim about who is on the other side of the open interest — which the
        bhavcopy does not say. It is named rather than folded in silently, because a profile
        whose sign is wrong marks support and resistance at exactly the wrong strikes.
        {gamma.flip !== null && (
          <>
            {' '}
            Cumulative exposure crosses zero near{' '}
            <b>{gamma.flip.toLocaleString('en-IN')}</b>
            {atm !== null && `, with the money at ${atm.toLocaleString('en-IN')}`}.
          </>
        )}
      </p>
    </div>
  );
}

export function PositioningPanel({
  ratio,
}: {
  ratio: {
    by_open_interest: number | null;
    by_volume: number | null;
    call_open_interest: number;
    put_open_interest: number;
    call_volume: number;
    put_volume: number;
  };
}) {
  const show = (value: number | null) => (value === null ? '—' : value.toFixed(3));
  const big = (value: number) => value.toLocaleString('en-IN', { maximumFractionDigits: 0 });

  return (
    <>
      <div className="period">
        <div>
          <span>PCR by open interest</span>
          <b>{show(ratio.by_open_interest)}</b>
          <i className="tfine">
            {big(ratio.put_open_interest)} puts / {big(ratio.call_open_interest)} calls
          </i>
        </div>
        <div>
          <span>PCR by volume</span>
          <b>{show(ratio.by_volume)}</b>
          <i className="tfine">
            {big(ratio.put_volume)} puts / {big(ratio.call_volume)} calls
          </i>
        </div>
      </div>
      <p className="tfine" style={{ marginTop: 12 }}>
        Kept apart rather than averaged. Open interest is positions held and volume is positions
        traded today; quoting one as &ldquo;the PCR&rdquo; is how a quiet session with heavy
        existing positioning reads as a busy one. A ratio with no calls to divide by is shown as
        &mdash;, because a division nobody can perform is not a very large number.
      </p>
    </>
  );
}
