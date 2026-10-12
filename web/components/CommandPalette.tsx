'use client';

/**
 * Jump to anything: every page, every tool and every strategy from one input.
 *
 * It used to list strategies and a "RUN" action that did nothing when chosen —
 * a search box whose results could not be opened. Every entry here goes
 * somewhere: a page or tool navigates, a strategy opens its explanation, a
 * company opens its page.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { companySearch, type CompanyHit, type FleetStrategy } from '@/lib/api';

export type PaletteTarget = { id: string; label: string; meta: string };

type Entry =
  | { kind: 'PAGE'; label: string; meta: string; id: string }
  | { kind: 'STRAT'; label: string; meta: string; id: string }
  | { kind: 'CO'; label: string; meta: string; id: string };

const STAGE_META: Record<string, string> = {
  registered: 'screened',
  backtested: 'backtested',
  forward_testing: 'validated',
  live: 'live',
  retired: 'retired',
};

export function CommandPalette({
  pages,
  strategies,
  onPage,
  onStrategy,
  onClose,
}: {
  pages: PaletteTarget[];
  strategies: FleetStrategy[];
  onPage: (id: string) => void;
  onStrategy: (id: string) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Companies come from the server: 2,352 of them, searched by symbol or name
  // once two letters are typed. Pages and strategies are already in memory.
  const [companies, setCompanies] = useState<CompanyHit[]>([]);
  useEffect(() => {
    const wanted = query.trim();
    if (wanted.length < 2) {
      setCompanies([]);
      return;
    }
    let live = true;
    const timer = window.setTimeout(() => {
      companySearch(wanted, 6)
        .then((found) => live && setCompanies(found.rows))
        .catch(() => live && setCompanies([]));
    }, 150);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [query]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const entries = useMemo<Entry[]>(() => {
    const needle = query.trim().toLowerCase();
    const out: Entry[] = [];
    for (const page of pages) {
      if (!needle || `${page.label} ${page.meta}`.toLowerCase().includes(needle)) {
        out.push({ kind: 'PAGE', ...page });
      }
    }
    for (const s of strategies) {
      if (
        !needle ||
        [s.id, s.title, s.kind].some((field) => field.toLowerCase().includes(needle))
      ) {
        out.push({
          kind: 'STRAT',
          id: s.id,
          label: s.title,
          meta: `${s.asset_class} · ${STAGE_META[s.stage] ?? s.stage}`,
        });
      }
    }
    const shown = out.slice(0, 14 - companies.length);
    for (const company of companies) {
      shown.push({
        kind: 'CO',
        id: company.symbol,
        label: company.name || company.symbol,
        meta: `${company.symbol} · ${company.industry || 'company'}`,
      });
    }
    return shown;
  }, [pages, strategies, query, companies]);

  useEffect(() => {
    setCursor(0);
  }, [query]);

  const choose = (entry: Entry | undefined) => {
    if (!entry) return;
    if (entry.kind === 'CO') {
      // A company has its own page; leave the terminal shell for it.
      window.location.assign(`/terminal/company/${encodeURIComponent(entry.id)}`);
      return;
    }
    if (entry.kind === 'PAGE') onPage(entry.id);
    else onStrategy(entry.id);
    onClose();
  };

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
      aria-label="Jump to anything"
      onClick={onClose}
    >
      <div className="pal" onClick={(event) => event.stopPropagation()}>
        <input
          ref={inputRef}
          className="pal-input"
          placeholder="A page, a tool, a strategy or a company…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') choose(entries[cursor]);
          }}
          aria-label="Search everything"
        />
        <div className="pal-list" role="listbox">
          {entries.map((entry, index) => (
            <div
              key={`${entry.kind}-${entry.id}`}
              className="pal-row"
              role="option"
              aria-selected={index === cursor}
              onMouseEnter={() => setCursor(index)}
              onClick={() => choose(entry)}
            >
              <span className="pal-kind">{entry.kind === 'PAGE' ? 'GO' : entry.kind}</span>
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
        <div className="pal-hint">↑↓ move · enter open · esc close</div>
      </div>
    </div>
  );
}
