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

export function MacroLine({ label, unit, points }: { label: string; unit: string; points: MacroPoint[] }) {
  const holder = useRef<HTMLDivElement | null>(null);
  const first = points[0]?.at.slice(0, 10);
  const enough = points.length >= 2;

  useEffect(() => {
    const node = holder.current;
    if (!node || !enough) return;
    let disposed = false;
    let chart: { remove: () => void } | null = null;

    import('lightweight-charts')
      .then(({ createChart, LineSeries, ColorType }) => {
        if (disposed || !holder.current) return;
        const grid = token('--rule', '#e2e8f0');
        const made = createChart(holder.current, {
          layout: {
            background: { type: ColorType.Solid, color: 'transparent' },
            textColor: token('--ink-3', '#64748b'),
            attributionLogo: false,
          },
          grid: { vertLines: { visible: false }, horzLines: { color: grid } },
          rightPriceScale: { borderVisible: false },
          timeScale: { borderVisible: false, timeVisible: false },
          height: 150,
          autoSize: true,
        });
        chart = made;
        const series = made.addSeries(LineSeries, {
          color: token('--accent', '#2563eb'),
          lineWidth: 2,
          priceLineVisible: false,
        });
        // The chart needs strictly increasing times; two sweeps in the same
        // second keep the later reading.
        const byTime = new Map<number, number>();
        for (const point of points) {
          const seconds = Math.floor(Date.parse(point.at) / 1000);
          if (Number.isFinite(seconds)) byTime.set(seconds, point.value);
        }
        const data = [...byTime.entries()]
          .sort((a, b) => a[0] - b[0])
          .map(([time, value]) => ({ time: time as never, value }));
        series.setData(data);
        made.timeScale().fitContent();
      })
      .catch(() => undefined);

    return () => {
      disposed = true;
      chart?.remove();
    };
  }, [points, enough]);

  return (
    <div className="ownchart">
      <div className="ownhead">
        <b>{label}</b>
        <span className="tfine">
          {points.length
            ? `${points.length} readings since ${first}${unit ? ` · ${unit}` : ''}`
            : 'no readings recorded yet'}
        </span>
      </div>
      {enough ? (
        <div className="macroline" ref={holder} />
      ) : (
        <div className="tempty">
          {points.length ? 'One reading so far; a line needs two.' : 'Nothing recorded yet.'}
        </div>
      )}
    </div>
  );
}
