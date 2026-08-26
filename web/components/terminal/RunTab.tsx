'use client';

/**
 * The batch runner.
 *
 * The price of the run is shown before the button, not after it. An interface
 * that makes running feel free is how somebody spends fifty configurations in
 * an afternoon and never notices that the noise bar has no idea any of it
 * happened.
 */

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { UniverseNote, UniversePicker } from '@/components/terminal/UniversePicker';
import { runBatch } from '@/lib/run';
import { ASSET_CLASSES } from '@/lib/assetClasses';
import type { BatchResult, Fleet, Instrument, RunPrice, WindowInfo } from '@/lib/api';

export function RunTab({
  fleet,
  window: days,
  tier,
  universe,
  instruments,
  assetClass,
  onAssetClass,
  onWindow,
  onTier,
  onUniverse,
  onInstruments,
  onRefresh,
}: {
  fleet: Fleet | null;
  window: number;
  tier: 'A' | 'B';
  universe: string;
  instruments: string[];
  assetClass: string;
  onAssetClass: (name: string) => void;
  onWindow: (days: number) => void;
  onTier: (tier: 'A' | 'B') => void;
  onUniverse: (name: string) => void;
  onInstruments: (symbols: string[]) => void;
  onRefresh: () => void;
}) {
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [price, setPrice] = useState<RunPrice | null>(null);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<WindowInfo | null>(null);
  const [symbolQuery, setSymbolQuery] = useState('');
  const [found, setFound] = useState<Instrument[]>([]);

  // Same period logic as the Backtest dialog, from the same endpoint, so the
  // two surfaces cannot describe the same run differently.
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
    if (symbolQuery.trim() === '') {
      setFound([]);
      return;
    }
    const timer = setTimeout(() => {
      api.instruments(symbolQuery, '', assetClass, 40).then((l) => setFound(l.instruments)).catch(() => setFound([]));
    }, 180);
    return () => clearTimeout(timer);
  }, [symbolQuery, assetClass]);

  const toggleSymbol = (symbol: string) =>
    onInstruments(
      instruments.includes(symbol)
        ? instruments.filter((s) => s !== symbol)
        : [...instruments, symbol]
    );

  const runnable = (fleet?.strategies ?? []).filter((s) => s.runnable);
  const custom = instruments.length > 0;

  useEffect(() => {
    if (picked.size === 0) {
      setPrice(null);
      return;
    }
    let live = true;
    api
      .priceRun(picked.size, 0)
      .then((quote) => live && setPrice(quote))
      .catch(() => live && setPrice(null));
    return () => {
      live = false;
    };
  }, [picked]);

  const go = useCallback(async () => {
    setBusy(true);
    setError('');
    setResult(null);
    try {
      const outcome = await runBatch(
        [...picked],
        days,
        tier,
        universe,
        instruments,
        assetClass,
        setNote
      );
      setResult(outcome);
      onRefresh();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  }, [picked, days, tier, universe, instruments, assetClass, onRefresh]);

  return (
    <>
      <section className="thero">
        <div>
          <div className="theyebrow">Run</div>
          <div className="thnum">
            <b>{picked.size}</b>
            <span className="unit">selected</span>
          </div>
          <p className="thsub">
            Screening runs the same engine <code>make backtest</code> uses. It writes
            nothing to the trial ledger, which means the noise bar does not move — and does
            not learn that the search happened.
          </p>
        </div>
        <div className="thstats">
          <div className="thstat">
            <span>Bar now</span>
            <b>{price ? price.bar_now.toFixed(2) : (fleet?.bar.toFixed(2) ?? '—')}</b>
          </div>
          <div className="thstat">
            <span>Bar if recorded</span>
            <b>{price ? price.would_move_bar_to.toFixed(2) : '—'}</b>
          </div>
          <div className="thstat">
            <span>Trials spent</span>
            <b>{price ? price.spends_trials : 0}</b>
          </div>
        </div>
      </section>

      <div className="ttools">
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
            {ASSET_CLASSES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        {assetClass === 'equity' && <UniversePicker value={universe} onChange={onUniverse} />}
        <input
          className="tsearch"
          style={{ flex: '1 1 200px', minWidth: 170 }}
          placeholder="…or search to add individual instruments"
          value={symbolQuery}
          onChange={(event) => setSymbolQuery(event.target.value)}
          aria-label="Search instruments"
        />
        <label className="tsort" style={{ marginLeft: 0 }}>
          Window
          <select
            value={days}
            onChange={(event) => onWindow(Number(event.target.value))}
          >
            {[250, 500, 800, 1200, 2000, 2800].map((value) => (
              <option key={value} value={value}>
                {value} days
              </option>
            ))}
          </select>
        </label>
        <label className="tsort" style={{ marginLeft: 0 }}>
          Tier
          <select value={tier} onChange={(event) => onTier(event.target.value as 'A' | 'B')}>
            <option value="B">B — event-driven engine</option>
            <option value="A">A — vectorised screen</option>
          </select>
        </label>
        <button
          className="tchip"
          type="button"
          onClick={() => setPicked(new Set(runnable.map((s) => s.id)))}
        >
          Select all {runnable.length}
        </button>
        <button className="tchip" type="button" onClick={() => setPicked(new Set())}>
          Clear
        </button>
      </div>

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
        </div>
      )}

      {info?.ok && info.cost_mode !== 'realistic' && (
        <p className="tfine">
          No cost model covers {assetClass.replace('_', ' ')}, so these runs pay nothing to
          trade. Results are upper bounds, not net figures.
        </p>
      )}

      {custom && (
        <div className="chosen-rail" style={{ padding: 0 }}>
          {instruments.map((symbol) => (
            <button key={symbol} className="chosen-chip" type="button" onClick={() => toggleSymbol(symbol)}>
              {symbol} <span aria-hidden="true">✕</span>
            </button>
          ))}
          <button className="tbtn sm ghost-line" type="button" onClick={() => onInstruments([])}>
            Clear
          </button>
        </div>
      )}

      {symbolQuery.trim() !== '' && (
        <div className="tpanel" style={{ padding: 0 }}>
          <div className="tscroll" style={{ maxHeight: '24vh' }}>
            <table className="ttable">
              <tbody>
                {found.map((instrument) => (
                  <tr key={`${instrument.asset_class}-${instrument.symbol}`}>
                    <td style={{ width: 26 }}>
                      <input
                        type="checkbox"
                        checked={instruments.includes(instrument.symbol)}
                        onChange={() => toggleSymbol(instrument.symbol)}
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
          </div>
          {found.length === 0 && <div className="tempty">Nothing matches.</div>}
        </div>
      )}

      <div className="tgrid">
        <div className="tpanel">
          <h3>Strategies</h3>
          <div className="tscroll" style={{ maxHeight: 420 }}>
            <table className="ttable">
              <tbody>
                {runnable.map((strategy) => (
                  <tr key={strategy.id}>
                    <td style={{ width: 26 }}>
                      <input
                        type="checkbox"
                        checked={picked.has(strategy.id)}
                        onChange={() =>
                          setPicked((prev) => {
                            const next = new Set(prev);
                            if (next.has(strategy.id)) next.delete(strategy.id);
                            else next.add(strategy.id);
                            return next;
                          })
                        }
                        aria-label={`Select ${strategy.title}`}
                      />
                    </td>
                    <td>
                      <b>{strategy.title}</b>
                      <div className="tfine">
                        {strategy.kind} · lookback {strategy.lookback}d
                        {strategy.lookback >= days && (
                          <span className="tflag" style={{ marginLeft: 6 }}>
                            lookback exceeds window
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="r">
                      <span className="ttag">{strategy.asset_class}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="tpanel">
          <h3>What this run costs</h3>
          {instruments.length > 0 ? (
            <p className="tfine">
              <b>{instruments.length} hand-picked instruments</b> — this overrides the
              universe and is recorded as a custom run.
            </p>
          ) : (
            <UniverseNote value={universe} />
          )}
          {price ? (
            <>
              <div className="tfacts">
                <div className="tfact">
                  <span>Configurations</span>
                  <b>{price.configurations}</b>
                </div>
                <div className="tfact">
                  <span>New evaluations</span>
                  <b>{price.new_evaluations}</b>
                </div>
                <div className="tfact">
                  <span>Trials spent</span>
                  <b>{price.spends_trials}</b>
                </div>
              </div>
            </>
          ) : (
            <div className="tempty">Select something to price it.</div>
          )}

          <div className="tacts" style={{ marginTop: 16 }}>
            <button className="tbtn go" type="button" disabled={busy || picked.size === 0} onClick={go}>
              {busy ? 'Running…' : `Backtest ${picked.size}`}
            </button>
          </div>
          {busy && note && <div className="trunning" style={{ marginTop: 12 }}>{note}</div>}
          {error && (
            <div className="tnote bad" style={{ marginTop: 12 }}>
              <span className="mk">▲</span>
              <div>{error}</div>
            </div>
          )}
        </div>
      </div>

      {result && (
        <div className="tpanel">
          <h3>Result</h3>
          <div className="tfacts">
            <div className="tfact">
              <span>Computed</span>
              <b>{result.computed}</b>
            </div>
            <div className="tfact">
              <span>Cached</span>
              <b>{result.cached}</b>
            </div>
            <div className="tfact">
              <span>Failed</span>
              <b className={result.failed ? 'neg' : ''}>{result.failed}</b>
            </div>
            <div className="tfact">
              <span>Unrecorded</span>
              <b>{result.unrecorded}</b>
            </div>
            <div className="tfact">
              <span>Mirrored</span>
              <b className={result.cloud && !result.cloud.ok ? 'neg' : ''}>
                {result.cloud ? (result.cloud.ok ? result.cloud.pushed : 'failed') : '—'}
              </b>
            </div>
          </div>
          <table className="ttable" style={{ marginTop: 16 }}>
            <thead>
              <tr>
                <th>Strategy</th>
                <th className="r">Sharpe</th>
                <th className="r">Return</th>
                <th className="r">Drawdown</th>
                <th className="r">Fills</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {result.results.map((row) => (
                <tr key={row.strategy}>
                  <td>
                    <b>{row.strategy}</b>
                  </td>
                  {row.error ? (
                    <td colSpan={5} className="tdim">
                      {row.error}
                    </td>
                  ) : (
                    <>
                      <td className="r">{row.result?.sharpe.toFixed(2)}</td>
                      <td className="r">{((row.result?.total_return ?? 0) * 100).toFixed(1)}%</td>
                      <td className="r">{((row.result?.max_drawdown ?? 0) * 100).toFixed(1)}%</td>
                      <td className="r">{row.result?.fills}</td>
                      <td>{row.cached ? 'cached' : 'computed'}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="tfine" style={{ marginTop: 12 }}>
            {result.note}
          </p>
        </div>
      )}
    </>
  );
}
