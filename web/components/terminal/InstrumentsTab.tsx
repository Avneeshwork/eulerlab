'use client';

/**
 * Every instrument that has data, across every asset class that has any.
 *
 * This used to show equities and nothing else, which quietly meant 20 landed
 * crypto pairs and 14,280 mutual fund schemes existed on disk and could not be
 * seen or selected. An asset class with data and no way to reach it is the same
 * defect as one offered without data, pointing the other way.
 */

import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { ASSET_CLASSES, assetClassLabel } from '@/lib/assetClasses';
import type { InstrumentList } from '@/lib/api';

// Labels come from `lib/assetClasses`, the single source three components used
// to each keep a private copy of.

export function InstrumentsTab() {
  const [query, setQuery] = useState('');
  const [assetClass, setAssetClass] = useState('');
  const [batch, setBatch] = useState('');
  const [list, setList] = useState<InstrumentList | null>(null);
  // A finished feed or sync bumps this rather than re-reading the list itself.
  // The two pollers used to call `api.instruments` directly, which captured the
  // filters as they stood when the poller was created — start a refresh on "all
  // classes", switch to FX while it runs, and the list came back unfiltered
  // under a highlighted FX pill.
  const [reloadAt, setReloadAt] = useState(0);

  const [sync, setSync] = useState<{ state: string; note: string }>({ state: 'idle', note: '' });
  const polling = useRef<number | null>(null);

  // Stop polling when the tab unmounts, or a closed page keeps asking the API
  // about a job nobody is watching.
  useEffect(() => () => {
    if (polling.current) window.clearInterval(polling.current);
  }, []);

  type FeedStep = { name: string; ok: boolean; detail: string };
  // The source list comes from the code that fetches them. Written by hand it
  // promised FX while the step list did not include it — the same drift as the
  // three copies of the asset-class list.
  const [plan, setPlan] = useState<{ sources: string[]; excluded: string[] } | null>(null);
  useEffect(() => {
    api
      .feedPlan()
      .then((p) => setPlan(p.ok ? { sources: p.sources, excluded: p.excluded } : null))
      .catch(() => undefined);
  }, []);

  const [steps, setSteps] = useState<FeedStep[]>([]);

  /**
   * Fetch every source, then mirror.
   *
   * Polls the same job machinery the mirror uses, and shows the per-source
   * outcome rather than one verdict: a run where five sources updated and two
   * failed is not a success and is not a failure, and collapsing it to either
   * word loses the only part the operator can act on.
   */
  async function startFeed() {
    setSteps([]);
    setSync({ state: 'running', note: 'starting…' });
    const started = await api.refreshFeed().catch((e) => ({ ok: false, error: String(e) }));
    if (!started.ok || !('job' in started) || !started.job) {
      setSync({ state: 'failed', note: started.error ?? 'could not start' });
      return;
    }
    const id = started.job;
    polling.current = window.setInterval(async () => {
      const job = await api.job(id).catch(() => null);
      if (!job) return;
      setSync((prev) => ({ state: 'running', note: job.message || prev.note }));
      if (job.status === 'done' || job.status === 'failed') {
        if (polling.current) window.clearInterval(polling.current);
        const result = job.result as
          | { summary?: string; uploaded?: number; steps?: FeedStep[]; sync_error?: string }
          | undefined;
        setSteps(result?.steps ?? []);
        setSync({
          state: job.status,
          note:
            job.status === 'done'
              ? `${result?.summary ?? 'finished'} · ${result?.uploaded ?? 0} object${
                  result?.uploaded === 1 ? '' : 's'
                } uploaded${result?.sync_error ? ` · mirror failed: ${result.sync_error}` : ''}`
              : job.error || 'failed',
        });
        if (job.status === 'done') setReloadAt(Date.now());
      }
    }, 3000);
  }

  async function startSync() {
    setSync({ state: 'running', note: 'starting…' });
    const started = await api.syncData().catch((e) => ({ ok: false, error: String(e) }));
    if (!started.ok || !('job' in started) || !started.job) {
      setSync({ state: 'failed', note: started.error ?? 'could not start' });
      return;
    }
    const id = started.job;
    polling.current = window.setInterval(async () => {
      const job = await api.job(id).catch(() => null);
      if (!job) return;
      if (job.status === 'done' || job.status === 'failed') {
        if (polling.current) window.clearInterval(polling.current);
        const uploaded = (job.result as { uploaded?: number } | undefined)?.uploaded;
        setSync({
          state: job.status,
          note:
            job.status === 'done'
              ? `${uploaded ?? 0} object${uploaded === 1 ? '' : 's'} uploaded in ${job.elapsed}s`
              : job.error || 'failed',
        });
        // A finished sync changes what is landed, so the list is re-read
        // rather than left showing the counts from before it ran.
        if (job.status === 'done') setReloadAt(Date.now());
      } else {
        setSync({ state: 'running', note: job.message || 'syncing…' });
      }
    }, 2000);
  }

  useEffect(() => {
    const timer = setTimeout(() => {
      api
        .instruments(query, assetClass === 'equity' ? batch : '', assetClass, 120)
        .then(setList)
        .catch(() => setList(null));
    }, 180);
    return () => clearTimeout(timer);
  }, [query, batch, assetClass, reloadAt]);

  const classes = list?.asset_classes ?? [];

  return (
    <>
      <section className="thero">
        <div>
          <div className="thnum">
            <b>{list ? list.instruments.length : '—'}</b>
            <span className="unit">shown</span>
          </div>
          {/* Named from the shared list rather than written out, because this
              sentence said "equities, crypto and mutual funds" for as long as
              US and FX were landed, panelled and invisible. Prose that
              enumerates a list is a fourth copy of that list. */}
          <p className="thsub">
            Search across {ASSET_CLASSES.map((c) => c.label).join(', ')}. NSE batches are
            liquidity-ranked from our own turnover history rather than index membership,
            because a published constituent list only exists as it stands today.
          </p>
        </div>
        <div className="tsyncbox">
          {/* Two buttons, because they do different things and the difference
              matters. "Update" fetches from every source and then mirrors;
              "Mirror only" uploads whatever is already on disk — which can
              push a stale landing zone to the cloud and report success. The
              fetch is the one an operator almost always wants, so it leads. */}
          <button
            className="tbtn"
            type="button"
            onClick={startFeed}
            disabled={sync.state === 'running'}
          >
            {sync.state === 'running' ? 'Working…' : 'Update daily feed'}
          </button>
          <button
            className="tbtn ghost-line"
            type="button"
            onClick={startSync}
            disabled={sync.state === 'running'}
          >
            Mirror only
          </button>
          <div className="tfine" data-state={sync.state}>
            {sync.state === 'idle'
              ? plan
                ? `Fetches ${plan.sources.join(', ')} — then mirrors to B2. ${plan.excluded.join(
                    '; ',
                  )}. Nothing local is deleted.`
                : 'Fetches every source, then mirrors to B2. Nothing local is deleted.'
              : sync.note}
          </div>
          {steps.length > 0 && (
            <ul className="feedsteps">
              {steps.map((step) => (
                <li key={step.name} data-ok={step.ok}>
                  <span>{step.name}</span>
                  <span className="tfine">{step.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <div className="ttools">
        <input
          className="tsearch"
          placeholder="Search by symbol, fund name, AMC or ISIN…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Search instruments"
        />
        <button
          className="tchip"
          type="button"
          aria-pressed={assetClass === ''}
          onClick={() => {
            setAssetClass('');
            setBatch('');
          }}
        >
          All classes
        </button>
        {classes.map((name) => (
          <button
            key={name}
            className="tchip"
            type="button"
            aria-pressed={assetClass === name}
            onClick={() => {
              setAssetClass(assetClass === name ? '' : name);
              setBatch('');
            }}
          >
            {assetClassLabel(name)}
          </button>
        ))}
      </div>

      {assetClass === 'equity' && (
        <div className="ttools">
          <button className="tchip" type="button" aria-pressed={batch === ''} onClick={() => setBatch('')}>
            All liquid
          </button>
          {(list?.batches ?? []).map((name) => (
            <button
              key={name}
              className="tchip"
              type="button"
              aria-pressed={batch === name}
              onClick={() => setBatch(batch === name ? '' : name)}
            >
              {name}
            </button>
          ))}
        </div>
      )}

      {list && !list.ok && <div className="tnote bad">{list.error}</div>}

      <div className="tpanel">
        <div className="tscroll" style={{ maxHeight: '58vh' }}>
          <table className="ttable">
            <thead>
              <tr>
                <th>Instrument</th>
                <th>Class</th>
                <th className="r">Rank</th>
                <th className="r">Daily</th>
                <th className="r">Minute</th>
              </tr>
            </thead>
            <tbody>
              {list?.instruments.map((instrument) => (
                <tr key={`${instrument.asset_class}-${instrument.symbol}`}>
                  <td>
                    <b>{instrument.name || instrument.symbol}</b>
                    {(instrument.name || instrument.detail) && (
                      <div className="tfine">
                        {instrument.name ? instrument.symbol : ''}
                        {instrument.name && instrument.detail ? ' · ' : ''}
                        {instrument.detail}
                      </div>
                    )}
                  </td>
                  <td>
                    <span className="ttag">{instrument.asset_class}</span>
                  </td>
                  <td className="r">{instrument.rank || <span className="tdim">—</span>}</td>
                  <td className="r">{instrument.has_daily ? '✓' : <span className="tdim">—</span>}</td>
                  <td className="r">{instrument.has_minute ? '✓' : <span className="tdim">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {list && list.instruments.length === 0 && (
          <div className="tempty">Nothing matches that search.</div>
        )}
      </div>

    </>
  );
}
