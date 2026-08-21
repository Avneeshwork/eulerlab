'use client';

/**
 * Instruments and batches, plus what each (asset class, timeframe) pair
 * actually has data behind it.
 *
 * The capability matrix is here rather than hidden because an unsupported
 * combination that runs and returns nothing reads as "no trades found" when
 * the truth is "never measured" (ADR-037). Better to refuse it visibly.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Capability, InstrumentList } from '@/lib/api';

export function InstrumentsTab() {
  const [query, setQuery] = useState('');
  const [batch, setBatch] = useState('');
  const [list, setList] = useState<InstrumentList | null>(null);
  const [matrix, setMatrix] = useState<Capability[]>([]);

  useEffect(() => {
    api.capabilities().then((response) => setMatrix(response.matrix)).catch(() => setMatrix([]));
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      api.instruments(query, batch).then(setList).catch(() => setList(null));
    }, 180);
    return () => clearTimeout(timer);
  }, [query, batch]);

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
            Search the universe or pick a batch. Batches are liquidity-ranked from our own
            turnover history rather than index membership, because a published constituent
            list only exists as it stands today and using one across history is
            survivorship bias.
          </p>
        </div>
      </section>

      <div className="ttools">
        <input
          className="tsearch"
          placeholder="Search symbols…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Search instruments"
        />
        <button className="tchip" type="button" aria-pressed={batch === ''} onClick={() => setBatch('')}>
          All
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

      {list && !list.ok && <div className="tnote bad">{list.error}</div>}

      <div className="tgrid">
        <div className="tpanel">
          <h3>Symbols</h3>
          <div className="tscroll" style={{ maxHeight: 460 }}>
            <table className="ttable">
              <thead>
                <tr>
                  <th>Symbol</th>
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
                      <b>{instrument.symbol}</b>
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

        <div className="tpanel">
          <h3>What has data behind it</h3>
          <table className="ttable">
            <thead>
              <tr>
                <th>Asset class</th>
                <th>Timeframe</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {matrix.map((cell) => (
                <tr key={`${cell.asset_class}-${cell.timeframe}`}>
                  <td>
                    <b>{cell.asset_class}</b>
                  </td>
                  <td>
                    <span className="ttag">{cell.timeframe}</span>
                  </td>
                  <td>
                    <span className="tpill" data-stage={cell.supported ? 'live' : 'retired'}>
                      {cell.supported ? 'ready' : 'no data'}
                    </span>
                    <p className="tfine" style={{ margin: '4px 0 0' }}>
                      {cell.detail}
                    </p>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {list && <p className="tfine">{list.batch_caveat}</p>}
    </>
  );
}
