'use client';

/**
 * Pick individual instruments instead of a batch.
 *
 * Batches are a convenience, not the only way in. "Does this work on these
 * eleven banks" is a legitimate backtest and was previously unaskable — the
 * only choice was a named universe, and the whole panel was the default.
 *
 * A hand-picked list overrides the universe entirely and is recorded as
 * `custom`, with the instruments themselves in the configuration hash, so two
 * different hand-picked lists are two different results rather than both being
 * "custom".
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Instrument } from '@/lib/api';

export function InstrumentChooser({
  chosen,
  onChange,
  onClose,
}: {
  chosen: string[];
  onChange: (symbols: string[]) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState('');
  const [batch, setBatch] = useState('');
  const [found, setFound] = useState<Instrument[]>([]);
  const [batches, setBatches] = useState<string[]>([]);
  const [problem, setProblem] = useState('');

  useEffect(() => {
    const timer = setTimeout(() => {
      api
        .instruments(query, batch)
        .then((list) => {
          setFound(list.instruments);
          setBatches(list.batches);
          setProblem(list.ok ? '' : (list.error ?? ''));
        })
        .catch(() => setProblem('Cannot reach the instrument list.'));
    }, 180);
    return () => clearTimeout(timer);
  }, [query, batch]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const toggle = (symbol: string) =>
    onChange(
      chosen.includes(symbol) ? chosen.filter((s) => s !== symbol) : [...chosen, symbol]
    );

  return (
    <div className="pal-scrim" role="dialog" aria-modal="true" aria-label="Choose instruments" onClick={onClose}>
      <div className="dlg wide" onClick={(event) => event.stopPropagation()}>
        <header className="dlg-head">
          <div>
            <div className="theyebrow">Instruments</div>
            <h2>{chosen.length ? `${chosen.length} chosen` : 'Pick instruments'}</h2>
          </div>
          <button className="ticon" type="button" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="dlg-modes" style={{ flexWrap: 'wrap' }}>
          <input
            className="tsearch"
            style={{ flex: '1 1 220px' }}
            placeholder="Search symbols…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search instruments"
            autoFocus
          />
          <button className="tchip" type="button" aria-pressed={batch === ''} onClick={() => setBatch('')}>
            All
          </button>
          {batches.map((name) => (
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

        {chosen.length > 0 && (
          <div className="chosen-rail">
            {chosen.map((symbol) => (
              <button key={symbol} className="chosen-chip" type="button" onClick={() => toggle(symbol)}>
                {symbol} <span aria-hidden="true">✕</span>
              </button>
            ))}
            <button className="tbtn sm ghost-line" type="button" onClick={() => onChange([])}>
              Clear all
            </button>
          </div>
        )}

        <div className="dlg-body">
          {problem && <div className="tnote bad">{problem}</div>}
          <div className="tscroll" style={{ maxHeight: '44vh' }}>
            <table className="ttable">
              <thead>
                <tr>
                  <th style={{ width: 26 }} />
                  <th>Symbol</th>
                  <th>Class</th>
                  <th className="r">Rank</th>
                  <th className="r">Daily</th>
                  <th className="r">Minute</th>
                </tr>
              </thead>
              <tbody>
                {found.map((instrument) => (
                  <tr key={`${instrument.asset_class}-${instrument.symbol}`}>
                    <td>
                      <input
                        type="checkbox"
                        checked={chosen.includes(instrument.symbol)}
                        onChange={() => toggle(instrument.symbol)}
                        aria-label={`Choose ${instrument.symbol}`}
                      />
                    </td>
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
            {found.length === 0 && !problem && <div className="tempty">Nothing matches.</div>}
          </div>

          <div className="dlg-foot">
            <div className="verdict" data-ok={chosen.length > 0}>
              {chosen.length === 0
                ? 'Nothing chosen — runs will use the selected universe.'
                : `${chosen.length} instruments. This overrides the universe and is recorded as a custom run.`}
            </div>
            <button className="tbtn go" type="button" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
