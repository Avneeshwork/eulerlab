/**
 * The equity curve of a real run, drawn small.
 *
 * The curve comes from `engine.equity` — the actual path the backtest took,
 * downsampled server-side. There is deliberately no fallback shape: a strategy
 * that has never run draws nothing, because a flat line would be a picture of a
 * run that did not happen, and a generated squiggle would be worse.
 */

export function Spark({
  curve,
  clears,
  width = 132,
  height = 34,
}: {
  curve: number[] | undefined;
  clears: boolean;
  width?: number;
  height?: number;
}) {
  if (!curve || curve.length < 2) {
    return <span className="sparkempty" title="Never run in this workspace." />;
  }

  const low = Math.min(...curve);
  const high = Math.max(...curve);
  const range = high - low || 1;
  const step = width / (curve.length - 1);
  const y = (value: number) => height - 2 - ((value - low) / range) * (height - 4);

  const line = curve.map((value, index) => `${index * step},${y(value)}`).join(' ');
  const area = `0,${height} ${line} ${width},${height}`;
  const start = curve[0];
  const end = curve[curve.length - 1];
  // The baseline is the starting capital, so the fill reads as "above or below
  // where it began" rather than as an arbitrary shape in a box.
  const base = y(start);

  return (
    <svg
      className={`spark${clears ? ' clear' : ''}`}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`Equity curve, ${end >= start ? 'ending above' : 'ending below'} its start`}
    >
      <polygon points={area} className="spark-fill" />
      <line x1="0" y1={base} x2={width} y2={base} className="spark-base" />
      <polyline points={line} className="spark-line" fill="none" />
      <circle cx={width} cy={y(end)} r="2.5" className="spark-end" />
    </svg>
  );
}
