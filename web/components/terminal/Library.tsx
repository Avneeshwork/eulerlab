'use client';

/**
 * The library.
 *
 * Columns are Strategy, Asset, Graph, Sharpe vs bar, Actions. Evidence, Runs
 * and Trials came out of the table on the operator's instruction; none of that
 * information was deleted, it moved into the row's detail panel and into the
 * line under the number, which already carried "best of N" at every breakpoint.
 * The one real cost is that the trial count is now a click away rather than in
 * the default view.
 *
 * The graph is the actual equity path of the best stored run, downsampled
 * server-side. A strategy that has never run draws nothing at all — a flat line
 * would be a picture of a run that did not happen.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { EvidenceBadge, SharpeCell, Tag } from '@/components/primitives';
import { Spark } from '@/components/terminal/Spark';
import { UniversePicker } from '@/components/terminal/UniversePicker';
import { api } from '@/lib/api';
import { runBatch } from '@/lib/run';
import type { Fleet, FleetStrategy } from '@/lib/api';

type Sort = 'evidence' | 'name' | 'sharpe';

const RUNG_ORDER: Record<string, number> = {
  live: 0,
  forward_testing: 1,
  backtested: 2,
  registered: 3,
  retired: 4,
};

export function Library({
  fleet,
  problem,
  window: days,
  tier,
  universe,
  onUniverse,
  instruments,
  onChoose,
  onRefresh,
  onDeploy,
  onExplain,
  onReport,
  onConfigure,
  pendingRun,
  onRan,
}: {
  fleet: Fleet | null;
  problem: string;
  window: number;
  tier: 'A' | 'B';
  universe: string;
  onUniverse: (name: string) => void;
  instruments: string[];
  onChoose: () => void;
  onRefresh: () => void;
  onDeploy: (strategy: FleetStrategy) => void;
  onExplain: (strategy: string) => void;
  onReport: (strategy: FleetStrategy) => void;
  onConfigure: (strategy: FleetStrategy) => void;
  /** Ids the Backtest dialog just confirmed. Run once, then cleared. */
  pendingRun: string[];
  onRan: () => void;
}) {
  const [query, setQuery] = useState('');
  const [assetClass, setAssetClass] = useState('');
  const [sort, setSort] = useState<Sort>('evidence');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [note, setNote] = useState('');
  const [failure, setFailure] = useState('');

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
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const backtest = useCallback(
    async (ids: string[]) => {
      setFailure('');
      setBusy((prev) => new Set([...prev, ...ids]));
      try {
        const result = await runBatch(ids, days, tier, universe, instruments, setNote);
        const failed = result.results.filter((r) => r.error);
        setNote(
          `${result.computed} computed, ${result.cached} cached` +
            (failed.length ? `, ${failed.length} failed` : '') +
            (result.cloud
              ? result.cloud.ok
                ? ` · ${result.cloud.pushed} mirrored to cloud`
                : ` · cloud mirror failed: ${result.cloud.failed[0] ?? 'unknown'}`
              : '')
        );
        if (failed.length) setFailure(`${failed[0].strategy}: ${failed[0].error}`);
        onRefresh();
      } catch (error) {
        setFailure(error instanceof Error ? error.message : String(error));
      } finally {
        setBusy((prev) => {
          const next = new Set(prev);
          for (const id of ids) next.delete(id);
          return next;
        });
      }
    },
    [days, tier, universe, instruments, onRefresh]
  );

  useEffect(() => {
    if (pendingRun.length === 0) return;
    const ids = pendingRun;
    onRan();
    void backtest(ids);
  }, [pendingRun, onRan, backtest]);

  return (
    <>
      <div className="ttools">
        <input
          className="tsearch"
          placeholder="Search by name, factor or paper…"
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
          All
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
        <UniversePicker value={universe} onChange={onUniverse} />
        <button
          className="tchip"
          type="button"
          aria-pressed={instruments.length > 0}
          onClick={onChoose}
          title="Pick individual instruments instead of a batch. Overrides the universe."
        >
          {instruments.length > 0 ? `${instruments.length} instruments` : 'Pick instruments'}
        </button>
        <label className="tsort">
          Sort
          <select value={sort} onChange={(event) => setSort(event.target.value as Sort)}>
            <option value="evidence">Evidence</option>
            <option value="name">Name</option>
            <option value="sharpe">Sharpe — see note</option>
          </select>
        </label>
      </div>

      {sort === 'sharpe' && (
        <div className="tnote">
          <span className="mk" aria-hidden="true">
            ▲
          </span>
          <div>
            <b>Sorting by Sharpe and taking the top row is the selection procedure the
            overfitting test measures.</b>{' '}
            The ranking is offered because hiding it would be worse than showing it with
            this attached — but the bar, not the order, is what decides anything.
          </div>
        </div>
      )}

      {note && !failure && <div className="trunning">{note}</div>}
      {failure && (
        <div className="tnote bad">
          <span className="mk" aria-hidden="true">
            ▲
          </span>
          <div>{failure}</div>
        </div>
      )}

      {problem && (
        <div className="tnote bad">
          <span className="mk" aria-hidden="true">
            ▲
          </span>
          <div>{problem}</div>
        </div>
      )}

      <div className="tcols" aria-hidden="true">
        <span />
        <span>Strategy</span>
        <span>Asset</span>
        <span>Backtest</span>
        <span className="r">Sharpe vs bar</span>
        <span className="r">Actions</span>
      </div>

      <div className="tlist">
        {fleet &&
          rows.map((strategy) => (
            <Row
              key={strategy.id}
              strategy={strategy}
              bar={fleet.bar}
              checked={selected.has(strategy.id)}
              open={open === strategy.id}
              busy={busy.has(strategy.id)}
              onToggle={() => toggle(strategy.id)}
              onOpen={() => setOpen(open === strategy.id ? null : strategy.id)}
              onBacktest={() => onConfigure(strategy)}
              onDeploy={() => onDeploy(strategy)}
              onExplain={() => onExplain(strategy.id)}
              onReport={() => onReport(strategy)}
            />
          ))}
        {fleet && rows.length === 0 && <div className="tempty">Nothing matches that filter.</div>}
        {!fleet && !problem && <div className="tempty">Reading the registry…</div>}
      </div>

      {selected.size > 0 && (
        <div className="tsel">
          <b>{selected.size}</b> selected
          <span className="price">
            {instruments.length > 0 ? `${instruments.length} chosen instruments` : universe} ·{' '}
            {days}-day window · tier {tier} · spends no trial, so the bar will not learn
            this search happened
          </span>
          <button className="tbtn ghost" type="button" onClick={() => setSelected(new Set())}>
            Clear
          </button>
          <button
            className="tbtn"
            type="button"
            disabled={busy.size > 0}
            onClick={() => backtest([...selected])}
          >
            {busy.size > 0 ? 'Running…' : `Backtest ${selected.size}`}
          </button>
        </div>
      )}
    </>
  );
}

