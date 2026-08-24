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
import { api } from '@/lib/api';
import type { MacroReading } from '@/lib/api';
import { MacroBand } from '@/components/terminal/MacroBand';
import { OwnChart } from '@/components/terminal/OwnChart';

type Market = 'NSE' | 'US' | 'CRYPTO' | 'FX' | 'MACRO';

const PRESETS: Record<Market, { label: string; symbols: [string, string][] }> = {
  NSE: {
    label: 'NSE',
    symbols: [
      // ETFs, not the indices themselves. `NSE:NIFTY` is a real symbol and the
      // free embed refuses it — index data is licensed separately from equity
      // data, so the widget answers "only available on TradingView". NIFTYBEES
      // is an ordinary security tracking the same index and embeds fine.
      ['NSE:NIFTYBEES', 'NIFTYBEES'],
      ['NSE:BANKBEES', 'BANKBEES'],
      ['NSE:JUNIORBEES', 'JUNIORBEES'],
      ['NSE:RELIANCE', 'RELIANCE'],
      ['NSE:TCS', 'TCS'],
      ['NSE:HDFCBANK', 'HDFC BANK'],
      ['NSE:ICICIBANK', 'ICICI BANK'],
      ['NSE:INFY', 'INFOSYS'],
      ['NSE:SBIN', 'SBI'],
      ['NSE:BHARTIARTL', 'AIRTEL'],
      ['NSE:ITC', 'ITC'],
      ['NSE:LT', 'LARSEN & TOUBRO'],
      ['NSE:TATAMOTORS', 'TATA MOTORS'],
      ['NSE:AXISBANK', 'AXIS BANK'],
      ['NSE:MARUTI', 'MARUTI'],
      ['NSE:SUNPHARMA', 'SUN PHARMA'],
    ],
  },
  US: {
    label: 'US',
    symbols: [
      ['AMEX:SPY', 'SPY'],
      ['NASDAQ:QQQ', 'QQQ'],
      ['AMEX:DIA', 'DIA'],
      ['AMEX:IWM', 'IWM'],
      ['NASDAQ:AAPL', 'APPLE'],
      ['NASDAQ:MSFT', 'MICROSOFT'],
      ['NASDAQ:NVDA', 'NVIDIA'],
      ['NASDAQ:AMZN', 'AMAZON'],
      ['NASDAQ:GOOGL', 'ALPHABET'],
      ['NASDAQ:META', 'META'],
      ['NASDAQ:TSLA', 'TESLA'],
      ['NYSE:JPM', 'JPMORGAN'],
    ],
  },
  CRYPTO: {
    label: 'Crypto',
    symbols: [
      ['BINANCE:BTCUSDT', 'BTC/USDT'],
      ['BINANCE:ETHUSDT', 'ETH/USDT'],
      ['BINANCE:SOLUSDT', 'SOL/USDT'],
      ['BINANCE:XRPUSDT', 'XRP/USDT'],
      ['BINANCE:BNBUSDT', 'BNB/USDT'],
      ['BINANCE:DOGEUSDT', 'DOGE/USDT'],
      ['BINANCE:ADAUSDT', 'ADA/USDT'],
      ['BINANCE:AVAXUSDT', 'AVAX/USDT'],
      ['CRYPTOCAP:TOTAL', 'TOTAL MARKET CAP'],
      ['CRYPTOCAP:BTC.D', 'BTC DOMINANCE'],
    ],
  },
  FX: {
    label: 'Forex',
    symbols: [
      ['FX_IDC:USDINR', 'USD/INR'],
      ['FX:EURUSD', 'EUR/USD'],
      ['FX:USDJPY', 'USD/JPY'],
      ['FX:GBPUSD', 'GBP/USD'],
      ['FX:AUDUSD', 'AUD/USD'],
      ['FX:USDCAD', 'USD/CAD'],
      ['FX:USDCHF', 'USD/CHF'],
      ['FX:EURJPY', 'EUR/JPY'],
      ['TVC:DXY', 'DOLLAR INDEX'],
    ],
  },
  MACRO: {
    label: 'Macro',
    symbols: [
      // The band the operator asked for, as charts rather than a single
      // reading. TVC symbols are TradingView's own aggregates and embed freely
      // where the underlying exchange feeds do not.
      ['TVC:US10Y', 'US 10Y YIELD'],
      ['TVC:US02Y', 'US 2Y YIELD'],
      ['TVC:US30Y', 'US 30Y YIELD'],
      ['TVC:IN10Y', 'INDIA 10Y YIELD'],
      ['TVC:USOIL', 'WTI CRUDE'],
      ['TVC:UKOIL', 'BRENT CRUDE'],
      ['TVC:GOLD', 'GOLD'],
      ['TVC:SILVER', 'SILVER'],
      ['TVC:VIX', 'VIX'],
      ['NSE:GOLDBEES', 'GOLDBEES'],
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

/** Whether we hold our own bars for a charted symbol, and under what name.
 *
 *  The embed's symbol and ours are not the same string: it wants
 *  `NSE:RELIANCE` and `BINANCE:BTCUSDT`, while the panel wants `RELIANCE` and
 *  the crypto archive wants `BTCUSDT`. Keeping that translation in one place
 *  beats scattering it through the render.
 *
 *  Returns null for anything not landed — US listings, sovereign yields, the
 *  dollar index — so those show the embed alone rather than an empty panel
 *  claiming we hold data we do not.
 */
function ownOf(charted: string): { symbol: string; assetClass: string } | null {
  const [venue, rest] = charted.includes(':') ? charted.split(':') : ['', charted];
  if (venue === 'NSE') return { symbol: rest, assetClass: 'equity' };
  if (venue === 'BINANCE') return { symbol: rest, assetClass: 'crypto' };
  if (venue === 'FX' || venue === 'FX_IDC') return { symbol: rest, assetClass: 'fx' };
  return null;
}

export function ChartTab() {
  const [market, setMarket] = useState<Market>('NSE');
  const [symbol, setSymbol] = useState('NSE:NIFTYBEES');
  const [interval, setInterval] = useState('D');
  const [typed, setTyped] = useState('');
  const holder = useRef<HTMLDivElement | null>(null);
  const [macro, setMacro] = useState<MacroReading[]>([]);
  const [spread, setSpread] = useState<number | null>(null);
  const [stale, setStale] = useState(false);

  // The macro band reads the landed sweep, same as the snapshot's ribbon —
  // one file rather than seventeen requests per page view.
  useEffect(() => {
    let live = true;
    api
      .snapshot('')
      .then((snap) => {
        if (!live) return;
        setMacro(snap.world?.macro ?? []);
        setSpread(snap.world?.macro_2s10s ?? null);
        setStale(Boolean(snap.world?.stale_groups?.includes('macro')));
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

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
            Data, drawing tools and indicators are TradingView&rsquo;s. A close here can
            differ from the panel&rsquo;s &mdash; never reconcile a backtest against this
            chart.
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

      {market === 'NSE' && (
        <p className="tfine mktgap" style={{ marginBottom: 10 }}>
          NIFTYBEES, BANKBEES and JUNIORBEES are <b>ETFs</b>, named for the funds they
          are rather than the indices they track &mdash; Nippon India&rsquo;s Nifty 50,
          Nifty Bank and Nifty Next 50 funds. The embed refuses `NSE:NIFTY` itself because
          index data is licensed separately, and an ETF is close to its index but not the
          same instrument: it carries tracking error and trades at its own premium. The
          chart below each one is the real index series from our own panel.
        </p>
      )}

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

      {/* The same instrument from our own bars, when we hold them. Shown
          beside the embed rather than instead of it: the embed has the drawing
          tools, this has the provenance, and a reader comparing the two can
          see for themselves where a vendor's adjusted close differs from the
          panel's. */}
      {ownOf(symbol) && (
        <OwnChart symbol={ownOf(symbol)!.symbol} assetClass={ownOf(symbol)!.assetClass} />
      )}

      {/* Below the chart, as asked: what a trader checks around a price. */}
      <MacroBand rows={macro} spread={spread} stale={stale} />
    </>
  );
}
