'use client';

/**
 * The Charts page.
 *
 * ### Whose data this is
 *
 * **NSE symbols: ours.** They are drawn only by `OwnChart` from the bars a
 * backtest reads, with our own drawing tools and indicators (ADR-114). The
 * free TradingView embed refused `NSE:NIFTYBEES` on the operator's Mac, and a
 * chart from the same rows as a result cannot disagree with it.
 *
 * **Every other venue: TradingView's.** Their Advanced Chart widget is a
 * window onto a third party's feed, so a close there can differ from ours:
 * vendors adjust for corporate actions differently and continuous contracts
 * are stitched by rules we do not control. **Never reconcile a backtest
 * against the embed.** Where we hold bars for that venue, our chart sits
 * below it.
 *
 * The macro band below plots our own sweeps (`/api/macro/history`).
 */

import { Info } from '@/components/terminal/ui';
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

  // NSE symbols are drawn from our own bars, not the embed. The free embed
  // answers "only available on TradingView" for NSE listings, NIFTYBEES
  // included (seen on the operator's Mac, 2026-11-01, HISTORY #52).
  const ours = symbol.startsWith('NSE:');

  useEffect(() => {
    const node = holder.current;
    if (!node || ours) return;

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
  }, [symbol, interval, ours]);

  function go(next: string) {
    const clean = next.trim().toUpperCase();
    if (clean) setSymbol(clean);
  }

  return (
    <>
      <section className="thero">
        <div>
          <div className="thnum">
            <b style={{ fontSize: 28 }}>{symbol.split(':').pop()}</b>
            <span className="unit">{symbol}</span>
          </div>
        </div>
        <div className="tsyncbox">
          {ours ? (
            <>
              <span className="ui-chip">Our own bars</span>
              <Info align="right">
                Drawn from the price panel, the same rows a backtest reads. TradingView&rsquo;s free
                embed refuses NSE listings, so there are no drawing tools here;{' '}
                <a
                  href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(symbol)}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  open it on TradingView
                </a>{' '}
                for those.
              </Info>
            </>
          ) : (
            <>
              <span className="ui-chip">TradingView data</span>
              <Info align="right">
                Data, drawing tools and indicators are TradingView&rsquo;s. A close here can differ
                from the panel&rsquo;s: never reconcile a backtest against this chart.
              </Info>
            </>
          )}
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

        {/* These drive the TradingView embed only. NSE symbols are drawn by
            our own chart, which has its own timeframe buttons; showing both
            left two rows of 1m to 1W where one did nothing (2026-11-01). */}
        {!ours && (
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
        )}

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
          <span className="ui-chip">ETFs, not indices</span>
          <Info>
            NIFTYBEES, BANKBEES and JUNIORBEES are ETFs, named for the funds they are rather than
            the indices they track: Nippon India&rsquo;s Nifty 50, Nifty Bank and Nifty Next 50
            funds, drawn from our own price panel. An ETF is close to its index but not the same
            instrument: it carries tracking error and trades at its own premium.
          </Info>
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
      {!ours && <div className="chartholder" ref={holder} />}

      {/* The same instrument from our own bars, when we hold them. For NSE it
          is the chart; elsewhere it sits under the embed, which has the
          drawing tools, so a reader can see where a vendor's adjusted close
          differs from the panel's. */}
      {ownOf(symbol) && (
        <OwnChart symbol={ownOf(symbol)!.symbol} assetClass={ownOf(symbol)!.assetClass} />
      )}

      {/* Below the chart, as asked: what a trader checks around a price. */}
      <MacroBand rows={macro} spread={spread} stale={stale} />
    </>
  );
}
