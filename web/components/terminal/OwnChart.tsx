'use client';

/**
 * A trading chart drawn from **this platform's own bars**.
 *
 * The TradingView embed refuses NSE listings in its free form (NIFTYBEES said
 * "only available on TradingView" on the operator's Mac, 2026-11-01), so this
 * is the main chart for anything we hold. It renders `/api/history`, the same
 * rows a backtest reads, so a chart and a result cannot disagree.
 * `lightweight-charts` (MIT) is the engine; the data is ours.
 *
 * What it adds over plain candles, as the operator asked ("horizontal vertical
 * lines, interactable, some features of TradingView"):
 * - a crosshair readout of the bar under the cursor: open, high, low, close,
 *   change and volume;
 * - range buttons, a log scale and a reset;
 * - drawings: horizontal, vertical and trend lines, erased by clicking near
 *   one, kept per symbol in this browser;
 * - indicators computed from the same bars (`lib/indicators.ts`, tested):
 *   volume, SMA 20/50/200, EMA 20, Bollinger 20/2, RSI 14 and MACD 12/26/9
 *   in panes below.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  IChartApi,
  ISeriesApi,
  Logical,
  MouseEventParams,
  SeriesType,
  Time,
} from 'lightweight-charts';
import { api } from '@/lib/api';
import type { Bar } from '@/lib/api';
import { bollinger, ema, macd, rsi, sma, type Series } from '@/lib/indicators';
import { token } from '@/lib/tokens';

type Tool = 'cursor' | 'hline' | 'vline' | 'trend' | 'erase';

type Drawing =
  | { kind: 'hline'; price: number }
  | { kind: 'vline'; time: string }
  | { kind: 'trend'; t1: string; p1: number; t2: string; p2: number };

type Indicator = 'volume' | 'sma20' | 'sma50' | 'sma200' | 'ema20' | 'bollinger' | 'rsi' | 'macd';

const INDICATORS: [Indicator, string][] = [
  ['volume', 'Volume'],
  ['sma20', 'SMA 20'],
  ['sma50', 'SMA 50'],
  ['sma200', 'SMA 200'],
  ['ema20', 'EMA 20'],
  ['bollinger', 'Bollinger 20, 2'],
  ['rsi', 'RSI 14'],
  ['macd', 'MACD 12, 26, 9'],
];

const RANGES: [string, number | null][] = [
  ['1M', 21],
  ['3M', 63],
  ['6M', 126],
  ['1Y', 252],
  ['5Y', 1260],
  ['All', null],
];

const TOOLS: [Tool, string, string][] = [
  ['cursor', 'Cursor', 'Move and zoom'],
  ['hline', '— Horizontal', 'Click a price'],
  ['vline', '| Vertical', 'Click a day'],
  ['trend', '/ Trend', 'Click two points'],
  ['erase', 'Erase', 'Click near a line to remove it'],
];

/** Read and write a symbol's drawings. Browser storage can be missing or
 *  blocked; the chart works without it, it just forgets. */
function storageKey(assetClass: string, symbol: string) {
  return `eulerlab.drawings.${assetClass}.${symbol}`;
}
function loadDrawings(key: string): Drawing[] {
  try {
    const raw = window.localStorage.getItem(key);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as Drawing[]) : [];
  } catch {
    return [];
  }
}
function saveDrawings(key: string, drawings: Drawing[]) {
  try {
    window.localStorage.setItem(key, JSON.stringify(drawings));
  } catch {
    /* storage blocked: drawings last for this view only */
  }
}
function loadIndicators(): Indicator[] {
  try {
    const raw = window.localStorage.getItem('eulerlab.chart.indicators');
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed) ? (parsed as Indicator[]) : ['volume', 'sma50'];
  } catch {
    return ['volume', 'sma50'];
  }
}

const fmt = (value: number) =>
  value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtVolume = (value: number) =>
  value >= 1e7 ? `${(value / 1e7).toFixed(2)} Cr` : value >= 1e5 ? `${(value / 1e5).toFixed(2)} L` : value.toFixed(0);

