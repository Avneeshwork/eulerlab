'use client';

/**
 * The fleet list — the console's primary surface.
 *
 * The one design decision that matters here: **every Sharpe is drawn against
 * the noise bar, never as a bare number.** A list of strategies sorted by
 * Sharpe descending, top row picked, is precisely the selection procedure the
 * PBO test measures as overfitting. Making it the path of least resistance
 * would turn the interface into an engine for the error the rest of the system
 * exists to prevent.
 *
 * So: clearing the bar is the primary visual signal and magnitude is
 * secondary, the bar tick is drawn at the same position on every row, and
 * sorting by Sharpe says out loud what it is doing.
 */

import { useMemo, useState } from 'react';
import type { Fleet, FleetStrategy } from '@/lib/api';

type Sort = 'id' | 'stage' | 'sharpe';

const STAGE_CLASS: Record<string, string> = {
  live: 'live',
  forward_testing: 'fwd',
  backtested: 'bt',
  registered: '',
  retired: 'ret',
};

export function FleetTable({
  fleet,
  selected,
  onToggle,
}: {
  fleet: Fleet;
  selected: Set<string>;
  onToggle: (id: string) => void;
}) {
  const [query, setQuery] = useState('');
  const [assetClass, setAssetClass] = useState('');
  const [timeframe, setTimeframe] = useState('');
  const [sort, setSort] = useState<Sort>('id');

  const classes = useMemo(
    () => Array.from(new Set(fleet.strategies.map((s) => s.asset_class))).sort(),
    [fleet.strategies]
  );
  const frames = useMemo(
    () => Array.from(new Set(fleet.strategies.map((s) => s.timeframe))).sort(),
    [fleet.strategies]
  );

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = fleet.strategies.filter((s) => {
      if (assetClass && s.asset_class !== assetClass) return false;
      if (timeframe && s.timeframe !== timeframe) return false;
      if (!needle) return true;
      return (
        s.id.toLowerCase().includes(needle) ||
        s.title.toLowerCase().includes(needle) ||
        s.kind.toLowerCase().includes(needle) ||
        s.shape.toLowerCase().includes(needle)
      );
    });
    const order = [...filtered];
    if (sort === 'sharpe') {
      // Unmeasured sorts last, never as zero — a strategy with no evidence is
      // not a strategy that scored nothing.
      order.sort((a, b) => (b.sharpe ?? -Infinity) - (a.sharpe ?? -Infinity));
    } else if (sort === 'stage') {
      const rank = ['live', 'forward_testing', 'backtested', 'registered', 'retired'];
      order.sort((a, b) => rank.indexOf(a.stage) - rank.indexOf(b.stage));
    } else {
      order.sort((a, b) => a.id.localeCompare(b.id));
    }
    return order;
  }, [fleet.strategies, query, assetClass, timeframe, sort]);

  // The bar sits at a fixed fraction of the track on every row, so the tick
  // lines up down the column and "who clears it" is readable at a glance.
  const scale = Math.max(fleet.bar * 1.6, 0.01);

  return (
    <div className="card">
      {/* The noise bar is already in the masthead statline; repeating it here
          made the same number argue with itself two inches apart. */}
      <h2>Fleet</h2>
      <p className="sub">
        {fleet.strategies.length} registered. Every Sharpe is drawn against the bar,
        because a Sharpe on its own reads as good or bad against nothing.
      </p>

      <div className="tools">
        <input
          className="tool-search"
          placeholder="Search name, kind, shape…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search strategies"
        />
        <button
          className={`chip${assetClass ? ' on' : ''}`}
          onClick={() => setAssetClass('')}
          aria-pressed={!assetClass}
        >
          all classes
        </button>
        {classes.map((c) => (
          <button
            key={c}
            className={`chip${assetClass === c ? ' on' : ''}`}
            onClick={() => setAssetClass(assetClass === c ? '' : c)}
            aria-pressed={assetClass === c}
          >
            {c}
          </button>
        ))}
        {frames.map((f) => (
          <button
            key={f}
            className={`chip${timeframe === f ? ' on' : ''}`}
            onClick={() => setTimeframe(timeframe === f ? '' : f)}
            aria-pressed={timeframe === f}
          >
            {f}
          </button>
        ))}
        <label className="sortby">
          sort
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="id">name</option>
            <option value="stage">stage</option>
            <option value="sharpe">Sharpe — see note</option>
          </select>
        </label>
      </div>

      {sort === 'sharpe' && (
        <div className="note warn" style={{ marginBottom: 12 }}>
          Sorting by Sharpe and taking the top row is the selection procedure the
          overfitting test measures. The ranking is shown because hiding it would be
          worse — but the bar, not the order, is what decides anything.
        </div>
      )}

      <div className="fleet-scroll">
        <table className="fleet">
          <thead>
            <tr>
              <th aria-label="select" />
              <th>Strategy</th>
              <th>Class</th>
              <th>TF</th>
              <th>Stage</th>
              <th style={{ textAlign: 'right' }}>Sharpe vs bar</th>
              <th style={{ textAlign: 'right' }}>Trials</th>
              <th>RM / TM</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <Row
                key={s.id}
                s={s}
                bar={fleet.bar}
                scale={scale}
                checked={selected.has(s.id)}
                onToggle={() => onToggle(s.id)}
              />
            ))}
          </tbody>
        </table>
      </div>

      {rows.length === 0 && (
        <p className="muted" style={{ marginTop: 12 }}>
          Nothing matches that filter.
        </p>
      )}
    </div>
  );
}

function Row({
  s,
  bar,
  scale,
  checked,
  onToggle,
}: {
  s: FleetStrategy;
  bar: number;
  scale: number;
  checked: boolean;
  onToggle: () => void;
}) {
  const barLeft = Math.min((bar / scale) * 100, 100);
  const fill = s.sharpe === null ? 0 : Math.max(Math.min((s.sharpe / scale) * 100, 100), 0);

  return (
    <tr>
      <td>
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          aria-label={`Select ${s.title}`}
        />
      </td>
      <td>
        <div className="nm">{s.id}</div>
        <div className="rowsub">
          {s.kind} · {s.shape}
          {!s.is_strategy_subclass && (
            <span
              className="flag"
              title="Cannot satisfy the Strategy interface today: a minute bar cannot be expressed in a MarketView (ADR-037)."
            >
              not a Strategy
            </span>
          )}
        </div>
      </td>
      <td>
        <span className="tag">{s.asset_class}</span>
      </td>
      <td>
        <span className="tag">{s.timeframe}</span>
      </td>
      <td>
        <span className={`stage ${STAGE_CLASS[s.stage] ?? ''}`}>{s.stage.replace('_', ' ')}</span>
      </td>
      <td>
        <div className="sb">
          <span className={`sb-val${s.clears_bar ? ' clears' : ''}${s.sharpe === null ? ' none' : ''}`}>
            {s.sharpe === null ? 'not measured' : s.sharpe.toFixed(2)}
          </span>
          <span className="sb-track">
            <span className="sb-line" />
            {s.sharpe !== null && (
              <span className={`sb-fill${s.clears_bar ? ' clears' : ''}`} style={{ width: `${fill}%` }} />
            )}
            <span className="sb-bar" style={{ left: `${barLeft}%` }} />
          </span>
        </div>
      </td>
      <td className="numcell">{s.trials}</td>
      <td className="rmcell">
        {s.risk_manager || <span className="none">none</span>}
        {' / '}
        {s.trade_manager || <span className="none">none</span>}
      </td>
    </tr>
  );
}
