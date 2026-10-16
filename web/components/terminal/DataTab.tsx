'use client';

/**
 * What data exists, counted rather than claimed.
 *
 * Every figure here is a read: the panel numbers come from the panel, the
 * landing numbers from walking the directories, the remote list from a LIST
 * against the bucket. A source that is missing says missing — it never reports
 * the size it was supposed to be.
 */

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { CloudStatus, DataStatus } from '@/lib/api';

const GB = 1024 ** 3;
const MB = 1024 ** 2;

function size(bytes: number | undefined) {
  if (!bytes) return '—';
  return bytes >= GB ? `${(bytes / GB).toFixed(2)} GB` : `${(bytes / MB).toFixed(0)} MB`;
}

export function DataTab({ workspace }: { workspace: string }) {
  const [data, setData] = useState<DataStatus | null>(null);
  const [cloud, setCloud] = useState<CloudStatus | null>(null);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.data().then(setData).catch((e) => setError(String(e)));
    api.cloudStatus(workspace).then(setCloud).catch(() => setCloud(null));
  }, [workspace]);

  useEffect(load, [load]);

  const mirror = useCallback(async () => {
    setBusy(true);
    setNote('');
    try {
      const outcome = await api.mirror(workspace);
      setNote(
        outcome.ok
          ? `${outcome.pushed} pushed, ${outcome.pulled} pulled, ${outcome.merged_rows} rows merged in`
          : `failed: ${outcome.failed.join('; ')}`
      );
      load();
    } catch (e) {
      setNote(String(e));
    } finally {
      setBusy(false);
    }
  }, [workspace, load]);

  return (
    <>
      <section className="thero">
        <div>
          <div className="theyebrow">Panel on disk</div>
          <div className="thnum">
            <b>{data ? data.panel.rows.toLocaleString('en-IN') : '—'}</b>
            <span className="unit">rows</span>
          </div>
          <p className="thsub">
            {data?.panel.first && data.panel.last
              ? `${data.panel.symbols?.toLocaleString('en-IN')} symbols across ${data.panel.days?.toLocaleString('en-IN')} trading days, ${data.panel.first} to ${data.panel.last}. Counted from the panel itself, not from a configured expectation.`
              : 'Reading the panel…'}
          </p>
        </div>
        <div className="thstats">
          <div className="thstat">
            <span>Thinnest symbol</span>
            <b>{data?.panel.thinnest ?? '—'}</b>
          </div>
          <div className="thstat">
            <span>Fattest</span>
            <b>{data?.panel.fattest ?? '—'}</b>
          </div>
        </div>
      </section>

      {error && <div className="tnote bad">{error}</div>}

      <div className="tgrid">
        <div className="tpanel">
          <h3>Landing sources</h3>
          <table className="ttable">
            <thead>
              <tr>
                <th>Source</th>
                <th className="r">Files</th>
                <th className="r">Size</th>
                <th className="r">Newest</th>
              </tr>
            </thead>
            <tbody>
              {data?.sources.map((source) => (
                <tr key={source.name}>
                  <td>
                    <b>{source.name}</b>
                  </td>
                  <td className="r">
                    {source.present ? source.files.toLocaleString('en-IN') : <span className="tdim">missing</span>}
                  </td>
                  <td className="r">{size(source.bytes)}</td>
                  <td className="r">{source.newest ?? <span className="tdim">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="tpanel">
          <h3>Universes</h3>
          <table className="ttable">
            <thead>
              <tr>
                <th>Batch</th>
                <th className="r">Symbols</th>
              </tr>
            </thead>
            <tbody>
              {data?.universes.map((universe) => (
                <tr key={universe.name}>
                  <td>
                    <b>{universe.name}</b>
                  </td>
                  <td className="r">
                    {universe.error ? (
                      <span className="tdim">{universe.error}</span>
                    ) : (
                      universe.symbols.toLocaleString('en-IN')
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data && <p className="tfine">{data.universe_caveat}</p>}
        </div>
      </div>

      <div className="tpanel">
        <h3>Results in the cloud</h3>
        {cloud ? (
          <>
            <div className="tfacts">
              <div className="tfact">
                <span>Bucket</span>
                <b>{cloud.bucket || <span className="tdim">—</span>}</b>
              </div>
              <div className="tfact">
                <span>Prefix</span>
                <b style={{ fontSize: 13 }}>{cloud.prefix}</b>
              </div>
              <div className="tfact">
                <span>Local files</span>
                <b>{cloud.local_files.length}</b>
              </div>
              <div className="tfact">
                <span>In bucket</span>
                <b className={cloud.reachable ? '' : 'dim'}>
                  {cloud.reachable ? cloud.remote_files.length : '—'}
                </b>
                {cloud.listed_at && (
                  <span className="tfine">
                    as of {new Date(cloud.listed_at).toLocaleTimeString()}
                  </span>
                )}
              </div>
            </div>
            {!cloud.configured && (
              <p className="tfine" style={{ marginTop: 16 }}>
                Not configured: {cloud.reason}
              </p>
            )}
            <div className="tacts" style={{ marginTop: 16 }}>
              <button
                className="tbtn go"
                type="button"
                disabled={busy || !cloud.configured}
                onClick={mirror}
              >
                {busy ? 'Mirroring…' : 'Pull, merge, then push'}
              </button>
              <button
                className="tbtn"
                type="button"
                disabled={busy || !cloud.configured}
                onClick={() =>
                  api.cloudStatus(workspace, true).then(setCloud).catch(() => setCloud(null))
                }
              >
                List the bucket again
              </button>
              {note && <span className="tfine">{note}</span>}
            </div>
            <p className="tfine" style={{ marginTop: 12 }}>
              Results mirror automatically after every backtest. This button forces a pass
              — it pulls the bucket&rsquo;s copy and merges before pushing, so a run made
              on another machine is never overwritten (ADR-042).
            </p>
          </>
        ) : (
          <div className="tempty">Checking the bucket…</div>
        )}
      </div>
    </>
  );
}