export function OwnChart({
  symbol,
  assetClass = 'equity',
  days = 2600,
}: {
  symbol: string;
  assetClass?: string;
  days?: number;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainRef = useRef<ISeriesApi<SeriesType> | null>(null);
  const [note, setNote] = useState('');
  const [bars, setBars] = useState<Bar[]>([]);
  const [tool, setTool] = useState<Tool>('cursor');
  const [log, setLog] = useState(false);
  const [shown, setShown] = useState<Indicator[]>(['volume', 'sma50']);
  const [menu, setMenu] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [anchor, setAnchor] = useState<{ time: string; price: number } | null>(null);
  const [preview, setPreview] = useState<{ time: string; price: number } | null>(null);
  const [tick, setTick] = useState(0);
  const key = storageKey(assetClass, symbol);

  useEffect(() => setShown(loadIndicators()), []);
  useEffect(() => {
    setDrawings(loadDrawings(key));
    setAnchor(null);
  }, [key]);

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

  const index = useMemo(() => new Map(bars.map((bar, i) => [bar.time, i])), [bars]);
  const closes = useMemo(() => bars.map((bar) => bar.close), [bars]);

  const setIndicators = (next: Indicator[]) => {
    setShown(next);
    try {
      window.localStorage.setItem('eulerlab.chart.indicators', JSON.stringify(next));
    } catch {
      /* not remembered */
    }
  };

  // --- the chart itself: rebuilt when the bars or the indicator set change ---
  useEffect(() => {
    const node = holder.current;
    if (!node || !bars.length) return;
    let disposed = false;

    import('lightweight-charts')
      .then(
        ({
          createChart,
          CandlestickSeries,
          HistogramSeries,
          LineSeries,
          ColorType,
          CrosshairMode,
          PriceScaleMode,
        }) => {
          if (disposed || !holder.current) return;
          const up = token('--up', '#16a34a');
          const down = token('--down', '#dc2626');
          const grid = token('--rule', '#e2e8f0');
          const edge = token('--rule-2', '#cbd5e1');
          const accent = token('--accent', '#2563eb');
          const amber = token('--amber', '#d97706');
          const ink = token('--ink-3', '#64748b');

          const chart = createChart(holder.current, {
            layout: {
              background: { type: ColorType.Solid, color: 'transparent' },
              textColor: ink,
              attributionLogo: false,
              panes: { separatorColor: edge },
            },
            grid: { vertLines: { color: grid }, horzLines: { color: grid } },
            crosshair: { mode: CrosshairMode.Normal },
            rightPriceScale: {
              borderColor: edge,
              mode: log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
            },
            timeScale: { borderColor: edge, rightOffset: 6 },
            autoSize: true,
          });
          chartRef.current = chart;

          const candles = chart.addSeries(CandlestickSeries, {
            upColor: up,
            downColor: down,
            borderUpColor: up,
            borderDownColor: down,
            wickUpColor: up,
            wickDownColor: down,
          });
          candles.setData(
            bars.map((bar) => ({
              time: bar.time as Time,
              open: bar.open,
              high: bar.high,
              low: bar.low,
              close: bar.close,
            })),
          );
          mainRef.current = candles;

          const line = (values: Series, color: string, pane = 0, width: 1 | 2 = 2) => {
            const series = chart.addSeries(
              LineSeries,
              {
                color,
                lineWidth: width,
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: false,
              },
              pane,
            );
            series.setData(
              values.flatMap((value, i) =>
                value === null ? [] : [{ time: bars[i].time as Time, value }],
              ),
            );
            return series;
          };

          if (shown.includes('volume')) {
            const volume = chart.addSeries(HistogramSeries, {
              priceScaleId: 'volume',
              priceFormat: { type: 'volume' },
              lastValueVisible: false,
              priceLineVisible: false,
            });
            volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
            volume.setData(
              bars.map((bar, i) => ({
                time: bar.time as Time,
                value: bar.volume,
                color: (i === 0 || bar.close >= bars[i - 1].close ? up : down) + '66',
              })),
            );
          }
          if (shown.includes('sma20')) line(sma(closes, 20), accent, 0, 1);
          if (shown.includes('sma50')) line(sma(closes, 50), amber, 0, 1);
          if (shown.includes('sma200')) line(sma(closes, 200), ink, 0, 1);
          if (shown.includes('ema20')) line(ema(closes, 20), up, 0, 1);
          if (shown.includes('bollinger')) {
            const bands = bollinger(closes, 20, 2);
            line(bands.upper, ink, 0, 1);
            line(bands.middle, ink, 0, 1);
            line(bands.lower, ink, 0, 1);
          }
          let pane = 1;
          if (shown.includes('rsi')) {
            const series = line(rsi(closes, 14), accent, pane);
            series.createPriceLine({ price: 70, color: down, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' });
            series.createPriceLine({ price: 30, color: up, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '' });
            pane += 1;
          }
          if (shown.includes('macd')) {
            const m = macd(closes);
            const histogram = chart.addSeries(
              HistogramSeries,
              { priceLineVisible: false, lastValueVisible: false },
              pane,
            );
            histogram.setData(
              m.histogram.flatMap((value, i) =>
                value === null
                  ? []
                  : [{ time: bars[i].time as Time, value, color: (value >= 0 ? up : down) + '99' }],
              ),
            );
            line(m.macd, accent, pane, 1);
            line(m.signal, amber, pane, 1);
          }
          // The price pane keeps most of the height; each indicator pane gets a strip.
          chart.panes().forEach((p, i) => p.setStretchFactor(i === 0 ? 380 : 120));

          chart.timeScale().subscribeVisibleLogicalRangeChange(() => setTick((t) => t + 1));
          chart.subscribeCrosshairMove((param: MouseEventParams<Time>) => {
            const at = param.logical;
            setHover(at === undefined || at === null ? null : Math.round(at));
          });
          const visible = Math.min(bars.length, 252);
          chart.timeScale().setVisibleLogicalRange({ from: bars.length - visible, to: bars.length + 4 });
          setTick((t) => t + 1);
        },
      )
      .catch((problem) => setNote(String(problem)));

    return () => {
      disposed = true;
      chartRef.current?.remove();
      chartRef.current = null;
      mainRef.current = null;
    };
  }, [bars, closes, shown, log]);

  // --- clicks: what a drawing tool does with them ---
  // Read from the DOM, not `chart.subscribeClick`: the library swallows a
  // second click that lands within half a second of the first (it is waiting
  // to see whether it is a double click), which lost the second point of
  // nearly every trend line when this was first tried.
  const pointAt = useCallback(
    (event: MouseEvent): { time: string; price: number; x: number; y: number } | null => {
      const chart = chartRef.current;
      const series = mainRef.current;
      const node = holder.current;
      if (!chart || !series || !node || !bars.length) return null;
      const box = node.getBoundingClientRect();
      const px = event.clientX - box.left;
      const py = event.clientY - box.top;
      // Only the price pane takes drawings; the indicator panes have no price.
      const priceHeight = chart.panes()[0]?.getHeight() ?? 0;
      if (px < 0 || py < 0 || px > chart.timeScale().width() || py > priceHeight) return null;
      const logical = chart.timeScale().coordinateToLogical(px);
      const price = series.coordinateToPrice(py);
      if (logical === null || price === null) return null;
      const i = Math.max(0, Math.min(bars.length - 1, Math.round(logical)));
      return { time: bars[i].time, price, x: px, y: py };
    },
    [bars],
  );

  useEffect(() => {
    const node = holder.current;
    if (!node || tool === 'cursor') return;
    const onClick = (event: MouseEvent) => {
      const at = pointAt(event);
      if (!at) return;
      if (tool === 'hline') setDrawings((d) => [...d, { kind: 'hline', price: at.price }]);
      if (tool === 'vline') setDrawings((d) => [...d, { kind: 'vline', time: at.time }]);
      if (tool === 'trend') {
        if (!anchor) setAnchor({ time: at.time, price: at.price });
        else {
          setDrawings((d) => [...d, { kind: 'trend', t1: anchor.time, p1: anchor.price, t2: at.time, p2: at.price }]);
          setAnchor(null);
          setPreview(null);
        }
      }
      if (tool === 'erase') {
        setDrawings((d) => {
          const hit = d.findIndex((drawing) => distance(drawing, at.x, at.y) < 8);
          return hit < 0 ? d : d.filter((_, i) => i !== hit);
        });
      }
    };
    const onMove = (event: MouseEvent) => {
      if (tool !== 'trend' || !anchor) return;
      const at = pointAt(event);
      if (at) setPreview({ time: at.time, price: at.price });
    };
    node.addEventListener('click', onClick);
    node.addEventListener('mousemove', onMove);
    return () => {
      node.removeEventListener('click', onClick);
      node.removeEventListener('mousemove', onMove);
    };
    // `distance` reads coordinates, which change with tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool, anchor, pointAt, tick, bars]);
  useEffect(() => saveDrawings(key, drawings), [key, drawings]);

  // --- coordinates for the overlay ---
  const x = (time: string): number | null => {
    const chart = chartRef.current;
    const i = index.get(time);
    if (!chart || i === undefined) return null;
    return chart.timeScale().logicalToCoordinate(i as Logical);
  };
  const y = (price: number): number | null => mainRef.current?.priceToCoordinate(price) ?? null;

  function distance(drawing: Drawing, px: number, py: number): number {
    if (drawing.kind === 'hline') {
      const at = y(drawing.price);
      return at === null ? Infinity : Math.abs(at - py);
    }
    if (drawing.kind === 'vline') {
      const at = x(drawing.time);
      return at === null ? Infinity : Math.abs(at - px);
    }
    const ax = x(drawing.t1);
    const ay = y(drawing.p1);
    const bx = x(drawing.t2);
    const by = y(drawing.p2);
    if (ax === null || ay === null || bx === null || by === null) return Infinity;
    const length = Math.hypot(bx - ax, by - ay) || 1;
    const t = Math.max(0, Math.min(1, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / length ** 2));
    return Math.hypot(px - (ax + t * (bx - ax)), py - (ay + t * (by - ay)));
  }

  const width = chartRef.current?.timeScale().width() ?? holder.current?.clientWidth ?? 0;
  const paneHeight = chartRef.current?.panes()[0]?.getHeight() ?? 380;
  const lineColor = token('--accent', '#2563eb');
  const shapes = [
    ...drawings,
    ...(anchor && preview
      ? [{ kind: 'trend', t1: anchor.time, p1: anchor.price, t2: preview.time, p2: preview.price } as Drawing]
      : []),
  ];

  // --- the readout: the bar under the cursor, or the last one ---
  const shownIndex = hover !== null && hover >= 0 && hover < bars.length ? hover : bars.length - 1;
  const bar = bars[shownIndex];
  const prev = shownIndex > 0 ? bars[shownIndex - 1] : undefined;
  const change = bar && prev ? bar.close / prev.close - 1 : null;

  const zoom = (count: number | null) => {
    const chart = chartRef.current;
    if (!chart || !bars.length) return;
    if (count === null) chart.timeScale().fitContent();
    else chart.timeScale().setVisibleLogicalRange({ from: bars.length - count, to: bars.length + 4 });
  };

  return (
    <div className="ownchart tchart">
      <div className="ownhead">
        <b>{symbol}</b>
        <span className="tfine">{note || 'loading…'}</span>
      </div>

      <div className="tchart-tools">
        <div className="mkttoggle">
          {RANGES.map(([label, count]) => (
            <button key={label} type="button" onClick={() => zoom(count)}>
              {label}
            </button>
          ))}
        </div>
        <div className="mkttoggle">
          <button type="button" className={log ? 'on' : ''} onClick={() => setLog(!log)} title="Logarithmic price scale">
            Log
          </button>
          <button type="button" onClick={() => zoom(252)} title="Back to the last year">
            Reset
          </button>
        </div>
        <div className="mkttoggle">
          {TOOLS.map(([value, label, hint]) => (
            <button
              key={value}
              type="button"
              title={hint}
              className={tool === value ? 'on' : ''}
              onClick={() => {
                setTool(value);
                setAnchor(null);
                setPreview(null);
              }}
            >
              {label}
            </button>
          ))}
          <button type="button" onClick={() => setDrawings([])} disabled={!drawings.length} title="Remove every line on this symbol">
            Clear
          </button>
        </div>
        <div className="tchart-menu">
          <button type="button" className="tbtn" onClick={() => setMenu(!menu)} aria-expanded={menu}>
            Indicators{shown.length ? ` · ${shown.length}` : ''}
          </button>
          {menu && (
            <div className="tchart-pop" role="menu">
              {INDICATORS.map(([value, label]) => (
                <label key={value}>
                  <input
                    type="checkbox"
                    checked={shown.includes(value)}
                    onChange={(event) =>
                      setIndicators(
                        event.target.checked ? [...shown, value] : shown.filter((v) => v !== value),
                      )
                    }
                  />
                  {label}
                </label>
              ))}
            </div>
          )}
        </div>
      </div>

      {bars.length > 0 ? (
        <div className="tchart-body" data-tool={tool}>
          {bar && (
            <div className="tchart-legend">
              <span>{bar.time}</span>
              <span>O <b>{fmt(bar.open)}</b></span>
              <span>H <b>{fmt(bar.high)}</b></span>
              <span>L <b>{fmt(bar.low)}</b></span>
              <span>C <b>{fmt(bar.close)}</b></span>
              {change !== null && (
                <span className={change >= 0 ? 'tup' : 'tdn'}>
                  {change >= 0 ? '+' : '−'}
                  {Math.abs(change * 100).toFixed(2)}%
                </span>
              )}
              {bar.volume > 0 && <span>Vol <b>{fmtVolume(bar.volume)}</b></span>}
            </div>
          )}
          <div
            className="tchart-holder"
            ref={holder}
            style={{ height: 380 + 120 * ((shown.includes('rsi') ? 1 : 0) + (shown.includes('macd') ? 1 : 0)) }}
          />
          <svg className="tchart-overlay" width={width} height={paneHeight} data-tick={tick}>
            {shapes.map((drawing, i) => {
              if (drawing.kind === 'hline') {
                const at = y(drawing.price);
                if (at === null) return null;
                return (
                  <g key={i}>
                    <line x1={0} x2={width} y1={at} y2={at} stroke={lineColor} strokeWidth={1.5} />
                    <text x={6} y={at - 4} className="tchart-label">
                      {fmt(drawing.price)}
                    </text>
                  </g>
                );
              }
              if (drawing.kind === 'vline') {
                const at = x(drawing.time);
                if (at === null) return null;
                return (
                  <g key={i}>
                    <line x1={at} x2={at} y1={0} y2={paneHeight} stroke={lineColor} strokeWidth={1.5} />
                    <text x={at + 4} y={14} className="tchart-label">
                      {drawing.time}
                    </text>
                  </g>
                );
              }
              const ax = x(drawing.t1);
              const ay = y(drawing.p1);
              const bx = x(drawing.t2);
              const by = y(drawing.p2);
              if (ax === null || ay === null || bx === null || by === null) return null;
              return <line key={i} x1={ax} y1={ay} x2={bx} y2={by} stroke={lineColor} strokeWidth={1.5} />;
            })}
          </svg>
          {tool === 'trend' && anchor && <div className="tchart-hint">Click the second point</div>}
        </div>
      ) : (
        <div className="tempty">{note || 'loading…'}</div>
      )}
    </div>
  );
}
