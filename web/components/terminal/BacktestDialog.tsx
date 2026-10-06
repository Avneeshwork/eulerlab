'use client';

/**
 * What to run, over what, and over which period — asked before the run rather
 * than assumed.
 *
 * Backtest used to fire immediately on whatever the toolbar happened to be set
 * to, which meant the two facts that most change a result — the instruments and
 * the period — were the two the operator could not see at the moment of
 * deciding.
 *
 * The period is shown as dates, not as a day count, and it distinguishes the
 * window from the part actually traded. A 1200-day window spends 253 days on
 * warmup; calling the result "1200 days" would describe a period the strategy
 * never traded in.
 *
 * This is the only place a backtest is configured. One strategy (a row's
 * Backtest button) and several (the selection bar) open the same dialog; the
 * separate Run tab that used to offer a second, smaller set of the same
 * controls is gone, so a run's settings can only ever be read from here.
 */

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { ASSET_CLASSES } from '@/lib/assetClasses';
import type { FleetStrategy, Instrument, RunPrice, WindowInfo } from '@/lib/api';
import { BacktestOptions, BacktestWindowNote } from './BacktestOptions';


export function BacktestDialog({
  strategies,
  window: days,
  tier,
  universe,
  instruments,
  assetClass,
  onWindow,
  onTier,
  onUniverse,
  onInstruments,
  onAssetClass,
  dateRange,
  onDateRange,
  startingCash,
  onStartingCash,
  onRun,
  onClose,
}: {
  /** One strategy from a row, or the whole selection. */
  strategies: FleetStrategy[];
  window: number;
  tier: 'A' | 'B';
  universe: string;
  instruments: string[];
  assetClass: string;
  onWindow: (days: number) => void;
  onTier: (tier: 'A' | 'B') => void;
  onUniverse: (name: string) => void;
  onInstruments: (symbols: string[]) => void;
  onAssetClass: (name: string) => void;
  /** An explicit window, or empty strings for "the last N days".
   *
   *  Both or neither: a start with no end could mean "until today" or "for N
   *  days", and guessing would answer a different question than the one asked. */
  dateRange: { start: string; end: string };
  onDateRange: (range: { start: string; end: string }) => void;
  startingCash: number;
  onStartingCash: (amount: number) => void;
  onRun: () => void;
  onClose: () => void;
}) {
  const [info, setInfo] = useState<WindowInfo | null>(null);
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<Instrument[]>([]);
  const [batches, setBatches] = useState<string[]>([]);
  const [price, setPrice] = useState<RunPrice | null>(null);
  const single = strategies.length === 1 ? strategies[0] : null;
  const lookback = Math.max(0, ...strategies.map((s) => s.lookback));

  // What the run would do to the noise bar, shown before the button. It used
  // to live only on the Run tab, so a run started from the library never saw it.
  useEffect(() => {
    let live = true;
    api
      .priceRun(strategies.length, 0)
      .then((quote) => live && setPrice(quote))
      .catch(() => live && setPrice(null));
    return () => {
      live = false;
    };
  }, [strategies.length]);

  useEffect(() => {
    setInfo(null);
    // Guarded against its own earlier self. Switching asset class fires a
    // second request while the first is in flight, and the equity panel answers
    // in milliseconds while crypto resamples a minute archive — so the *older*
    // response landed last and painted equity dates under a "Crypto" label.
    let live = true;
    api
      .window(days, universe, assetClass)
      .then((next) => live && setInfo(next))
      .catch(() => live && setInfo(null));
    return () => {
      live = false;
    };
  }, [days, universe, assetClass]);

  useEffect(() => {
    const timer = setTimeout(() => {
      api
        .instruments(query, '', assetClass, 40)
        .then((list) => {
          setFound(list.instruments);
          setBatches(list.batches);
        })
        .catch(() => setFound([]));
    }, 180);
    return () => clearTimeout(timer);
  }, [query, assetClass]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const toggle = useCallback(
    (symbol: string) =>
      onInstruments(
        instruments.includes(symbol)
          ? instruments.filter((s) => s !== symbol)
          : [...instruments, symbol]
      ),
    [instruments, onInstruments]
  );

  const custom = instruments.length > 0;
  const tooShort = info?.ok ? info.traded_days <= 0 : false;
  const lookbackTooLong = info?.ok ? lookback >= info.traded_days : false;

  return (
    <div className="pal-scrim" role="dialog" aria-modal="true" aria-label="Backtest" onClick={onClose}>
      <div className="dlg wide tall" onClick={(event) => event.stopPropagation()}>
        <header className="dlg-head">
          <div style={{ minWidth: 0 }}>
            <div className="theyebrow">Backtest</div>
            <h2>{single ? single.title : `${strategies.length} strategies`}</h2>
            <div className="tfine" style={{ marginTop: 4 }}>
              {single
                ? `${single.kind} · ${single.asset_class} · ${single.timeframe} · needs ${single.lookback} days of history`
                : `${strategies.map((s) => s.title).join(', ')} · the longest needs ${lookback} days of history`}
            </div>
          </div>
          <button className="ticon" type="button" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="dlg-body">
          <h4 className="report-h">Period</h4>
          <BacktestOptions
            window={days}
            tier={tier}
            dateRange={dateRange}
            startingCash={startingCash}
            onWindow={onWindow}
            onTier={onTier}
            onDateRange={onDateRange}
            onStartingCash={onStartingCash}
          />
          <BacktestWindowNote dateRange={dateRange} />

          {!info && (
            <div className="period">
              <div>
                <span>Reading the panel</span>
                <b>…</b>
                <i>
                  {assetClass === 'equity'
                    ? 'trimming to the window'
                    : 'first load resamples the raw archive, which takes a couple of minutes'}
                </i>
              </div>
            </div>
          )}

          {info?.ok && (
            <div className="period">
              <div>
                <span>Window</span>
                <b>
                  {info.window_first} → {info.window_last}
                </b>
                <i>{info.window_days.toLocaleString('en-IN')} trading days</i>
              </div>
              <div>
                <span>Warmup, never traded</span>
                <b>{info.warmup_days} days</b>
                <i>so features have history to compute from</i>
              </div>
              <div>
                <span>Actually traded</span>
                <b>
                  {info.traded_first} → {info.traded_last}
                </b>
                <i>{info.traded_days.toLocaleString('en-IN')} trading days</i>
              </div>
              {info.truncated && (
                <p>
                  You asked for {info.requested_days.toLocaleString('en-IN')} days but the
                  panel only holds {info.available_days.toLocaleString('en-IN')}, starting{' '}
                  {info.panel_first}. The run will cover everything there is.
                </p>
              )}
            </div>
          )}

          {lookbackTooLong && !tooShort && (
            <div className="tnote bad" style={{ marginTop: 12 }}>
              <span className="mk">▲</span>
              <div>
                <b>This window is too short for {single ? 'this strategy' : 'the longest of these'}.</b> It needs{' '}
                {lookback} days of history and only {info?.traded_days} are traded,
                so it will hold nothing. The run refuses rather than reporting a Sharpe of
                zero — zero is a measurement, and this would be an absence.
              </div>
            </div>
          )}

          <h4 className="report-h">Instruments</h4>
          <div className="ttools" style={{ marginBottom: 12 }}>
            <label className="tsort" style={{ marginLeft: 0 }}>
              Asset
              <select
                value={assetClass}
                onChange={(event) => {
                  onAssetClass(event.target.value);
                  onInstruments([]);
                  onUniverse('all');
                }}
              >
                {/* From `lib/assetClasses`, not a local list. Three components
                    kept their own copies and drifted — US and FX were runnable
                    and offered nowhere. */}
                {ASSET_CLASSES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="tchip"
              type="button"
              aria-pressed={!custom && universe === 'all'}
              onClick={() => {
                onInstruments([]);
                onUniverse('all');
              }}
            >
              Whole panel
            </button>
            {assetClass === 'equity' && batches.map((name) => (
              <button
                key={name}
                className="tchip"
                type="button"
                aria-pressed={!custom && universe === name}
                onClick={() => {
                  onInstruments([]);
                  onUniverse(name);
                }}
              >
                {name}
              </button>
            ))}
            <input
              className="tsearch"
              style={{ flex: '1 1 180px', minWidth: 160 }}
              placeholder="…or search to add individual names"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label="Search instruments"
            />
          </div>

          {custom && (
            <div className="chosen-rail" style={{ padding: '0 0 12px' }}>
              {instruments.map((symbol) => (
                <button key={symbol} className="chosen-chip" type="button" onClick={() => toggle(symbol)}>
                  {symbol} <span aria-hidden="true">✕</span>
                </button>
              ))}
              <button className="tbtn sm ghost-line" type="button" onClick={() => onInstruments([])}>
                Clear
              </button>
            </div>
          )}

          {query.trim() !== '' && (
            <div className="tscroll" style={{ maxHeight: '26vh', marginBottom: 12 }}>
              <table className="ttable">
                <tbody>
                  {found.map((instrument) => (
                    <tr key={`${instrument.asset_class}-${instrument.symbol}`}>
                      <td style={{ width: 26 }}>
                        <input
                          type="checkbox"
                          checked={instruments.includes(instrument.symbol)}
                          onChange={() => toggle(instrument.symbol)}
                          aria-label={`Add ${instrument.symbol}`}
                        />
                      </td>
                      <td>
                        <b>{instrument.name || instrument.symbol}</b>
                        {instrument.name && <div className="tfine">{instrument.symbol}</div>}
                      </td>
                      <td>
                        <span className="ttag">{instrument.asset_class}</span>
                      </td>
                      <td className="r">{instrument.rank || <span className="tdim">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {found.length === 0 && <div className="tempty">Nothing matches.</div>}
            </div>
          )}

          {info?.ok && info.cost_mode !== 'realistic' && (
            <p className="tfine" style={{ marginBottom: 10 }}>
              No cost model covers {assetClass.replace('_', ' ')}, so this run pays nothing
              to trade. The result is an upper bound, not a net figure.
            </p>
          )}

          {/* Which venue's bill this run pays. Stated because it changes the
              answer more than most parameters do, and because the same engine
              charges three different schedules depending on this dropdown. */}
          {assetClass === 'us' && (
            <p className="tfine" style={{ marginBottom: 10 }}>
              Costed at <b>INDmoney</b>: 0.25% a leg, capped at $25 per transaction, plus
              18% GST — a flat $29.50 a leg above $10,000 of notional. The cap is what
              makes US viable here; uncapped, 0.25% a leg is 0.5% a round trip and no
              intraday signal survives it. Currency conversion is not included: it is a
              cost on moving capital, not on trading.
            </p>
          )}
          {assetClass === 'fx' && (
            <p className="tfine" style={{ marginBottom: 10 }}>
              Costed at the <b>measured bid-ask spread</b>, carried per bar in the landed
              data. FX pays no exchange charges, STT or stamp duty — the spread is the
              cost, and charging what was observed is not the same as inventing a fee.
            </p>
          )}

          <p className="tfine">
            {custom
              ? `${instruments.length} hand-picked instruments. This overrides the batch and is recorded as a custom run, with the list itself in the configuration hash — so a different list is a different result, not another "custom".`
              : assetClass === 'crypto'
                ? 'Every landed pair. Binance spot, resampled from the minute archive to daily bars.'
                : assetClass === 'us'
                  ? 'The landed S&P 500 names, from Alpaca daily bars. Volume is the IEX feed — one venue with a low single-digit share of the consolidated tape — so prices track closely and volume does not, which matters for anything liquidity-ranked.'
                  : assetClass === 'fx'
                    ? 'Every landed pair. FXCM minute bars resampled to daily, carrying the measured spread. Volume is zero and that is a fact rather than a gap: spot FX has no central exchange and therefore no consolidated volume.'
                : assetClass === 'mutual_fund'
                  ? 'Every scheme with landed NAV history. Direct growth plans only, so a scheme is not counted once per plan variant.'
                  : universe === 'all'
                    ? 'The whole panel. Batches are liquidity-ranked from our own turnover history rather than index membership, because a published constituent list only exists as it stands today and using one across history is survivorship bias.'
                    : `The ${universe} batch — liquidity-ranked from our own turnover history, not index membership.`}
          </p>

          {price && (
            <div className="tfacts" style={{ margin: '4px 0 12px' }}>
              <div className="tfact">
                <span>Bar now</span>
                <b>{price.bar_now.toFixed(2)}</b>
              </div>
              <div className="tfact">
                <span>Bar if recorded</span>
                <b>{price.would_move_bar_to.toFixed(2)}</b>
              </div>
              <div className="tfact">
                <span>Trials spent</span>
                <b>{price.spends_trials}</b>
              </div>
            </div>
          )}

          <div className="dlg-foot">
            <div className="verdict" data-ok={!lookbackTooLong}>
              {assetClass !== 'equity' ? `${assetClass.replace('_', ' ')} · ` : ''}
              {custom ? `${instruments.length} instruments` : universe} · tier {tier} ·{' '}
              {info?.ok ? `${info.traded_days} days traded` : `${days} days`} · spends no
              trial
            </div>
            <button className="tbtn ghost-line" type="button" onClick={onClose}>
              Cancel
            </button>
            <button className="tbtn go" type="button" disabled={tooShort} onClick={onRun}>
              {single ? 'Run backtest' : `Backtest ${strategies.length}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
