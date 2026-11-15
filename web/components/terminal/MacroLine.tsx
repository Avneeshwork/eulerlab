'use client';

/**
 * One macro series drawn from **this platform's own readings**.
 *
 * The Charts page drew these with TradingView mini-chart widgets. They refuse
 * most of these symbols, so the ETF proxies chosen instead stood in for the
 * real series (a bond fund for a yield, drawn the wrong way round), and on the
 * operator's Mac on 2026-11-01 all seven were blank anyway (HISTORY #52).
 *
 * This draws the readings each sweep lands (`/api/macro/history`), the same
 * source as the numbers view, so a level and its chart cannot disagree.
 * `lightweight-charts` is the engine; the data is ours.
 */

import { useEffect, useRef } from 'react';
import { token } from '@/lib/tokens';

export type MacroPoint = { at: string; value: number };

/** A hex colour with an alpha, as the chart library wants it. */
function alpha(hex: string, a: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return a === 0 ? 'rgba(0,0,0,0)' : hex;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

/** Points as the chart wants them: strictly increasing seconds; two sweeps in
 *  the same second keep the later reading. */
export function asSeries(points: MacroPoint[]): { time: number; value: number }[] {
  const byTime = new Map<number, number>();
  for (const point of points) {
    const seconds = Math.floor(Date.parse(point.at) / 1000);
    if (Number.isFinite(seconds)) byTime.set(seconds, point.value);
  }
  return [...byTime.entries()].sort((x, y) => x[0] - y[0]).map(([time, value]) => ({ time, value }));
}

/**
 * One macro series as an area chart. `compact` draws a sparkline (no axes, no
 * grid) for a card; otherwise a full chart with its price scale and dates.
 */
export function MacroLine({
  points,
  height = 150,
  compact = false,
}: {
  points: MacroPoint[];
  height?: number;
  compact?: boolean;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  const enough = points.length >= 2;

  useEffect(() => {
    const node = holder.current;
    if (!node || !enough) return;
    let disposed = false;
    let chart: { remove: () => void } | null = null;

    import('lightweight-charts')
      .then(({ createChart, AreaSeries, ColorType }) => {
        if (disposed || !holder.current) return;
        const data = asSeries(points);
        const rising = data.length > 1 && data[data.length - 1].value >= data[0].value;
        const line = rising ? token('--up', '#16a34a') : token('--down', '#dc2626');
        const made = createChart(holder.current, {
          layout: {
            background: { type: ColorType.Solid, color: 'transparent' },
            textColor: token('--ink-3', '#64748b'),
            attributionLogo: false,
          },
          grid: { vertLines: { visible: false }, horzLines: { visible: !compact, color: token('--rule', '#e2e8f0') } },
          rightPriceScale: { visible: !compact, borderVisible: false },
          leftPriceScale: { visible: false },
          timeScale: { visible: !compact, borderVisible: false, timeVisible: false },
          crosshair: compact ? { vertLine: { visible: false }, horzLine: { visible: false } } : undefined,
          handleScroll: !compact,
          handleScale: !compact,
          height,
          autoSize: true,
        });
        chart = made;
        const series = made.addSeries(AreaSeries, {
          lineColor: line,
          topColor: alpha(line, 0.28),
          bottomColor: alpha(line, 0),
          lineWidth: 2,
          priceLineVisible: !compact,
          lastValueVisible: !compact,
          crosshairMarkerVisible: !compact,
        });
        series.setData(data.map((d) => ({ time: d.time as never, value: d.value })));
        made.timeScale().fitContent();
      })
      .catch(() => undefined);

    return () => {
      disposed = true;
      chart?.remove();
    };
  }, [points, enough, height, compact]);

  if (!enough) return <div className="tempty">{points.length ? 'One reading so far.' : 'Nothing recorded yet.'}</div>;
  return <div ref={holder} style={{ height, width: '100%' }} />;
}
