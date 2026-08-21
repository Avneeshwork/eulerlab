'use client';

/**
 * The library — the terminal's primary surface.
 *
 * The design decision this screen exists to encode: **the default sort is
 * evidence, not Sharpe.** Ranking a strategy library by return is the selection
 * procedure that overfitting tests measure, performed by the interface, at
 * scale, before the user has thought about it. Composer's own reviewers describe
 * the result as "backtested junk optimized to look good on historical data" —
 * that is not a Composer flaw, it is what sorting by return produces.
 *
 * Sorting by Sharpe remains available, because hiding it would be worse than
 * showing it with a warning attached.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { CommandPalette } from '@/components/CommandPalette';
import { EvidenceBadge, SharpeVsBar, Tag } from '@/components/primitives';
import { api } from '@/lib/api';
import type { Fleet, FleetStrategy } from '@/lib/api';

type Sort = 'evidence' | 'name' | 'sharpe';

const RUNG_ORDER: Record<string, number> = {
  live: 0,
  forward_testing: 1,
  backtested: 2,
  registered: 3,
  retired: 4,
};

const NAV = ['Library', 'Build', 'Run', 'Instruments', 'Live', 'Data'];

export default function TerminalPage() {
  const [fleet, setFleet] = useState<Fleet | null>(null);
  const [problem, setProblem] = useState('');
  const [query, setQuery] = useState('');
  const [assetClass, setAssetClass] = useState('');
  const [sort, setSort] = useState<Sort>('evidence');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    api
      .fleet()
      .then(setFleet)
      .catch(() => setProblem('Cannot reach the API. Is it running on :8000?'));
  }, []);

  // ⌘K / Ctrl-K. Bloomberg's mnemonics without the keyboard: one input that
  // reaches strategies, features, papers and actions.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const classes = useMemo(
    () => Array.from(new Set(fleet?.strategies.map((s) => s.asset_class) ?? [])).sort(),
    [fleet]
  );

  const rows = useMemo(() => {
    if (!fleet) return [];
    const needle = query.trim().toLowerCase();
    const filtered = fleet.strategies.filter((s) => {
      if (assetClass && s.asset_class !== assetClass) return false;
      if (!needle) return true;
      return [s.id, s.title, s.kind, s.shape, s.summary].some((field) =>
        field.toLowerCase().includes(needle)
      );
    });

    const ordered = [...filtered];
    if (sort === 'sharpe') {
      // Unmeasured sorts last, never as zero: null means nobody looked, zero is
      // a measurement meaning no edge, and the two must not collapse.
      ordered.sort((a, b) => (b.sharpe ?? -Infinity) - (a.sharpe ?? -Infinity));
    } else if (sort === 'name') {
      ordered.sort((a, b) => a.id.localeCompare(b.id));
    } else {
      ordered.sort(
        (a, b) =>
          (RUNG_ORDER[a.stage] ?? 9) - (RUNG_ORDER[b.stage] ?? 9) ||
          b.trials - a.trials ||
          a.id.localeCompare(b.id)
      );
    }
    return ordered;
  }, [fleet, query, assetClass, sort]);

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      // Selection is explicit and counted. A windowed list that quietly
      // includes rows nobody rendered would, here, spend trials nobody chose.
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return (
    <>
      <header className="tbar">
        <span className="tbrand">
          euler<span>lab</span>
        </span>
        <nav className="tnav" aria-label="Sections">
          {NAV.map((item) => (
            <button key={item} type="button" aria-current={item === 'Library' ? 'page' : undefined}>
              {item}
            </button>
          ))}
        </nav>
        <div className="tright">
          <span className="tws" title="Evidence, strategies and credentials are scoped to this workspace (ADR-040).">
            workspace: default
          </span>
          <button className="tcmd" type="button" onClick={() => setPaletteOpen(true)}>
            ⌘K&nbsp; jump to anything
          </button>
        </div>
      </header>

      <div className="tpage">
        <div className="thead">
          <div>
            <h1>Library</h1>
            <p className="tsub">
              Sorted by evidence, not by return. Ranking a strategy library by performance is
              the selection procedure the overfitting tests measure — done by the interface,
              at scale, before anyone has thought about it.
            </p>
          </div>
        </div>

        {fleet && (
          <div className="tbanner">
            <span>
              strategies <b>{fleet.strategies.length}</b>
            </span>
            <span title={fleet.bar_note}>
              noise bar <b>{fleet.bar.toFixed(2)}</b>
              {!fleet.bar_sigma_measured && <em className="assumed"> assumed</em>}
            </span>
            <span>
              clearing it <b>{fleet.strategies.filter((s) => s.clears_bar).length}</b>
            </span>
            <span>
              trials logged <b>{fleet.strategies.reduce((sum, s) => sum + s.trials, 0)}</b>
            </span>
            <span style={{ marginLeft: 'auto' }}>screening here spends no trial</span>
          </div>
        )}

        {problem && <div className="tnote">{problem}</div>}

        <div className="ttools">
          <input
            className="tsearch"
            placeholder="search name, factor, paper…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search strategies"
          />
          <button
            className="tchip"
            type="button"
            aria-pressed={assetClass === ''}
            onClick={() => setAssetClass('')}
          >
            all
          </button>
          {classes.map((name) => (
            <button
              key={name}
              className="tchip"
              type="button"
              aria-pressed={assetClass === name}
              onClick={() => setAssetClass(assetClass === name ? '' : name)}
            >
              {name}
            </button>
          ))}
          <label className="tsort">
            sort
            <select value={sort} onChange={(event) => setSort(event.target.value as Sort)}>
              <option value="evidence">evidence</option>
              <option value="name">name</option>
              <option value="sharpe">Sharpe — see note</option>
            </select>
          </label>
        </div>

        {sort === 'sharpe' && (
          <div className="tnote">
            <b>Sorting by Sharpe and taking the top row is the selection procedure the
            overfitting test measures.</b> The ranking is shown because hiding it would be
            worse — but the bar, not the order, is what decides anything.
          </div>
        )}

        <div className="tcard">
          <div className="tscroll">
            <table className="tlib">
              <thead>
                <tr>
                  <th style={{ width: 26 }} aria-label="select" />
                  <th>Strategy</th>
                  <th>Class</th>
                  <th>TF</th>
                  <th>Evidence</th>
                  <th style={{ textAlign: 'right' }}>Sharpe vs bar</th>
                  <th style={{ textAlign: 'right' }}>Runs</th>
                  <th style={{ textAlign: 'right' }}>Trials</th>
                  <th>RM / TM</th>
                </tr>
              </thead>
              <tbody>
                {fleet &&
                  rows.map((strategy) => (
                    <Row
                      key={strategy.id}
                      strategy={strategy}
                      bar={fleet.bar}
                      checked={selected.has(strategy.id)}
                      onToggle={() => toggle(strategy.id)}
                    />
                  ))}
              </tbody>
            </table>
          </div>
          {fleet && rows.length === 0 && <div className="tempty">Nothing matches that filter.</div>}
          {!fleet && !problem && <div className="tempty">Reading the registry…</div>}
        </div>
      </div>

      {paletteOpen && (
        <CommandPalette
          strategies={fleet?.strategies ?? []}
          onClose={() => setPaletteOpen(false)}
        />
      )}
    </>
  );
}

function Row({
  strategy,
  bar,
  checked,
  onToggle,
}: {
  strategy: FleetStrategy;
  bar: number;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <tr>
      <td>
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          aria-label={`Select ${strategy.title}`}
        />
      </td>
      <td>
        <div className="nm">{strategy.id}</div>
        <div className="sub">
          {strategy.kind} · {strategy.shape}
          {!strategy.is_strategy_subclass && (
            <span
              className="tflag"
              title="Cannot satisfy the Strategy interface: its data cannot be expressed in a MarketView (ADR-037)."
            >
              not a Strategy
            </span>
          )}
        </div>
      </td>
      <td>
        <Tag>{strategy.asset_class}</Tag>
      </td>
      <td>
        <Tag>{strategy.timeframe}</Tag>
      </td>
      <td>
        <EvidenceBadge stage={strategy.stage} />
      </td>
      <td>
        <SharpeVsBar
          sharpe={strategy.sharpe}
          bar={bar}
          note={
            strategy.sharpe === null
              ? strategy.trials > 0
                ? 'searched, never measured'
                : 'not measured'
              : strategy.result.caveat || undefined
          }
        />
      </td>
      <td className="num" title={strategy.result.caveat || undefined}>
        {strategy.result.runs || <span style={{ opacity: 0.4 }}>—</span>}
        {strategy.result.is_a_maximum && (
          <span
            className="tflag"
            title={strategy.result.caveat}
            style={{ marginLeft: 4 }}
          >
            max
          </span>
        )}
      </td>
      <td className="num">{strategy.trials}</td>
      <td className="num" style={{ textAlign: 'left', fontSize: 10.5 }}>
        {strategy.risk_manager || <span style={{ opacity: 0.5 }}>none</span>}
        {' / '}
        {strategy.trade_manager || <span style={{ opacity: 0.5 }}>none</span>}
      </td>
    </tr>
  );
}
