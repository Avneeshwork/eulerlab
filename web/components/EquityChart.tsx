'use client';

// A plain SVG line chart. No charting library: this draws one series and a
// drawdown shade, and pulling in a dependency to do that would be more code to
// audit than the thirty lines it replaces.

type Props = { days: string[]; equity: number[]; startingCash: number };

export function EquityChart({ days, equity, startingCash }: Props) {
  if (equity.length < 2) return <p className="muted">Not enough days to draw a curve.</p>;

  const W = 900;
  const H = 280;
  const padL = 62;
  const padR = 14;
  const padT = 14;
  const padB = 26;

  const lo = Math.min(...equity, startingCash);
  const hi = Math.max(...equity, startingCash);
  const span = hi - lo || 1;

  const x = (i: number) => padL + (i / (equity.length - 1)) * (W - padL - padR);
  const y = (v: number) => padT + (1 - (v - lo) / span) * (H - padT - padB);

  const line = equity.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const area = `${line} L${x(equity.length - 1).toFixed(1)},${y(lo)} L${padL},${y(lo)} Z`;

  // The starting-capital line matters more than gridlines: everything above it
  // is profit and everything below it is loss, which is the only threshold a
  // reader actually cares about.
  const baseY = y(startingCash);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => lo + f * span);
  const up = equity[equity.length - 1] >= startingCash;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Equity curve" style={{ display: 'block' }}>
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth="1" />
          <text x={padL - 8} y={y(t) + 3.5} textAnchor="end" fontSize="10" fill="var(--ink-3)" fontFamily="var(--mono)">
            {(t / 100000).toFixed(1)}L
          </text>
        </g>
      ))}

      <line x1={padL} x2={W - padR} y1={baseY} y2={baseY} stroke="var(--ink-3)" strokeWidth="1" strokeDasharray="3 3" />
      <text x={W - padR} y={baseY - 5} textAnchor="end" fontSize="10" fill="var(--ink-3)">
        starting capital
      </text>

      <path d={area} fill={up ? 'var(--good)' : 'var(--bad)'} opacity="0.09" />
      <path d={line} fill="none" stroke={up ? 'var(--good)' : 'var(--bad)'} strokeWidth="1.6" strokeLinejoin="round" />

      <text x={padL} y={H - 8} fontSize="10" fill="var(--ink-3)" fontFamily="var(--mono)">
        {days[0]}
      </text>
      <text x={W - padR} y={H - 8} textAnchor="end" fontSize="10" fill="var(--ink-3)" fontFamily="var(--mono)">
        {days[days.length - 1]}
      </text>
    </svg>
  );
}
