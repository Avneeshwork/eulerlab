'use client';

/**
 * A candlestick chart drawn from **this platform's own bars**.
 *
 * The TradingView embed refuses a great deal of what needs charting here:
 * index data is licensed separately from equity data, so `NSE:NIFTY` errors
 * outright, and the ETF proxies substituted for it are a different instrument
 * with their own tracking error. That is a poor foundation on a platform whose
 * panel already holds the real series.
 *
 * So this renders `/api/history` — the same rows a backtest reads, which means
 * a chart and a result cannot disagree about what happened. `lightweight-charts`
 * is TradingView's own engine under an MIT licence, so the drawing is theirs
 * and the data is ours.
 *
 * What it deliberately does not do is compete with the embed on features.
 * There are no drawing tools and no indicator library here; that is what the
 * embed above is for. This is the honest-provenance view, and the two sit
 * together rather than one pretending to be the other.
 */

import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { Bar } from '@/lib/api';
import { token } from '@/lib/tokens';

export function OwnChart({
  symbol,
  assetClass = 'equity',
  days = 260,
}: {
  symbol: string;
  assetClass?: string;
  days?: number;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  const [note, setNote] = useState('');
  const [bars, setBars] = useState<Bar[]>([]);

  useEffect(() => {
    let live = true;
    setNote('');
    api
      .history(symbol, assetClass, days)
      .then((result) => {
        if (!live) return;
        if (!result.ok) {
          setBars([]);
          // Named, not blank. "We hold nothing for this symbol" and "the
          // request failed" are different answers and the panel says which.
          setNote(result.error ?? 'no bars');
          return;
        }
        setBars(result.bars);
        setNote(`${result.bars.length} bars · ${result.source} · to ${result.last}`);
      })
      .catch((problem) => live && setNote(String(problem)));
    return () => {
      live = false;
    };
  }, [symbol, assetClass, days]);

  useEffect(() => {
    const node = holder.current;
    if (!node || !bars.length) return;

    let disposed = false;
    let chart: { remove: () => void } | null = null;

    // Imported at use rather than at module load: the library is ~50KB and
    // nothing else on the terminal needs it.
    import('lightweight-charts')
      .then(({ createChart, CandlestickSeries, ColorType }) => {
        if (disposed || !holder.current) return;
        const up = token('--up', '#16a34a');
        const down = token('--down', '#dc2626');
        const grid = token('--rule', '#e2e8f0');
        const edge = token('--rule-2', '#cbd5e1');

        const made = createChart(holder.current, {
          layout: {
            background: { type: ColorType.Solid, color: 'transparent' },
            textColor: token('--ink-3', '#64748b'),
            attributionLogo: false,
          },
          grid: {
            vertLines: { color: grid },
            horzLines: { color: grid },
          },
          rightPriceScale: { borderColor: edge },
          timeScale: { borderColor: edge, rightOffset: 4 },
          height: 320,
          autoSize: true,
        });
        chart = made;

        const series = made.addSeries(CandlestickSeries, {
          upColor: up,
          downColor: down,
          borderUpColor: up,
          borderDownColor: down,
          wickUpColor: up,
          wickDownColor: down,
        });
        series.setData(
          bars.map((bar) => ({
            time: bar.time,
            open: bar.open,
            high: bar.high,
            low: bar.low,
            close: bar.close,
          })),
        );
        made.timeScale().fitContent();
      })
      .catch((problem) => setNote(String(problem)));

    return () => {
      disposed = true;
      chart?.remove();
    };
  }, [bars]);

  return (
    <div className="ownchart">
      <div className="ownhead">
        <b>{symbol}</b>
        <span className="tfine">{note || 'loading…'}</span>
      </div>
      {bars.length > 0 ? (
        <div className="ownholder" ref={holder} />
      ) : (
        <div className="tempty">{note || 'loading…'}</div>
      )}
    </div>
  );
}
