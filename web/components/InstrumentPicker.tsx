'use client';

/**
 * Instrument search and batches.
 *
 * Two things this must not do. It must not let an instrument with no minute
 * history be silently selected into a minute-bar backtest — so availability is
 * on the row. And it must not let a chip labelled `nifty50` be read as index
 * membership, which is what everyone will assume — so the caveat comes from
 * the API alongside the data and is shown wherever the batch is named.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Capability, Instrument } from '@/lib/api';

export function InstrumentPicker({
  batch,
  onBatch,
  onCount,
}: {
  batch: string;
  onBatch: (b: string) => void;
  onCount: (n: number) => void;
}) {
  const [query, setQuery] = useState('');
  const [rows, setRows] = useState<Instrument[]>([]);
  const [batches, setBatches] = useState<string[]>([]);
  const [caveat, setCaveat] = useState('');
  const [matrix, setMatrix] = useState<Capability[]>([]);
  const [problem, setProblem] = useState('');

  useEffect(() => {
    api.capabilities().then((c) => setMatrix(c.matrix)).catch(() => undefined);
  }, []);

  useEffect(() => {
    let live = true;
    const handle = setTimeout(() => {
      api
        .instruments(query, batch)
        .then((r) => {
          if (!live) return;
          if (!r.ok) {
            setProblem(r.error ?? 'could not read instruments');
            setRows([]);
            return;
          }
          setProblem('');
          setRows(r.instruments);
          setBatches(r.batches);
          setCaveat(r.batch_caveat);
          onCount(r.instruments.length);
        })
        .catch(() => setProblem('Cannot reach the API.'));
    }, 250);
    return () => {
      live = false;
      clearTimeout(handle);
    };
  }, [query, batch, onCount]);

  return (
    <div className="card">
      <h2>Instruments</h2>
      <p className="sub">Search, or pick a batch. Availability is per instrument.</p>

      <div className="tools">
        <input
          className="tool-search"
          placeholder="Search symbol…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search instruments"
        />
        {batches.map((b) => (
          <button
            key={b}
            className={`chip${batch === b ? ' on' : ''}`}
            onClick={() => onBatch(batch === b ? '' : b)}
            aria-pressed={batch === b}
          >
            {b}
          </button>
        ))}
      </div>

      {problem && <div className="note bad">{problem}</div>}

      {batch && caveat && (
        <div className="note warn" style={{ marginBottom: 12 }}>
          <strong>{batch}</strong> is not index membership. {caveat}
        </div>
      )}

      <div className="fleet-scroll">
        <table className="fleet inst">
          <thead>
            <tr>
              <th>Instrument</th>
              <th>Class</th>
              <th>Data available</th>
              <th style={{ textAlign: 'right' }}>Liquidity rank</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((i) => (
              <tr key={`${i.symbol}-${i.rank}`}>
                <td>
                  <span className="nm">{i.symbol}</span>
                </td>
                <td>
                  <span className="tag">{i.asset_class}</span>
                </td>
                <td className="avail">
                  <span className={i.has_minute ? 'y' : 'n'}>1m {i.has_minute ? '✓' : '—'}</span>
                  <span className={i.has_daily ? 'y' : 'n'}>1d {i.has_daily ? '✓' : '—'}</span>
                </td>
                <td className="numcell">{i.rank}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rows.length === 0 && !problem && (
        <p className="muted" style={{ marginTop: 12 }}>
          No instrument matches that search.
        </p>
      )}

      <h3 className="capsHead">What the data can actually serve</h3>
      <p className="sub">
        The interface will accept any combination. These are the ones with data behind
        them — the rest report unsupported rather than returning an empty result.
      </p>
      <div className="fleet-scroll">
        <table className="fleet caps">
          <tbody>
            {matrix.map((c) => (
              <tr key={`${c.asset_class}-${c.timeframe}`}>
                <td>
                  <span className="tag">{c.asset_class}</span>{' '}
                  <span className="tag">{c.timeframe}</span>
                </td>
                <td className={c.supported ? 'capy' : 'capn'}>
                  {c.supported ? 'supported' : 'unsupported'}
                </td>
                <td className="capdetail">{c.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
