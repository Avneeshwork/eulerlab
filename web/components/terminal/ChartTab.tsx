'use client';

/**
 * A full charting surface — TradingView's Advanced Chart widget.
 *
 * ### Whose data this is
 *
 * **TradingView's, not this platform's.** That distinction is the whole reason
 * this file has a comment at the top. Every other number on this terminal is
 * traceable: the map and breadth come from the NSE panel or live Kite quotes,
 * the index ribbon from the broker and FMP, the backtests from landed bars we
 * hold and can re-read. This chart is a window onto a third party's feed.
 *
 * So a close here can differ from a close in the panel — different vendors
 * adjust for corporate actions differently, and TradingView's continuous
 * contracts are stitched by rules we do not control. **Never reconcile a
 * backtest against this chart.** It is for looking, drawing and thinking; the
 * numbers that decide anything come from the read API.
 *
 * The alternative was `lightweight-charts`, which renders *our* bars with
 * TradingView's engine. It was not chosen because it has no drawing tools, no
 * indicator library and no symbol search — which is most of what a chart is
 * for at this stage. The trade is honest provenance for capability, and the
 * banner says which way it went.
 */

import { useEffect, useRef, useState } from 'react';

type Market = 'NSE' | 'BSE' | 'CRYPTO' | 'FX' | 'US';

const PRESETS: Record<Market, { label: string; symbols: [string, string][] }> = {
  NSE: {
    label: 'NSE',
    symbols: [
      ['NSE:NIFTY', 'NIFTY 50'],
      ['NSE:BANKNIFTY', 'BANK NIFTY'],
      ['NSE:RELIANCE', 'RELIANCE'],
      ['NSE:TCS', 'TCS'],
      ['NSE:HDFCBANK', 'HDFC BANK'],
      ['NSE:INFY', 'INFOSYS'],
    ],
  },
  BSE: { label: 'BSE', symbols: [['BSE:SENSEX', 'SENSEX']] },
  US: {
    label: 'US',
    symbols: [
      ['SP:SPX', 'S&P 500'],
      ['NASDAQ:NDX', 'NASDAQ 100'],
      ['NASDAQ:AAPL', 'APPLE'],
      ['NASDAQ:NVDA', 'NVIDIA'],
    ],
  },
  CRYPTO: {
    label: 'Crypto',
    symbols: [
      ['BINANCE:BTCUSDT', 'BTC/USDT'],
      ['BINANCE:ETHUSDT', 'ETH/USDT'],
      ['BINANCE:SOLUSDT', 'SOL/USDT'],
    ],
  },
  FX: {
    label: 'Forex',
    symbols: [
      ['FX_IDC:USDINR', 'USD/INR'],
      ['FX:EURUSD', 'EUR/USD'],
      ['FX:USDJPY', 'USD/JPY'],
      ['FX:GBPUSD', 'GBP/USD'],
    ],
  },
};

const INTERVALS: [string, string][] = [
  ['1', '1m'],
  ['5', '5m'],
  ['15', '15m'],
  ['60', '1h'],
  ['D', '1D'],
  ['W', '1W'],
];

export function ChartTab() {
  const [market, setMarket] = useState<Market>('NSE');
  const [symbol, setSymbol] = useState('NSE:NIFTY');
  const [interval, setInterval] = useState('D');
  const [typed, setTyped] = useState('');
  const holder = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = holder.current;
    if (!node) return;

    // The widget writes into whatever node it is given and does not clean up
    // after itself, so the container is emptied first. Without this, changing
    // symbol stacks a second chart under the first.
    node.innerHTML = '';

    const dark =
      document.documentElement.dataset.theme === 'dark' ||
      (!document.documentElement.dataset.theme &&
        window.matchMedia('(prefers-color-scheme: dark)').matches);

    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol,
      interval,
      timezone: 'Asia/Kolkata',
      theme: dark ? 'dark' : 'light',
      style: '1',
      locale: 'en',
      allow_symbol_change: true,
      withdateranges: true,
      hide_side_toolbar: false, // the drawing tools live here
      details: true,
      studies: ['STD;SMA', 'STD;RSI'],
      support_host: 'https://www.tradingview.com',
    });
    node.appendChild(script);

    return () => {
      node.innerHTML = '';
    };
  }, [symbol, interval]);

  function go(next: string) {
    const clean = next.trim().toUpperCase();
    if (clean) setSymbol(clean);
  }

  return (
    <>
      <section className="thero">
        <div>
          <div className="theyebrow">Chart</div>
          <div className="thnum">
            <b style={{ fontSize: 28 }}>{symbol.split(':').pop()}</b>
            <span className="unit">{symbol}</span>
          </div>
        </div>
        <div className="tsyncbox">
          <span className="tfine" style={{ textAlign: 'right' }}>
            Drawing tools, indicators and symbol search are TradingView&rsquo;s, and so is
            the data. A close here can differ from the panel&rsquo;s &mdash; never reconcile
            a backtest against this chart.
          </span>
        </div>
      </section>

      <div className="ttools" style={{ flexWrap: 'wrap', gap: 8 }}>
        <div className="mkttoggle">
          {(Object.keys(PRESETS) as Market[]).map((key) => (
            <button
              key={key}
              type="button"
              className={market === key ? 'on' : ''}
              onClick={() => {
                setMarket(key);
                const first = PRESETS[key].symbols[0];
                if (first) setSymbol(first[0]);
              }}
            >
              {PRESETS[key].label}
            </button>
          ))}
        </div>

        <div className="mkttoggle">
          {INTERVALS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={interval === value ? 'on' : ''}
              onClick={() => setInterval(value)}
            >
              {label}
            </button>
          ))}
        </div>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            go(typed);
          }}
          style={{ display: 'flex', gap: 6 }}
        >
          <input
            className="tsearch"
            style={{ minWidth: 190 }}
            placeholder="Any symbol — NSE:TITAN, BINANCE:BTCUSDT…"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
          <button className="tbtn" type="submit">
            Load
          </button>
        </form>
      </div>

      <div className="chipbar">
        {PRESETS[market].symbols.map(([value, label]) => (
          <button
            key={value}
            type="button"
            className={symbol === value ? 'chip on' : 'chip'}
            onClick={() => setSymbol(value)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Given a real height rather than a percentage: the widget measures its
          container on mount, and a container that is auto-height at that moment
          measures zero and renders nothing at all. */}
      <div className="chartholder" ref={holder} />
    </>
  );
}
