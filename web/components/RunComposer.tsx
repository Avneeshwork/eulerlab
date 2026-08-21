'use client';

/**
 * Screening a batch, and being honest about what it costs.
 *
 * The first version of this said "Spend 2 trials and run". That was false: a
 * batch of backtests writes nothing to the ledger — only `make validate` and
 * `make gate` do, and neither is reachable from here. Shipping it would have
 * been a false claim in the UI of a project whose entire premise is not making
 * false claims in its UI.
 *
 * What is true is more interesting, and worse. Screening is free, so the
 * counter never moves — which means this surface lets you search without
 * paying for it. ADR-036 named that exact hole: *skip new configurations and
 * the search is laundered, invisibly, by construction.* So the panel reports
 * where the bar **would** stand if this search were recorded, and the result
 * reports how many configurations went unrecorded. Neither closes the gap.
 * Both stop it being silent.
 */

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { BatchResult, RunPrice } from '@/lib/api';

export function RunComposer({
  strategies,
  instruments,
  batch,
}: {
  strategies: string[];
  instruments: number;
  batch: string;
}) {
  const [price, setPrice] = useState<RunPrice | null>(null);
  const [days, setDays] = useState(800);
  const [tier, setTier] = useState<'A' | 'B'>('B');
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState('');
  const [result, setResult] = useState<BatchResult | null>(null);
  const [problem, setProblem] = useState('');

  const configurations = strategies.length;

  useEffect(() => {
    if (configurations === 0) {
      setPrice(null);
      return;
    }
    // Cached count is 0 here: the composer cannot know what the cache holds
    // without asking the runner, and guessing would make the forecast fiction.
    api.priceRun(configurations, 0).then(setPrice).catch(() => undefined);
  }, [configurations]);

  const run = useCallback(async () => {
    setProblem('');
    setResult(null);
    setRunning(true);
    setMessage('starting');

    // 'all' is the whole panel, which is exactly what this screen ran on
    // before the universe selector existed. Passing it keeps the old
    // workbench's numbers comparable with the ones it has already produced.
    const started = await api.runBatch(strategies, days, tier, 'all').catch(() => null);
    if (!started?.ok || !started.job) {
      setProblem(started?.error ?? 'could not start the batch');
      setRunning(false);
      return;
    }

    const poll = setInterval(async () => {
      const state = await api.batchJob(started.job!).catch(() => null);
      if (!state) return;
      setMessage(`${state.message} · ${state.elapsed}s`);
      if (state.status === 'done' || state.status === 'failed') {
        clearInterval(poll);
        setRunning(false);
        if (state.status === 'failed') setProblem(state.error);
        else setResult(state.result);
      }
    }, 1000);
  }, [strategies, days, tier]);

  return (
    <div className="card">
      <h2>Screen</h2>
      <p className="sub">
        Runs each selected strategy through the same engine <code className="inline">make
        backtest</code> uses.
      </p>

      <div className="compose-grid">
        <div className="cfield">
          <span className="lab">Strategies</span>
          <span className="val">
            {configurations === 0 ? 'none selected' : `${configurations} selected`}
          </span>
        </div>
        <div className="cfield">
          <span className="lab">Instruments</span>
          <span className="val">
            {batch || 'none'}{' '}
            {instruments > 0 && <span className="muted">· {instruments} names</span>}
          </span>
        </div>
        <label className="cfield">
          <span className="lab">Window</span>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={250}>250 days — about 1 year</option>
            <option value={500}>500 days — about 2 years</option>
            <option value={800}>800 days — about 3 years</option>
            <option value={1500}>1500 days — about 6 years</option>
          </select>
        </label>
        <label className="cfield">
          <span className="lab">Engine</span>
          <select value={tier} onChange={(e) => setTier(e.target.value as 'A' | 'B')}>
            <option value="B">Tier B — event-driven</option>
            <option value="A">Tier A — screen only</option>
          </select>
        </label>
      </div>

      {configurations === 0 && (
        <p className="muted" style={{ marginTop: 12 }}>
          Select at least one strategy in the fleet.
        </p>
      )}

      {price && (
        <>
          <div className="cost free">
            <div className="cost-h">Spends no trial</div>
            <div className="cost-move">
              <span className="from">{price.bar_now.toFixed(2)}</span>
              <span className="arw">stays</span>
              <span className="to">{price.bar_now.toFixed(2)}</span>
              <span className="cost-unit">noise bar, unchanged</span>
            </div>
            <p className="cost-note">{price.note}</p>
          </div>

          {price.unrecorded_search && (
            <div className="note warn" style={{ marginTop: 10 }}>
              Recorded, this search would put the bar at{' '}
              <strong>{price.would_move_bar_to.toFixed(2)}</strong>. It will not be recorded.
              That difference is the gap, not a saving.
            </div>
          )}

          <div className="actions">
            <button className="go safe" onClick={run} disabled={running}>
              {running && <span className="spinner" />}
              {running ? 'Screening…' : `Screen ${configurations} strateg${configurations === 1 ? 'y' : 'ies'}`}
            </button>
            {running && <span className="muted">{message}</span>}
          </div>
        </>
      )}

      {problem && (
        <div className="note bad" style={{ marginTop: 12 }}>
          <pre>{problem}</pre>
        </div>
      )}

      {result && (
        <div className="batch-result">
          <div className="batch-stats">
            <span>
              <b>{result.total}</b> run
            </span>
            <span>
              <b>{result.cached}</b> cached
            </span>
            <span>
              <b>{result.computed}</b> computed
            </span>
            {result.failed > 0 && (
              <span className="failed">
                <b>{result.failed}</b> failed
              </span>
            )}
          </div>

          <table className="fleet batch">
            <thead>
              <tr>
                <th>Strategy</th>
                <th style={{ textAlign: 'right' }}>Sharpe</th>
                <th style={{ textAlign: 'right' }}>Return</th>
                <th style={{ textAlign: 'right' }}>Fills</th>
              </tr>
            </thead>
            <tbody>
              {result.results.map((r) => (
                <tr key={r.strategy}>
                  <td>
                    <span className="nm">{r.strategy}</span>
                    {r.cached && <span className="tag cached">cached</span>}
                  </td>
                  {r.error ? (
                    <td colSpan={3} className="errcell" title={r.error}>
                      {r.error}
                    </td>
                  ) : (
                    <>
                      <td className="numcell">{r.result?.sharpe.toFixed(2)}</td>
                      <td className="numcell">
                        {((r.result?.total_return ?? 0) * 100).toFixed(1)}%
                      </td>
                      <td className="numcell">{r.result?.fills}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>

          <div className="note warn" style={{ marginTop: 12 }}>
            <strong>{result.unrecorded}</strong> configuration
            {result.unrecorded === 1 ? '' : 's'} evaluated, {result.spent_trials} trials spent.{' '}
            {result.note}
          </div>
        </div>
      )}
    </div>
  );
}