function Row({
  strategy,
  bar,
  checked,
  open,
  busy,
  onToggle,
  onOpen,
  onBacktest,
  onDeploy,
  onExplain,
  onReport,
}: {
  strategy: FleetStrategy;
  bar: number;
  checked: boolean;
  open: boolean;
  busy: boolean;
  onToggle: () => void;
  onOpen: () => void;
  onBacktest: () => void;
  onDeploy: () => void;
  onExplain: () => void;
  onReport: () => void;
}) {
  const result = strategy.result;
  const runnable = strategy.is_strategy_subclass;
  return (
    <div className="trow" data-open={open}>
      <div
        className="trow-top"
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={onOpen}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            onOpen();
          }
        }}
      >
        <div className="c-sel" onClick={(event) => event.stopPropagation()}>
          <input
            type="checkbox"
            checked={checked}
            onChange={onToggle}
            disabled={!runnable}
            aria-label={`Select ${strategy.title}`}
          />
        </div>
        <div className="tname">
          <div className="nm">{strategy.title}</div>
          <div className="sub">
            {strategy.kind} · {strategy.shape}
            {!runnable && (
              <span
                className="tflag"
                title="Cannot satisfy the Strategy interface: its data cannot be expressed in a MarketView (ADR-037)."
              >
                not a Strategy
              </span>
            )}
          </div>
        </div>
        <div className="tmeta">
          <Tag>{strategy.asset_class}</Tag>
          {result.universe ? (
            <Tag
              title={`This result was run on ${result.universe}${
                result.symbols ? `; ${result.symbols} names actually traded` : ''
              }.`}
            >
              {result.universe}
              {result.symbols ? ` · ${result.symbols}` : ''}
            </Tag>
          ) : (
            <span className="tdim" style={{ fontSize: 11 }}>
              never run
            </span>
          )}
        </div>
        <div className="tgraph">
          {busy ? (
            <span className="tdim">running…</span>
          ) : (
            <Spark
              curve={result.curve}
              clears={strategy.clears_bar}
              title={curveTitle(strategy)}
            />
          )}
        </div>
        <SharpeCell
          sharpe={strategy.sharpe}
          bar={bar}
          runs={result.runs}
        />
        <div className="tacts-cell" onClick={(event) => event.stopPropagation()}>
          <button
            className="ticon sm"
            type="button"
            onClick={onExplain}
            title="What this strategy is, what a backtest here does, and which asset classes have data."
            aria-label={`What ${strategy.title} means`}
          >
            i
          </button>
          <button
            className="tbtn sm"
            type="button"
            disabled={busy || !runnable}
            onClick={onBacktest}
            title={
              runnable
                ? 'Choose the instruments and the period, then run.'
                : 'Cannot run through the daily engine (ADR-037).'
            }
          >
            {busy ? '…' : 'Backtest'}
          </button>
          <button
            className="tbtn sm ghost-line"
            type="button"
            onClick={onDeploy}
            title="Check every condition that must hold before this can trade."
          >
            Deploy
          </button>
        </div>
      </div>

      {open && (
        <div className="tdetail">
          <div>
            <p className="tdesc">{strategy.summary}</p>
            <div className="tfacts">
              <Fact label="Evidence" value={<EvidenceBadge stage={strategy.stage} />} />
              <Fact label="Configurations" value={result.runs || '—'} />
              <Fact
                label="Best of them"
                value={result.best_sharpe !== null && result.best_sharpe !== undefined ? result.best_sharpe.toFixed(2) : '—'}
              />
              <Fact label="Universe" value={result.universe || '—'} />
              <Fact label="Instruments" value={result.symbols ?? '—'} />
              <Fact label="Trials" value={strategy.trials} />
              <Fact label="Total return" value={fmtPct(result.total_return)} />
              <Fact label="Max drawdown" value={fmtPct(result.max_drawdown)} />
              <Fact label="Fills" value={result.fills ?? '—'} />
              <Fact label="Window" value={result.window_days ? `${result.window_days}d` : '—'} />
              <Fact label="Universe" value={result.universe || '—'} />
              <Fact label="Names traded" value={result.symbols || '—'} />
              <Fact label="Tier" value={result.tier || '—'} />
              <Fact label="Lookback" value={`${strategy.lookback}d`} />
              <Fact label="Risk manager" value={strategy.risk_manager || '—'} />
              <Fact label="Trade manager" value={strategy.trade_manager || '—'} />
            </div>
          </div>
          <div className="tside">
            <button
              className="tbtn go"
              type="button"
              disabled={strategy.sharpe === null}
              onClick={onReport}
              title={
                strategy.sharpe === null
                  ? 'Never run, so there is nothing to report on.'
                  : 'Per-instrument attribution, the order ledger, and every metric.'
              }
            >
              Full analysis
            </button>
            {result.caveat && (
              <div className="tcaveat">
                <h4>What this number is not</h4>
                {result.caveat}
              </div>
            )}
            {!result.caveat && strategy.sharpe === null && (
              <div className="tcaveat">
                <h4>No result</h4>
                Never backtested in this workspace. The column reads &ldquo;not
                measured&rdquo; rather than zero, because zero would be a finding.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * What the graph is a picture of.
 *
 * The headline Sharpe prefers the trial ledger's figure, which is a validated
 * result and the stronger claim. The curve can only come from the result store,
 * which holds screening runs. When those two disagree they are two different
 * runs, and a graph sitting silently beside a number it did not produce is a
 * quiet lie — so the tooltip always names its own run, and says so when they
 * differ.
 */
function curveTitle(strategy: FleetStrategy): string {
  const result = strategy.result;
  if (result.sharpe === null || result.sharpe === undefined) return 'Equity curve';
  const base =
    `Most recent backtest: Sharpe ${result.sharpe.toFixed(2)}` +
    (result.window_days ? ` over ${result.window_days} trading days` : '') +
    (result.universe ? ` on ${result.universe}` : '') +
    (result.symbols ? `, ${result.symbols} instruments` : '') +
    (result.tier ? `, tier ${result.tier}` : '');
  const headline = strategy.sharpe;
  if (headline !== null && Math.abs(headline - result.sharpe) > 0.005) {
    return (
      `${base}. The ${headline.toFixed(2)} shown alongside is the trial ledger's ` +
      `validated figure from a different run — this curve is not its path.`
    );
  }
  return base;
}

function fmtPct(value: number | undefined) {
  if (value === undefined || value === null) return '—';
  return `${value >= 0 ? '' : '−'}${Math.abs(value * 100).toFixed(1)}%`;
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="tfact">
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}
