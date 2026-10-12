'use client';

/**
 * Every instrument that has data, across every asset class that has any.
 *
 * This used to show equities and nothing else, which quietly meant 20 landed
 * crypto pairs and 14,280 mutual fund schemes existed on disk and could not be
 * seen or selected. An asset class with data and no way to reach it is the same
 * defect as one offered without data, pointing the other way.
 */

import { Fragment, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { ASSET_CLASSES, assetClassLabel } from '@/lib/assetClasses';
import type { DataCoverage, InstrumentList } from '@/lib/api';

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

  const [sync, setSync] = useState<{ state: string; note: string }>({
    state: 'idle',
    note: '',
  });
  const polling = useRef<number | null>(null);

  // Stop polling when the tab unmounts, or a closed page keeps asking the API
  // about a job nobody is watching.
  useEffect(
    () => () => {
      if (polling.current) window.clearInterval(polling.current);
    },
    [],
  );

  type FeedStep = { name: string; ok: boolean; detail: string };
  // The source list comes from the code that fetches them. Written by hand it
  // promised FX while the step list did not include it — the same drift as the
  // three copies of the asset-class list.
  const [plan, setPlan] = useState<{
    sources: string[];
    excluded: string[];
  } | null>(null);
  useEffect(() => {
    api
      .feedPlan()
      .then((p) => setPlan(p.ok ? { sources: p.sources, excluded: p.excluded } : null))
      .catch(() => undefined);
  }, []);

  const [steps, setSteps] = useState<FeedStep[]>([]);

  // What is held and what is missing, per dataset. Re-read after every run so
  // "did the click work?" is answered by the table, not by trusting the log.
  const [coverage, setCoverage] = useState<DataCoverage | null>(null);
  useEffect(() => {
    api
      .coverage()
      .then(setCoverage)
      .catch(() => setCoverage(null));
  }, [reloadAt]);
  const busy = coverage?.busy ?? null;

  /**
   * Fetch every source, then mirror.
   *
   * Polls the same job machinery the mirror uses, and shows the per-source
   * outcome rather than one verdict: a run where five sources updated and two
   * failed is not a success and is not a failure, and collapsing it to either
   * word loses the only part the operator can act on.
   */
  // Which dataset or group a running update was started for, so its row shows
  // the progress rather than the whole page reading "Working…".
  const [target, setTarget] = useState<{
    label: string;
    steps: string[];
  } | null>(null);

  async function startFeed(only: string[] = [], label = '') {
    setSteps([]);
    setPrunePlan(null);
    setTarget(only.length ? { label, steps: only } : null);
    setSync({
      state: 'running',
      note: only.length ? `updating ${label}…` : 'starting…',
    });
    // One dataset skips the mirror: it relists the bucket and takes minutes.
    // Mirror to cloud uploads it afterwards; Update all data mirrors itself.
    const started = await api
      .refreshFeed(only, only.length === 0)
      .catch((e) => ({ ok: false, error: String(e) }));
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
          | {
              summary?: string;
              uploaded?: number;
              steps?: FeedStep[];
              sync_error?: string;
              mirrored?: boolean;
            }
          | undefined;
        setSteps(result?.steps ?? []);
        setTarget(null);
        const uploaded = result?.mirrored
          ? ` · ${result?.uploaded ?? 0} object${result?.uploaded === 1 ? '' : 's'} uploaded`
          : ' · not mirrored yet — Mirror to cloud uploads it';
        setSync({
          state: job.status,
          note:
            job.status === 'done'
              ? `${only.length ? `${label}: ` : ''}${result?.summary ?? 'finished'}${uploaded}${
                  result?.sync_error ? ` · mirror failed: ${result.sync_error}` : ''
                }`
              : job.error || 'failed',
        });
        if (job.status === 'done') setReloadAt(Date.now());
      }
    }, 3000);
  }

  /**
   * Delete local copies B2 already holds, in two clicks. The first is a dry run
   * that says how many files and how much disk; only the confirm deletes.
   */
  const [prunePlan, setPrunePlan] = useState<{
    files: number;
    gb: number;
  } | null>(null);

  async function startPrune(dryRun: boolean) {
    setSteps([]);
    setSync({
      state: 'running',
      note: dryRun ? 'checking what B2 holds…' : 'deleting…',
    });
    const started = await api.pruneData(dryRun).catch((e) => ({ ok: false, error: String(e) }));
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
        const result = job.result as { files?: number; gb?: number } | undefined;
        setSync({
          state: job.status,
          note: job.message || job.error || job.status,
        });
        if (job.status === 'done' && dryRun && (result?.files ?? 0) > 0) {
          setPrunePlan({ files: result?.files ?? 0, gb: result?.gb ?? 0 });
        } else {
          setPrunePlan(null);
        }
        if (job.status === 'done' && !dryRun) setReloadAt(Date.now());
      } else {
        setSync({ state: 'running', note: job.message || 'working…' });
      }
    }, 2000);
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
            liquidity-ranked from our own turnover history rather than index membership, because a
            published constituent list only exists as it stands today.
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
            onClick={() => startFeed()}
            disabled={sync.state === 'running' || !!busy}
          >
            {sync.state === 'running' ? 'Working…' : 'Update all data'}
          </button>
          <button
            className="tbtn ghost-line"
            type="button"
            onClick={startSync}
            disabled={sync.state === 'running' || !!busy}
            title="Upload to B2 every landed file the cloud does not hold yet. Fetches nothing."
          >
            Mirror to cloud
          </button>
          {prunePlan ? (
            <button
              className="tbtn danger"
              type="button"
              onClick={() => startPrune(false)}
              disabled={sync.state === 'running' || !!busy}
            >
              {`Delete ${prunePlan.files.toLocaleString()} files (${prunePlan.gb.toFixed(2)} GB)`}
            </button>
          ) : (
            <button
              className="tbtn ghost-line"
              type="button"
              onClick={() => startPrune(true)}
              disabled={sync.state === 'running' || !!busy}
              title="Delete local copies that B2 holds at the same size. Asks before deleting."
            >
              Delete local copies
            </button>
          )}
          {prunePlan && (
            <button
              className="tbtn ghost-line"
              type="button"
              onClick={() => {
                setPrunePlan(null);
                setSync({ state: 'idle', note: '' });
              }}
            >
              Cancel
            </button>
          )}
          <div className="tfine" data-state={sync.state}>
            {busy && sync.state !== 'running'
              ? `Another data run is going (${busy.what ?? 'make daily'}, since ${busy.since ?? '?'}). Wait for it to finish.`
              : sync.state === 'idle'
                ? plan
                  ? `Update downloads only what is missing from ${plan.sources.length} sources, rebuilds every table and the paper books, then uploads what the cloud lacks. Mirror only uploads. Delete removes local files B2 already holds, after asking.`
                  : 'Downloads only what is missing, rebuilds every table, then uploads what the cloud lacks.'
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

      {coverage?.ok && (
        <section className="tpanel coverage">
          <div className="coverage-head">
            <div>
              <b>Data coverage</b>
              <div className="tfine">
                Each dataset&apos;s last day against the day it should reach. Update one row, one group,
                or everything above.
              </div>
            </div>
            <div className="cov-badges">
              {(['ok', 'behind', 'stale', 'missing'] as const)
                .filter((k) => coverage.summary[k])
                .map((k) => (
                  <span key={k} className="cov-status" data-status={k}>
                    {coverage.summary[k]} {k === 'ok' ? 'up to date' : k}
                  </span>
                ))}
            </div>
            <button
              className="tbtn ghost-line"
              type="button"
              onClick={() => setReloadAt(Date.now())}
              title={`checked ${coverage.checked_at.slice(11, 16)} UTC`}
            >
              Re-check
            </button>
          </div>
          <div className="tscroll">
            <table className="ttable cov-table">
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th>Last day</th>
                  <th>Should reach</th>
                  <th>Status</th>
                  <th className="r" aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {coverage.rows.map((row, i) => {
                  const first = i === 0 || coverage.rows[i - 1].group !== row.group;
                  const groupRows = coverage.rows.filter((r) => r.group === row.group);
                  const groupSteps = Array.from(new Set(groupRows.flatMap((r) => r.steps)));
                  const working =
                    sync.state === 'running' &&
                    !!target &&
                    row.steps.length > 0 &&
                    row.steps.every((step) => target.steps.includes(step));
                  const idle = sync.state !== 'running' && !busy;
                  return (
                    <Fragment key={`${row.group}-${row.name}`}>
                      {first && (
                        <tr className="coverage-group">
                          <td colSpan={4}>{row.group}</td>
                          <td className="r">
                            {groupSteps.length > 0 && (
                              <button
                                className="tbtn ghost-line small"
                                type="button"
                                disabled={!idle}
                                onClick={() => startFeed(groupSteps, row.group)}
                              >
                                Update group
                              </button>
                            )}
                          </td>
                        </tr>
                      )}
                      <tr data-working={working || undefined}>
                        <td>
                          <b>{row.name}</b>
                          {row.detail && <div className="tfine">{row.detail}</div>}
                        </td>
                        <td>{row.last || <span className="tdim">—</span>}</td>
                        <td>{row.expected || <span className="tdim">—</span>}</td>
                        <td>
                          <span
                            className="cov-status"
                            data-status={working ? 'working' : row.status}
                          >
                            {working
                              ? 'updating…'
                              : row.status === 'ok'
                                ? 'up to date'
                                : row.status === 'behind' || row.status === 'stale'
                                  ? `${row.behind || ''} behind`.trim()
                                  : row.status}
                          </span>
                        </td>
                        <td className="r">
                          {row.steps.length > 0 ? (
                            <button
                              className="tbtn ghost-line small"
                              type="button"
                              disabled={!idle}
                              title={`Runs: ${row.steps.join(' → ')}`}
                              onClick={() => startFeed(row.steps, row.name)}
                            >
                              Update
                            </button>
                          ) : (
                            row.status !== 'ok' &&
                            row.status !== 'info' && <span className="tfine">{row.fix}</span>
                          )}
                        </td>
                      </tr>
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

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
          <button
            className="tchip"
            type="button"
            aria-pressed={batch === ''}
            onClick={() => setBatch('')}
          >
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
                  <td className="r">
                    {instrument.has_daily ? '✓' : <span className="tdim">—</span>}
                  </td>
                  <td className="r">
                    {instrument.has_minute ? '✓' : <span className="tdim">—</span>}
                  </td>
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
