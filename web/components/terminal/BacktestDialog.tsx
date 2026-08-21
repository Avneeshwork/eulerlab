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
 */

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { FleetStrategy, Instrument, WindowInfo } from '@/lib/api';

const WINDOWS = [250, 500, 800, 1200, 1800, 2500, 2869];

export function BacktestDialog({
  strategy,
  window: days,
  tier,
  universe,
  instruments,
  onWindow,
  onTier,
  onUniverse,
  onInstruments,
  onRun,
  onClose,
}: {
  strategy: FleetStrategy;
  window: number;
  tier: 'A' | 'B';
  universe: string;
  instruments: string[];
  onWindow: (days: number) => void;
  onTier: (tier: 'A' | 'B') => void;
  onUniverse: (name: string) => void;
  onInstruments: (symbols: string[]) => void;
  onRun: () => void;
  onClose: () => void;
}) {
  const [info, setInfo] = useState<WindowInfo | null>(null);
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<Instrument[]>([]);
  const [batches, setBatches] = useState<string[]>([]);

  useEffect(() => {
    api
      .window(days, universe)
      .then(setInfo)
      .catch(() => setInfo(null));
  }, [days, universe]);

  useEffect(() => {
    const timer = setTimeout(() => {
      api
        .instruments(query, '')
        .then((list) => {
          setFound(list.instruments);
          setBatches(list.batches);
        })
        .catch(() => setFound([]));
    }, 180);
    return () => clearTimeout(timer);
  }, [query]);

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
  const lookbackTooLong = info?.ok ? strategy.lookback >= info.traded_days : false;

  return (
    <div className="pal-scrim" role="dialog" aria-modal="true" aria-label="Backtest" onClick={onClose}>
      <div className="dlg wide tall" onClick={(event) => event.stopPropagation()}>
        <header className="dlg-head">
          <div style={{ minWidth: 0 }}>
            <div className="theyebrow">Backtest</div>
            <h2>{strategy.title}</h2>
            <div className="tfine" style={{ marginTop: 4 }}>
              {strategy.kind} · {strategy.asset_class} · {strategy.timeframe} · needs{' '}
              {strategy.lookback} days of history
            </div>
          </div>
          <button className="ticon" type="button" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="dlg-body">
          <h4 className="report-h">Period</h4>
          <div className="ttools" style={{ marginBottom: 12 }}>
            {WINDOWS.map((value) => (
              <button
                key={value}
                className="tchip"
                type="button"
                aria-pressed={days === value}
                onClick={() => onWindow(value)}
              >
                {value >= 2869 ? 'everything' : `${value}d`}
              </button>
            ))}
            <label className="tsort">
              Tier
              <select value={tier} onChange={(event) => onTier(event.target.value as 'A' | 'B')}>
                <option value="B">B — event-driven engine</option>
                <option value="A">A — vectorised screen</option>
              </select>
            </label>
          </div>

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
                <b>This window is too short for this strategy.</b> It needs{' '}
                {strategy.lookback} days of history and only {info?.traded_days} are traded,
                so it will hold nothing. The run refuses rather than reporting a Sharpe of
                zero — zero is a measurement, and this would be an absence.
              </div>
            </div>
          )}

          <h4 className="report-h">Instruments</h4>
          <div className="ttools" style={{ marginBottom: 12 }}>
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
            {batches.map((name) => (
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
                        <b>{instrument.symbol}</b>
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

          <p className="tfine">
            {custom
              ? `${instruments.length} hand-picked instruments. This overrides the batch and is recorded as a custom run, with the list itself in the configuration hash — so a different list is a different result, not another "custom".`
              : universe === 'all'
                ? 'The whole panel. Batches are liquidity-ranked from our own turnover history rather than index membership, because a published constituent list only exists as it stands today and using one across history is survivorship bias.'
                : `The ${universe} batch — liquidity-ranked from our own turnover history, not index membership.`}
          </p>

          <div className="dlg-foot">
            <div className="verdict" data-ok={!lookbackTooLong}>
              {custom ? `${instruments.length} instruments` : universe} · tier {tier} ·{' '}
              {info?.ok ? `${info.traded_days} days traded` : `${days} days`} · spends no
              trial
            </div>
            <button className="tbtn ghost-line" type="button" onClick={onClose}>
              Cancel
            </button>
            <button className="tbtn go" type="button" disabled={tooShort} onClick={onRun}>
              Run backtest
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
