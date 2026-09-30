'use client';

/**
 * Bloomberg's mnemonics, without the keyboard.
 *
 * `AAPL US Equity DES` is faster than any menu and — the part usually missed —
 * it is *learnable*: the same three letters mean the same thing everywhere. At
 * a hundred strategies a menu is fine; at a thousand it is not, and this system
 * is explicitly built for a thousand.
 *
 * One input reaches strategies, features, papers and actions. The prefixes are
 * the mnemonics: `STRAT`, `FEAT`, `PAPER`, `RUN`.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { FleetStrategy } from '@/lib/api';

type Entry = {
  kind: 'STRAT' | 'FEAT' | 'PAPER' | 'RUN';
  label: string;
  meta: string;
};

const STAGE_META: Record<string, string> = {
  registered: 'screened',
  backtested: 'backtested',
  forward_testing: 'validated',
  live: 'live',
  retired: 'retired',
};

export function CommandPalette({
  strategies,
  onClose,
}: {
  strategies: FleetStrategy[];
  onClose: () => void;
}) {
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const entries = useMemo<Entry[]>(() => {
    const needle = query.trim().toLowerCase();
    const out: Entry[] = [];

    for (const s of strategies) {
      if (!needle || s.id.toLowerCase().includes(needle) || s.kind.includes(needle)) {
        out.push({
          kind: 'STRAT',
          label: s.id,
          meta: `${s.asset_class} · ${STAGE_META[s.stage] ?? s.stage}`,
        });
      }
    }
    if (needle.length >= 2) {
      out.push({
        kind: 'RUN',
        // The palette is also where a run gets priced. Showing the cost here
        // rather than after the click is the whole point: an interface that
        // makes running cheap is what lets somebody spend fifty trials in an
        // afternoon.
        label: `screen ${needle}* on nifty100`,
        meta: 'spends no trial · unrecorded search',
      });
    }
    return out.slice(0, 12);
  }, [strategies, query]);

  useEffect(() => {
    setCursor(0);
  }, [query]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setCursor((c) => Math.min(c + 1, Math.max(entries.length - 1, 0)));
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setCursor((c) => Math.max(c - 1, 0));
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [entries.length, onClose]);

  return (
    <div
      className="pal-scrim"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      onClick={onClose}
    >
      <div className="pal" onClick={(event) => event.stopPropagation()}>
        <input
          ref={inputRef}
          className="pal-input"
          placeholder="strategy, feature, paper, or an action…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Search everything"
        />
        <div className="pal-list" role="listbox">
          {entries.map((entry, index) => (
            <div
              key={`${entry.kind}-${entry.label}`}
              className="pal-row"
              role="option"
              aria-selected={index === cursor}
              onMouseEnter={() => setCursor(index)}
            >
              <span className="pal-kind">{entry.kind}</span>
              <span>{entry.label}</span>
              <span className="pal-meta">{entry.meta}</span>
            </div>
          ))}
          {entries.length === 0 && (
            <div className="pal-row" style={{ color: 'var(--ink-3)' }}>
              nothing matches
            </div>
          )}
        </div>
        <div className="pal-hint">↑↓ move · esc close · prefixes: STRAT FEAT PAPER RUN</div>
      </div>
    </div>
  );
}
