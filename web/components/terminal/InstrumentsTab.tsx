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
import type { InstrumentList } from '@/lib/api';

const LABEL: Record<string, string> = {
  equity: 'Equities',
  crypto: 'Crypto',
  mutual_fund: 'Mutual funds',
};

export function InstrumentsTab() {
  const [query, setQuery] = useState('');
  const [assetClass, setAssetClass] = useState('');
  const [batch, setBatch] = useState('');
  const [list, setList] = useState<InstrumentList | null>(null);
  const [sync, setSync] = useState<{ state: string; note: string }>({ state: 'idle', note: '' });
  const polling = useRef<number | null>(null);

  // Stop polling when the tab unmounts, or a closed page keeps asking the API
  // about a job nobody is watching.
  useEffect(() => () => {
    if (polling.current) window.clearInterval(polling.current);
  }, []);

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
        if (job.status === 'done') {
          api.instruments(query, assetClass === 'equity' ? batch : '', assetClass, 120)
            .then(setList)
            .catch(() => undefined);
        }
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
  }, [query, batch, assetClass]);

  const classes = list?.asset_classes ?? [];

  return (
    <>
      <section className="thero">
        <div>
          <div className="theyebrow">Instruments</div>
          <div className="thnum">
            <b>{list ? list.instruments.length : '—'}</b>
            <span className="unit">shown</span>
          </div>
          <p className="thsub">
            Search across equities, crypto and mutual funds. Batches are
            liquidity-ranked from our own turnover history rather than index membership,
            because a published constituent list only exists as it stands today.
          </p>
        </div>
        <div className="tsyncbox">
          <button
            className="tbtn"
            type="button"
            onClick={startSync}
            disabled={sync.state === 'running'}
          >
            {sync.state === 'running' ? 'Syncing…' : 'Sync all data'}
          </button>
          <div className="tfine" data-state={sync.state}>
            {sync.state === 'idle'
              ? 'Mirrors the landing zone to B2 and recounts it. Safe to re-run — already-uploaded files are skipped.'
              : sync.note}
          </div>
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
            {LABEL[name] ?? name}
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
