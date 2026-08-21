'use client';

/**
 * Authoring.
 *
 * Two ways in: compose from the feature library, or write a strategy in the
 * sandbox. Both end at the same `/api/validate`, so a composed strategy and a
 * written one are the same object by the time anything runs them — which is the
 * whole point of the one-Strategy-interface rule.
 */

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Library, Provider, StrategyInput } from '@/lib/api';

export function BuildTab({ onRefresh }: { onRefresh: () => void }) {
  const [library, setLibrary] = useState<Library | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [mode, setMode] = useState<'composed' | 'code'>('composed');
  const [feature, setFeature] = useState('');
  const [topN, setTopN] = useState(20);
  const [rebalance, setRebalance] = useState(21);
  const [minTurnover, setMinTurnover] = useState(0);
  const [source, setSource] = useState('');
  const [describe, setDescribe] = useState('');
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .library()
      .then((response) => {
        setLibrary(response);
        setFeature((current) => current || response.features[0]?.name || '');
        setSource((current) => current || response.example_code);
      })
      .catch(() => setError('Cannot read the feature library.'));
    api
      .providers()
      .then((response) => setProviders(response.providers ?? []))
      .catch(() => setProviders([]));
  }, []);

  const input = useCallback(
    (): StrategyInput => ({
      mode,
      source,
      feature,
      top_n: topN,
      rebalance,
      min_turnover: minTurnover,
    }),
    [mode, source, feature, topN, rebalance, minTurnover]
  );

  const validate = useCallback(async () => {
    setBusy(true);
    setError('');
    setStatus('');
    try {
      const response = await api.validate(input());
      if (response.ok) setStatus(`Valid: ${response.label}`);
      else setError(response.error ?? 'rejected');
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  }, [input]);

  const draft = useCallback(async () => {
    setBusy(true);
    setError('');
    setStatus('');
    try {
      const ready = providers.find((p) => p.ready);
      const response = await api.draft(describe, mode, ready?.name ?? null);
      if (!response.ok) {
        setError(response.error ?? 'the model could not draft that');
      } else {
        if (response.source) setSource(response.source);
        setStatus(response.explanation ?? 'drafted');
      }
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  }, [describe, mode, providers]);

  const run = useCallback(async () => {
    setBusy(true);
    setError('');
    setStatus('starting…');
    try {
      const started = await api.backtest({ ...input(), days: 800, tier: 'B', starting_cash: 1_000_000 });
      if (!started.ok || !started.job) throw new Error(started.error ?? 'could not start');
      for (;;) {
        await new Promise((resolve) => setTimeout(resolve, 700));
        const job = await api.job(started.job);
        setStatus(job.message || job.status);
        if (job.status === 'done') {
          setStatus(
            `Sharpe ${job.result.sharpe.toFixed(2)} against a bar of ${job.result.noise_bar.toFixed(2)} · ` +
              `${job.result.fills} fills · ${(job.result.total_return * 100).toFixed(1)}% total`
          );
          onRefresh();
          return;
        }
        if (job.status === 'failed') throw new Error(job.error || 'the run failed');
      }
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
      setStatus('');
    } finally {
      setBusy(false);
    }
  }, [input, onRefresh]);

  const usable = providers.filter((p) => p.ready);

  return (
    <>
      <section className="thero">
        <div>
          <div className="theyebrow">Build</div>
          <div className="thnum">
            <b>{library?.features.length ?? '—'}</b>
            <span className="unit">features available</span>
          </div>
          <p className="thsub">
            Compose from the library or write it directly. Both routes end at the same
            validator, so a composed strategy and a written one are the same object by the
            time anything runs them.
          </p>
        </div>
      </section>

      <div className="ttools">
        <button className="tchip" type="button" aria-pressed={mode === 'composed'} onClick={() => setMode('composed')}>
          Compose
        </button>
        <button className="tchip" type="button" aria-pressed={mode === 'code'} onClick={() => setMode('code')}>
          Write code
        </button>
      </div>

      <div className="tgrid">
        <div className="tpanel">
          <h3>{mode === 'composed' ? 'Parameters' : 'Source'}</h3>
          {mode === 'composed' ? (
            <div className="tform">
              <label>
                Feature
                <select value={feature} onChange={(event) => setFeature(event.target.value)}>
                  {library?.features.map((item) => (
                    <option key={item.name} value={item.name}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Hold top N
                <input type="number" min={1} max={200} value={topN} onChange={(e) => setTopN(Number(e.target.value))} />
              </label>
              <label>
                Rebalance every (days)
                <input type="number" min={1} max={250} value={rebalance} onChange={(e) => setRebalance(Number(e.target.value))} />
              </label>
              <label>
                Minimum turnover
                <input type="number" min={0} max={1} step={0.01} value={minTurnover} onChange={(e) => setMinTurnover(Number(e.target.value))} />
              </label>
              <p className="tfine">
                {library?.features.find((f) => f.name === feature)?.description}
              </p>
            </div>
          ) : (
            <>
              <textarea
                className="tcode"
                value={source}
                onChange={(event) => setSource(event.target.value)}
                spellCheck={false}
                aria-label="Strategy source"
              />
              <p className="tfine">
                Runs in a sandbox: {library?.sandbox_rules.join(' · ')}
              </p>
            </>
          )}

          <div className="tacts" style={{ marginTop: 16 }}>
            <button className="tbtn" type="button" disabled={busy} onClick={validate}>
              Validate
            </button>
            <button className="tbtn go" type="button" disabled={busy} onClick={run}>
              {busy ? 'Working…' : 'Backtest'}
            </button>
          </div>
        </div>

        <div className="tpanel">
          <h3>Describe it instead</h3>
          <textarea
            className="tcode"
            style={{ minHeight: 96 }}
            placeholder="e.g. hold the 20 stocks with the strongest 12-month return, skipping the last month, rebalanced monthly"
            value={describe}
            onChange={(event) => setDescribe(event.target.value)}
            aria-label="Describe a strategy"
          />
          <div className="tacts" style={{ marginTop: 12 }}>
            <button
              className="tbtn"
              type="button"
              disabled={busy || !describe.trim() || usable.length === 0}
              onClick={draft}
              title={usable.length === 0 ? 'No model provider is configured.' : undefined}
            >
              Draft
            </button>
            <span className="tfine">
              {usable.length > 0
                ? `via ${usable[0].name} (${usable[0].model})`
                : 'no provider ready — set a key, or compose by hand'}
            </span>
          </div>

          {status && <div className="trunning" style={{ marginTop: 16 }}>{status}</div>}
          {error && (
            <div className="tnote bad" style={{ marginTop: 16 }}>
              <span className="mk">▲</span>
              <div>{error}</div>
            </div>
          )}

        </div>
      </div>
    </>
  );
}
