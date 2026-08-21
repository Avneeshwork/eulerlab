'use client';

/**
 * Every instrument that has data, across every asset class that has any.
 *
 * This used to show equities and nothing else, which quietly meant 20 landed
 * crypto pairs and 14,280 mutual fund schemes existed on disk and could not be
 * seen or selected. An asset class with data and no way to reach it is the same
 * defect as one offered without data, pointing the other way.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Capability, InstrumentList } from '@/lib/api';

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
  const [matrix, setMatrix] = useState<Capability[]>([]);

  useEffect(() => {
    api
      .capabilities()
      .then((response) => setMatrix(response.matrix))
      .catch(() => setMatrix([]));
  }, []);

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
                  <b>{LABEL[cell.asset_class] ?? cell.asset_class}</b>
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
    </>
  );
}
