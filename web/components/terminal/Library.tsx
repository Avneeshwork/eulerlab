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

import { ASSET_CLASSES, assetClassLabel, homeMarket } from '@/lib/assetClasses';
import { EvidenceBadge, SharpeCell, Tag } from '@/components/primitives';
import { Spark } from '@/components/terminal/Spark';
import { AdoptedReport } from '@/components/terminal/AdoptedReport';
import { SweepPanel } from '@/components/terminal/SweepPanel';
import { TuningPanel } from '@/components/terminal/TuningPanel';
import { WalkPanel } from '@/components/terminal/WalkPanel';
import { Bar, Info, Move } from '@/components/terminal/ui';
import { api } from '@/lib/api';
import { currencySymbol, money } from '@/lib/money';
import { runBatch } from '@/lib/run';
import { belowPaperFloor } from '@/lib/paperFloor';
import type { Fleet, FleetStrategy, OptimizeRow, Recommended, StrategyVerdict } from '@/lib/api';
import './strategies.css';

type Sort = 'verdict' | 'name' | 'annual' | 'drawdown' | 'sharpe' | 'win' | 'trades';
type Style = '' | 'intraday' | 'daily';
type Source = '' | 'paper' | 'builder' | 'coded';

const VERDICTS: { value: StrategyVerdict; label: string; hint: string }[] = [
  { value: 'beats_bar', label: 'Beats the bar', hint: 'Sharpe above what luck across every idea family tested so far explains (the gate’s bar).' },
  { value: 'positive', label: 'Positive, not proven', hint: 'Made money, but luck could explain a Sharpe this size.' },
  { value: 'loses', label: 'Loses money', hint: 'Lost money over its latest run, after costs.' },
  { value: 'not_run', label: 'Not run', hint: 'Never backtested in this workspace.' },
];
const VERDICT_ORDER: Record<StrategyVerdict, number> = { beats_bar: 0, positive: 1, loses: 2, not_run: 3 };

function verdictOf(s: FleetStrategy): StrategyVerdict {
  return s.table?.verdict ?? (s.sharpe === null ? 'not_run' : s.clears_bar ? 'beats_bar' : 'positive');
}

function styleOf(s: FleetStrategy): Exclude<Style, ''> {
  return s.engine === 'intraday' || s.timeframe === '1m' ? 'intraday' : 'daily';
}

function sourceOf(s: FleetStrategy): Exclude<Source, ''> {
  if (s.kind === 'builder') return 'builder';
  if (s.source.startsWith('[paper]') || s.source.startsWith('[adaptation]') || s.published) return 'paper';
  return 'coded';
}

const SOURCE_LABEL: Record<Exclude<Source, ''>, string> = {
  paper: 'From a paper',
  builder: 'My builder',
  coded: 'Coded',
};

/** Green or red for a signed number; nothing for a dash. A strategy never run
 *  showed a green "—" for its return and a red one for its drawdown. */
function tone(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '';
  return value >= 0 ? 'pos' : 'neg';
}

function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`;
}

function annualOf(s: FleetStrategy): number | null {
  return s.table?.annual_return ?? null;
}

const RUNG_ORDER: Record<string, number> = {
  live: 0,
  forward_testing: 1,
  backtested: 2,
  registered: 3,
  retired: 4,
};

/**
 * In the archive: put away by the operator, or no stored backtest report yet
 * (the report's period is unset). The second comes back to the main list by
 * itself once a backtest writes its report (ADR-207).
 */
const inArchive = (s: FleetStrategy) => Boolean(s.archived) || !s.table?.period?.[0];

export function Library({
  fleet,
  problem,
  window: days,
  tier,
  universe,
  instruments,
  runClass,
  onRefresh,
  onDeploy,
  onExplain,
  onReport,
  onConfigure,
  dateRange,
  startingCash,
  pendingRun,
  onRan,
  onRecommend,
}: {
  fleet: Fleet | null;
  problem: string;
  window: number;
  tier: 'A' | 'B';
  universe: string;
  instruments: string[];
  /** The asset class a run will use. Chosen in the Backtest dialog, shown here
   * so the selection bar cannot claim a run over the wrong panel. */
  runClass: string;
  onRefresh: () => void;
  onDeploy: (strategy: FleetStrategy) => void;
  onExplain: (strategy: string) => void;
  onReport: (strategy: FleetStrategy) => void;
  /** Opens the one backtest dialog, for a row or for the whole selection. */
  onConfigure: (strategies: FleetStrategy[]) => void;
  /** Ids the Backtest dialog just confirmed. Run once, then cleared. */
  /** An explicit window, empty for "the last N days". */
  dateRange: { start: string; end: string };
  startingCash: number;
  pendingRun: string[];
  onRan: () => void;
  /** Fills the backtest controls with a strategy's own setting when it is opened (ADR-143). */
  onRecommend?: (setting: Recommended) => void;
}) {
  const [query, setQuery] = useState('');
  const [assetClass, setAssetClass] = useState('');
  const [sort, setSort] = useState<Sort>('verdict');
  const [descending, setDescending] = useState(true);
  const [style, setStyle] = useState<Style>('');
  const [source, setSource] = useState<Source>('');
  const [verdict, setVerdict] = useState<StrategyVerdict | ''>('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  // What the running job last said, and when it started. A row that only says
  // "running…" gives the operator nothing to judge by — a scan that will take
  // two seconds and one that will take two minutes look identical, so the wait
  // feels unbounded either way.
  const [progress, setProgress] = useState('');
  const [startedAt, setStartedAt] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startedAt) return;
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - startedAt) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);
  const [note, setNote] = useState('');
  const [failure, setFailure] = useState('');
  // Archived strategies are put away, not deleted: hidden unless asked for,
  // with their results and trials untouched (ADR-069).
  const [showArchived, setShowArchived] = useState(false);
  const [lastArchive, setLastArchive] = useState<{ ids: string[]; archived: boolean } | null>(null);

  // Fetched once for the table rather than per row: one sweep document covers
  // every strategy, and twenty components each asking for it would be twenty
  // requests for one file.
  const [sweeps, setSweeps] = useState<Map<string, OptimizeRow>>(new Map());
  const [sweeping, setSweeping] = useState(false);
  useEffect(() => {
    let live = true;
    // Polled while a sweep is in flight so finished strategies appear as they
    // land, rather than all twenty arriving half an hour later. The interval
    // is cleared as soon as the run reports complete, so a settled library
    // makes exactly one request.
    let timer: number | undefined;
    const read = () => {
      api
        .optimize()
        .then((data) => {
          if (!live || !data.ran) return;
          setSweeps(new Map(data.rows.map((row) => [row.strategy_id, row])));
          const running = data.complete === false;
          setSweeping(running);
          if (!running && timer) {
            window.clearInterval(timer);
            timer = undefined;
          }
        })
        .catch(() => {
          // A missing sweep is a normal state — nothing has been swept yet —
          // so it leaves the map empty rather than surfacing an error the
          // reader cannot act on.
        });
    };

    read();
    timer = window.setInterval(read, 15_000);
    return () => {
      live = false;
      if (timer) window.clearInterval(timer);
    };
  }, []);

  // Markets, not declared classes. Built from `asset_class` alone this listed
  // exactly two — equity and crypto — because those are the only tags any
  // strategy carries, so US equity and FX had no way in from here at all.
  const classes = useMemo(() => {
    const present = new Set((fleet?.strategies ?? []).map(homeMarket));
    return ASSET_CLASSES.filter((option) => present.has(option.value));
  }, [fleet]);

  const rows = useMemo(() => {
    if (!fleet) return [];
    const needle = query.trim().toLowerCase();
    const filtered = fleet.strategies.filter((s) => {
      if (inArchive(s) !== showArchived) return false;
      if (assetClass && homeMarket(s) !== assetClass) return false;
      if (style && styleOf(s) !== style) return false;
      if (source && sourceOf(s) !== source) return false;
      if (verdict && verdictOf(s) !== verdict) return false;
      if (!needle) return true;
      return [s.id, s.title, s.kind, s.shape, s.summary, s.source].some((field) =>
        field.toLowerCase().includes(needle)
      );
    });

    // Unmeasured always sorts last, never as zero: null means nobody looked.
    const value = (s: FleetStrategy): number | null => {
      switch (sort) {
        case 'annual':
          return annualOf(s);
        case 'drawdown':
          return s.result.max_drawdown ?? null;
        case 'sharpe':
          return s.sharpe;
        case 'win':
          return s.table?.win_rate ?? null;
        case 'trades':
          return s.table?.trades ?? null;
        default:
          return null;
      }
    };
    const ordered = [...filtered];
    if (sort === 'name') {
      ordered.sort((a, b) => (descending ? -1 : 1) * b.title.localeCompare(a.title));
    } else if (sort === 'verdict') {
      ordered.sort(
        (a, b) =>
          VERDICT_ORDER[verdictOf(a)] - VERDICT_ORDER[verdictOf(b)] ||
          (b.sharpe ?? -Infinity) - (a.sharpe ?? -Infinity)
      );
    } else {
      ordered.sort((a, b) => {
        const x = value(a);
        const y = value(b);
        if (x === null && y === null) return a.title.localeCompare(b.title);
        if (x === null) return 1;
        if (y === null) return -1;
        return descending ? y - x : x - y;
      });
    }
    return ordered;
  }, [fleet, query, assetClass, style, source, verdict, sort, descending, showArchived]);

  const sortBy = useCallback(
    (next: Sort) => {
      if (next === sort) setDescending((d) => !d);
      else {
        setSort(next);
        setDescending(next !== 'drawdown' && next !== 'name');
      }
    },
    [sort]
  );
  const openStrategy = useMemo(
    () => (open ? (fleet?.strategies.find((s) => s.id === open) ?? null) : null),
    [open, fleet]
  );

  // Opening a strategy with a recommended setting fills the backtest controls
  // with it, so a run from here repeats the stored full-history run.
  const recommendedFor = openStrategy?.recommended;
  useEffect(() => {
    if (recommendedFor && onRecommend) onRecommend(recommendedFor);
    // Only when a different strategy opens, not on every fleet refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openStrategy?.id]);

  const archivedCount = useMemo(() => (fleet?.strategies ?? []).filter(inArchive).length, [fleet]);
  // Leaving the archive view when the last one is restored, so the page does
  // not sit on an empty list.
  useEffect(() => {
    if (showArchived && fleet && archivedCount === 0) setShowArchived(false);
  }, [showArchived, fleet, archivedCount]);

  const setArchived = useCallback(
    async (ids: string[], archived: boolean, undo = false) => {
      if (ids.length === 0) return;
      setFailure('');
      try {
        const done = await api.archiveStrategies(ids, archived);
        if (!done.ok) {
          setFailure(done.error);
          return;
        }
        setLastArchive(undo ? null : { ids, archived });
        setNote('');
        setSelected((prev) => {
          const next = new Set(prev);
          for (const id of ids) next.delete(id);
          return next;
        });
        setOpen((current) => (current && ids.includes(current) ? null : current));
        onRefresh();
      } catch (error) {
        setFailure(error instanceof Error ? error.message : String(error));
      }
    },
    [onRefresh]
  );

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // A strategy that cannot be run can still be selected, to archive it; only
  // the runnable part of a selection is offered to the Backtest dialog.
  const runnableSelected = useMemo(
    () => (fleet?.strategies ?? []).filter((s) => selected.has(s.id) && s.runnable),
    [fleet, selected]
  );

  const backtest = useCallback(
    async (ids: string[]) => {
      setFailure('');
      setBusy((prev) => new Set([...prev, ...ids]));
      setStartedAt(Date.now());
      setElapsed(0);
      setProgress('starting');
      try {
        const result = await runBatch(
          ids,
          days,
          tier,
          universe,
          instruments,
          runClass,
          (message) => {
            setNote(message);
            setProgress(message);
          },
          { start: dateRange.start, end: dateRange.end, startingCash },
        );
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
        setStartedAt(0);
        setProgress('');
      }
    },
    [days, tier, universe, instruments, runClass, dateRange, startingCash, onRefresh]
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
        {/* Labelled, not raw ids: the chips read "US equities" and "FX"
            rather than "us" and "fx", which is what the rest of the console
            calls them. */}
        {classes.map((option) => (
          <button
            key={option.value}
            className="tchip"
            type="button"
            aria-pressed={assetClass === option.value}
            onClick={() => setAssetClass(assetClass === option.value ? '' : option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="st-filters">
        <ChipGroup
          label="Style"
          value={style}
          onChange={(v) => setStyle(v as Style)}
          options={[
            { value: 'intraday', label: 'Intraday' },
            { value: 'daily', label: 'Daily' },
          ]}
        />
        <ChipGroup
          label="Source"
          value={source}
          onChange={(v) => setSource(v as Source)}
          options={(['paper', 'builder', 'coded'] as const).map((v) => ({ value: v, label: SOURCE_LABEL[v] }))}
        />
        <ChipGroup
          label="Verdict"
          value={verdict}
          onChange={(v) => setVerdict(v as StrategyVerdict | '')}
          options={VERDICTS.map((v) => ({ value: v.value, label: v.label }))}
        />
        <Info label="What the filters mean">
          {VERDICTS.map((v) => `${v.label}: ${v.hint}`).join(' ')}{' '}
          {classes
            .filter((option) => option.note)
            .map((option) => `${option.label}: ${option.note}`)
            .join(' ')}{' '}
          Archived: strategies you have put away, and every strategy with no stored backtest
          report yet. Those come back to the main list by themselves once a backtest
          writes their report (ADR-207). Results and trials are kept.
        </Info>
        {(archivedCount > 0 || showArchived) && (
          <div className="st-chips" role="group" aria-label="Archive">
            <button
              className="tchip sm"
              type="button"
              aria-pressed={showArchived}
              onClick={() => {
                setShowArchived((v) => !v);
                setSelected(new Set());
                setOpen(null);
              }}
            >
              Archived {archivedCount}
            </button>
          </div>
        )}
      </div>

      {lastArchive && (
        <div className="trunning st-undo" role="status">
          <span>
            {lastArchive.archived ? 'Archived' : 'Restored'} {lastArchive.ids.length}{' '}
            {lastArchive.ids.length === 1 ? 'strategy' : 'strategies'}.

          </span>
          <button className="tbtn sm" type="button" onClick={() => void setArchived(lastArchive.ids, !lastArchive.archived, true)}>
            Undo
          </button>
          <button className="ticon sm" type="button" aria-label="Dismiss" onClick={() => setLastArchive(null)}>
            ×
          </button>
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

      <div className="st-wrap">
        <table className="st-table">
          <thead>
            <tr>
              <th className="st-sel" aria-label="Select" />
              <SortHead label="Strategy" sort="name" current={sort} descending={descending} onSort={sortBy} align="left" />
              <th className="st-spark">Equity</th>
              <SortHead label="Annual return" sort="annual" current={sort} descending={descending} onSort={sortBy} />
              <th>
                Nifty, same period
                <Info align="right">
                  NIFTYBEES held over the same period, before costs. Annual return and Sharpe are the
                  strategy&apos;s latest run after costs; the bar under Sharpe is drawn against the noise
                  bar a strategy must clear. Max drawdown is the deepest fall from a peak.
                </Info>
              </th>
              <SortHead label="Max drawdown" sort="drawdown" current={sort} descending={descending} onSort={sortBy} />
              <SortHead label="Sharpe" sort="sharpe" current={sort} descending={descending} onSort={sortBy} />
              <SortHead label="Win rate" sort="win" current={sort} descending={descending} onSort={sortBy} />
              <SortHead label="Trades" sort="trades" current={sort} descending={descending} onSort={sortBy} />
              <SortHead label="Verdict" sort="verdict" current={sort} descending={descending} onSort={sortBy} align="left" />
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {fleet &&
              rows.map((strategy) => {
                const v = verdictOf(strategy);
                const t = strategy.table;
                const running = busy.has(strategy.id);
                return (
                  <tr
                    key={strategy.id}
                    className="st-row"
                    data-open={open === strategy.id}
                    tabIndex={0}
                    onClick={() => setOpen(open === strategy.id ? null : strategy.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') setOpen(open === strategy.id ? null : strategy.id);
                    }}
                  >
                    <td className="st-sel" onClick={(event) => event.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selected.has(strategy.id)}
                        onChange={() => toggle(strategy.id)}
                        aria-label={`Select ${strategy.title}`}
                      />
                    </td>
                    <td className="st-name">
                      <b>{strategy.title}</b>
                      <span>
                        {assetClassLabel(homeMarket(strategy))} ·{' '}
                        {styleOf(strategy) === 'intraday' ? 'intraday' : 'daily'} · {SOURCE_LABEL[sourceOf(strategy)].toLowerCase()}
                      </span>
                    </td>
                    <td className="st-spark">
                      {running ? (
                        <span className="tdim">{progress ? shortProgress(progress) : 'running'} {elapsed > 0 ? `${elapsed}s` : ''}</span>
                      ) : (
                        <Spark
                          curve={strategy.adopted ? strategy.adopted.curve : strategy.result.curve}
                          clears={strategy.clears_bar}
                          title={curveTitle(strategy)}
                          width={96}
                          height={26}
                        />
                      )}
                    </td>
                    <td className="num">
                      <Move value={annualOf(strategy)} text={pct(annualOf(strategy))} />
                    </td>
                    <td className="num tdim">{pct(t?.nifty_return ?? null, 0)}</td>
                    <td className={`num ${strategy.result.max_drawdown ? 'neg' : ''}`}>{pct(strategy.result.max_drawdown ?? null, 0)}</td>
                    <td className="num st-sharpe">
                      {strategy.sharpe === null ? (
                        '—'
                      ) : (
                        <>
                          <b>{strategy.sharpe.toFixed(2)}</b>
                          <Bar
                            value={strategy.sharpe}
                            max={Math.max(fleet.bar, 0.01)}
                            tone={strategy.sharpe >= fleet.bar ? 'up' : strategy.sharpe > 0 ? 'accent' : 'down'}
                          />
                        </>
                      )}
                    </td>
                    <td className="num">{t?.win_rate === null || t?.win_rate === undefined ? '—' : `${(t.win_rate * 100).toFixed(0)}%`}</td>
                    <td className="num">{t?.trades ?? strategy.result.fills ?? '—'}</td>
                    <td>
                      <span className={`st-verdict v-${v}`}>
                        {VERDICTS.find((x) => x.value === v)?.label}
                      </span>
                    </td>
                    <td className="st-act" onClick={(event) => event.stopPropagation()}>
                      <button
                        className="tbtn sm"
                        type="button"
                        disabled={running || !strategy.runnable}
                        onClick={() => onConfigure([strategy])}
                      >
                        {running ? '…' : 'Backtest'}
                      </button>
                      <button
                        className="tbtn sm ghost-line"
                        type="button"
                        disabled={!!strategy.deploy_blocker || !!belowPaperFloor(strategy)}
                        onClick={() => onDeploy(strategy)}
                        title={
                          strategy.deploy_blocker
                            ? `Cannot paper-trade: ${strategy.deploy_blocker}`
                            : belowPaperFloor(strategy) || 'Put it on paper trading'
                        }
                      >
                        Deploy
                      </button>
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
        {fleet && rows.length === 0 && (
          <div className="tempty">{showArchived ? 'No archived strategy matches those filters.' : 'Nothing matches those filters.'}</div>
        )}
        {!fleet && !problem && <div className="tempty">Reading the registry…</div>}
      </div>

      {openStrategy && fleet && (
        <aside className="st-drawer" aria-label={`${openStrategy.title} details`}>
          <div className="st-drawer-head">
            <div>
              <h2>
                {openStrategy.title}
                {openStrategy.summary && <Info label="What this strategy is">{openStrategy.summary}</Info>}
              </h2>
              <span className={`st-verdict v-${verdictOf(openStrategy)}`}>
                {VERDICTS.find((x) => x.value === verdictOf(openStrategy))?.label}
              </span>
            </div>
            <button className="ticon" type="button" aria-label="Close" onClick={() => setOpen(null)}>
              ×
            </button>
          </div>
          <div className="st-stats">
            <Fact label="Annual return" value={pct(annualOf(openStrategy))} />
            <Fact label="Nifty, same period" value={pct(openStrategy.table?.nifty_return ?? null, 0)} />
            <Fact label="Total return" value={pct(openStrategy.result.total_return ?? null, 0)} />
            <Fact label="Max drawdown" value={pct(openStrategy.result.max_drawdown ?? null, 0)} />
            <Fact label="Sharpe" value={openStrategy.sharpe === null ? '—' : `${openStrategy.sharpe.toFixed(2)} (bar ${fleet.bar.toFixed(2)})`} />
            <Fact label="Period" value={openStrategy.table?.period?.[0] ? `${openStrategy.table.period[0]} → ${openStrategy.table.period[1]}` : '—'} />
          </div>
          <div className="st-drawer-actions">
            <button className="tbtn go" type="button" disabled={!openStrategy.runnable || busy.has(openStrategy.id)} onClick={() => onConfigure([openStrategy])}>
              Backtest
            </button>
            <button className="tbtn" type="button" disabled={openStrategy.sharpe === null} onClick={() => onReport(openStrategy)}>
              Full report
            </button>
            <button className="tbtn" type="button" onClick={() => onExplain(openStrategy.id)}>
              How it works
            </button>
            <button
              className="tbtn ghost-line"
              type="button"
              disabled={!!openStrategy.deploy_blocker || !!belowPaperFloor(openStrategy)}
              onClick={() => onDeploy(openStrategy)}
              title={
                openStrategy.deploy_blocker
                  ? `Cannot paper-trade: ${openStrategy.deploy_blocker}`
                  : belowPaperFloor(openStrategy) || 'Put it on paper trading'
              }
            >
              Deploy
            </button>
            <button
              className="tbtn"
              type="button"
              title={
                openStrategy.archived
                  ? 'Bring it back to the main list.'
                  : 'Hide it from the main list. Results, trials and any deployment are kept; you can restore it.'
              }
              onClick={() => void setArchived([openStrategy.id], !openStrategy.archived)}
            >
              {openStrategy.archived ? 'Restore' : 'Archive'}
            </button>
          </div>
          {openStrategy.logic && openStrategy.logic.length > 0 && (
            <section className="st-rules">
              <h3>The rules</h3>
              <ol>
                {openStrategy.logic.map((line, index) => (
                  // Position in the key: two configurations can share a line.
                  <li key={`${index}-${line}`}>{line}</li>
                ))}
              </ol>
            </section>
          )}
          <TuningPanel key={openStrategy.id} strategyId={openStrategy.id} />
          <Row
            strategy={openStrategy}
            sweep={sweeps.get(openStrategy.id)}
            sweeping={sweeping}
            bar={fleet.bar}
            checked={false}
            open
            detailOnly
            busy={busy.has(openStrategy.id)}
            progress=""
            elapsed={0}
            onToggle={() => undefined}
            onOpen={() => undefined}
            onBacktest={() => onConfigure([openStrategy])}
            onDeploy={() => onDeploy(openStrategy)}
            onExplain={() => onExplain(openStrategy.id)}
            onReport={() => onReport(openStrategy)}
          />
        </aside>
      )}

      {selected.size > 0 && (
        <div className="tsel">
          <b>{selected.size}</b> selected
          <Info>Instruments, period and capital are chosen in the next step.</Info>
          <button className="tbtn ghost" type="button" onClick={() => setSelected(new Set())}>
            Clear
          </button>
          <button className="tbtn" type="button" onClick={() => void setArchived([...selected], !showArchived)}>
            {showArchived ? `Restore ${selected.size}` : `Archive ${selected.size}`}
          </button>
          {runnableSelected.length > 0 && (
            <button
              className="tbtn"
              type="button"
              disabled={busy.size > 0}
              onClick={() => onConfigure(runnableSelected)}
            >
              {busy.size > 0 ? 'Running…' : `Backtest ${runnableSelected.length}`}
            </button>
          )}
        </div>
      )}
    </>
  );
}


/**
 * The one thing worth saying about how this result was produced.
 *
 * Ordered by how surprising it is, and only the most surprising is shown. A
 * signal that wins on a market its paper never tested is the finding a reader
 * would otherwise have to open two drawers to notice; that it also happens to
 * be tuned is a detail, and it lives in the tooltip.
 *
 * Returns empty when nothing about the provenance is unusual, and the row then
 * carries no chip at all.
 */
/** The job message, trimmed to what fits in a table cell.
 *
 * Messages read like "scanned 3/12 — RELIANCE" or "loading the panel". The
 * counter is the part worth keeping when there is no room: it is the only piece
 * that says how much is left. */
function shortProgress(message: string): string {
  const counted = message.match(/(\d+\/\d+)/);
  if (counted) return counted[1];
  return message.length > 18 ? `${message.slice(0, 17)}…` : message;
}

function provenance(strategy: FleetStrategy, sweep: OptimizeRow | undefined): string {
  const best = strategy.best_asset;
  if (best && best.beats > 1 && best.is_away) return `wins on ${best.symbol} ↗`;
  if (strategy.walk && strategy.walk.pbo > 0.25 && !strategy.walk.most_settings_work) {
    return 'overfitting risk';
  }
  if (strategy.adopted?.adopted) return 'tuned';
  if (strategy.adopted && sweep) return 'paper params';
  return '';
}

function provenanceTone(strategy: FleetStrategy): string {
  const best = strategy.best_asset;
  if (best && best.is_away && best.sharpe > 0) return 'sweep-tag on';
  if (strategy.walk && strategy.walk.pbo > 0.25 && !strategy.walk.most_settings_work) {
    return 'sweep-tag off';
  }
  return '';
}

/** Everything the chip does not have room for, in one sentence per fact. */
function provenanceDetail(strategy: FleetStrategy, sweep: OptimizeRow | undefined): string {
  const parts: string[] = [];
  const best = strategy.best_asset;
  if (best && best.beats > 1) {
    parts.push(
      best.is_away
        ? `Does best on ${best.symbol} (Sharpe ${best.sharpe.toFixed(2)}) — not the market its paper tested.`
        : `Does best on ${best.symbol}, the market its paper tested.`,
    );
  }
  if (strategy.adopted?.adopted) {
    parts.push(`Running the best of ${sweep?.candidates ?? 9} settings from a recorded sweep.`);
  } else if (sweep) {
    parts.push(`Swept ${sweep.candidates} settings; none beat the published parameters.`);
  }
  if (strategy.walk) parts.push(strategy.walk.verdict);
  if (strategy.engine === 'intraday') {
    parts.push('Runs on minute bars; cannot be expressed as target weights (ADR-037).');
  }
  if (strategy.engine === 'study') {
    parts.push(
      'A paper coded as a study and run by its own make target (see the last step); every published setting is stored here, after costs. It cannot be run from this page.',
    );
  }
  if (strategy.engine === 'overnight') {
    parts.push('Holds a future from the close to the next open; run as a calculation, not by an engine.');
  }
  return parts.join(' ');
}

function Row({
  strategy,
  sweep,
  sweeping,
  progress,
  elapsed,
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
  detailOnly = false,
}: {
  /** Only the detail panel, for the side drawer; the table row is drawn elsewhere. */
  detailOnly?: boolean;
  strategy: FleetStrategy;
  sweep: OptimizeRow | undefined;
  sweeping: boolean;
  /** What the running job last reported, empty when this row is not running. */
  progress: string;
  /** Seconds since the batch started. Shown because an unbounded wait and a
   *  ten-second one feel identical without it. */
  elapsed: number;
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
  const runnable = strategy.runnable;
  const ranOn = result.asset_class;
  return (
    <div className={detailOnly ? 'trow st-detail' : 'trow'} data-open={open}>
      {!detailOnly && (
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
            {/* One provenance chip, not five.
             *
             * The row carried PBO, "tuned", "best: QQQ", "intraday" and the
             * market — five chips saying three things, with the market stated
             * three times over between them and the columns to the right. Five
             * pieces of provenance competing with one number is a row nobody
             * reads; the reader wants the number, and provenance only when
             * something about it is unusual.
             *
             * So it collapses to a single chip reading like a phrase, with the
             * full detail in its tooltip — and the chip only appears when there
             * is something to say. A strategy running published parameters, on
             * its paper's market, with unremarkable overfitting risk gets no
             * chip at all, which is the correct amount of attention for the
             * unremarkable case. */}
            {provenance(strategy, sweep) && (
              <span
                className={`ttag ${provenanceTone(strategy)}`}
                title={provenanceDetail(strategy, sweep)}
              >
                {provenance(strategy, sweep)}
              </span>
            )}
            {!runnable && (
              <span
                className="tflag"
                title="Cannot satisfy the Strategy interface and has no intraday implementation (ADR-037)."
              >
                not runnable
              </span>
            )}
          </div>
        </div>
        <div className="tmeta">
          {/* The class the result was RUN on, not the one the strategy is
              declared for. They can differ — buy_and_hold is declared equity and
              its latest run was 20 crypto pairs — and a crypto Sharpe sitting
              under an "equity" tag is the same quiet mismatch the graph tooltip
              already guards against. */}
          {/* The market the *displayed* result came from. For a swept strategy
              that is the adopted run's market, not the daily store's: the row
              was showing "equity · nifty50" beside a QQQ result, because the
              tag and the number came from different runs. */}
          <Tag
            title={
              strategy.adopted
                ? `This result was run on ${strategy.adopted.symbol} (${strategy.adopted.market}), the market its paper tested.`
                : ranOn && ranOn !== strategy.asset_class
                  ? `Declared for ${strategy.asset_class}; this result was run on ${ranOn}.`
                  : undefined
            }
          >
            {strategy.adopted ? strategy.adopted.market : ranOn || strategy.asset_class}
          </Tag>
          {result.cost_mode === 'replication' && (
            <span
              className="tflag"
              title="No cost model covers that asset class, so this figure is gross of costs and not comparable to a net one."
            >
              no costs
            </span>
          )}
          {strategy.adopted && (
            <Tag
              title={
                `Run on ${strategy.adopted.symbol} over ${strategy.adopted.sessions} sessions ` +
                `with ${strategy.adopted.fills} fills, on the parameters this strategy now uses.`
              }
            >
              {strategy.adopted.net_pnl >= 0 ? '+' : ''}
              {money(strategy.adopted.net_pnl, strategy.adopted.market)}
            </Tag>
          )}
          {strategy.adopted ? (
            <Tag
              title={`${strategy.adopted.sessions} sessions, ${strategy.adopted.fills} fills.`}
            >
              {strategy.adopted.symbol} · {strategy.adopted.sessions}d
            </Tag>
          ) : result.universe ? (
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
            <span className="trunprog" title={progress}>
              {/* The job's own message rather than a spinner. The API already
                  reports which symbol it is scanning and how far through it is;
                  the row was throwing that away and showing "running…". */}
              <b>{progress ? shortProgress(progress) : 'running'}</b>
              <span className="tdim">{elapsed > 0 ? ` ${elapsed}s` : ''}</span>
            </span>
          ) : (
            /* The adopted run's own equity path where there is one. The stored
               curve belongs to the daily engine and, for a swept intraday
               signal, is an NSE run under the published parameters — a picture
               of a different strategy on a different market than the number
               beside it. */
            <Spark
              curve={strategy.adopted ? strategy.adopted.curve : result.curve}
              clears={strategy.clears_bar}
              title={
                strategy.adopted
                  ? `Cumulative P&L on ${strategy.adopted.symbol} over ${strategy.adopted.sessions} sessions, on the parameters this strategy now uses.`
                  : curveTitle(strategy)
              }
            />
          )}
        </div>
        {/* For a swept strategy the headline is the run on the parameters it
            actually uses, and `runs` is that sweep's grid size — the count the
            number was the best of, which is what makes it readable. Falling
            back to the daily engine's run count would attach the wrong
            denominator to the right number. */}
        <SharpeCell
          sharpe={strategy.sharpe}
          bar={bar}
          runs={strategy.adopted ? (sweep?.candidates ?? result.runs) : result.runs}
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
      )}

      {open && (
        <div className="tdetail">
          <div>
            <p className="tdesc">{strategy.summary}</p>
            {/* The strategy's own result first, then the sweep that chose its
                parameters. The grid is evidence for the parameter, not the
                result of the strategy, and leading with it answered "which
                setting won" to a reader asking "what does this do". */}
            {strategy.adopted && <AdoptedReport result={strategy.adopted} bar={bar} />}
            {/* Shown only when it is a different measurement. For a strategy
                already measured on QQQ the two rows are the same run, and
                printing it twice would suggest two pieces of evidence where
                there is one. `orb_in_play` is the case that makes this worth
                checking: measured on SPY at home, and a different number on
                QQQ. */}
            {strategy.on_us &&
              (strategy.adopted?.symbol !== strategy.on_us.symbol ||
                strategy.adopted?.market !== strategy.on_us.market) && (
                <AdoptedReport
                  result={strategy.on_us}
                  bar={bar}
                  heading="Also tested on US equity"
                  note={
                    strategy.adopted
                      ? `Its paper tested ${strategy.adopted.market === 'crypto' ? 'crypto' : strategy.adopted.market}, and this is the same signal on QQQ — a different question from the run above, and the only US evidence for it.`
                      : undefined
                  }
                />
              )}
            {/* After the sweep it judges, and before the facts: the sweep says
                what was chosen, this says whether choosing that way holds up. */}
            {strategy.walk && <WalkPanel walk={strategy.walk} />}
            {sweep && <SweepPanel row={sweep} running={sweeping} />}
            {/* Facts about the run shown above it, never a second run's.
                This grid used to read straight from the daily result store, so
                a QQQ report with 20 fills over 58 sessions sat directly above
                "nifty50 · 179 fills · 90d · −7.1%" — two complete, contradicting
                accounts of one strategy, both presented as fact. Duplicated
                "Universe" and "Instruments"/"Names traded" pairs came from the
                same drift and are gone. */}
            <div className="tfacts">
              <Fact label="Evidence" value={<EvidenceBadge stage={strategy.stage} />} />
              {strategy.adopted ? (
                <>
                  <Fact label="Settings tried" value={sweep?.candidates ?? '—'} />
                  <Fact
                    label="Parameters"
                    value={strategy.adopted.adopted ? 'tuned' : "paper's"}
                  />
                  <Fact label="Market" value={strategy.adopted.market} />
                  <Fact label="Instrument" value={strategy.adopted.symbol} />
                  <Fact label="Costs" value="realistic" />
                  <Fact label="Trials spent" value={sweep?.candidates ?? '—'} />
                  {/* The account is a million units of whatever the prices are
                      quoted in, so the label follows the market. "₹10L" on a
                      QQQ run is wrong by the exchange rate. */}
                  <Fact
                    label={`Return on ${currencySymbol(strategy.adopted.market)}1M`}
                    value={fmtPct(strategy.adopted.net_pnl / 1_000_000)}
                  />
                  <Fact
                    label="Max drawdown"
                    value={fmtPct(strategy.adopted.max_drawdown / 1_000_000)}
                  />
                  <Fact label="Fills" value={strategy.adopted.fills} />
                  <Fact label="Sessions" value={strategy.adopted.sessions} />
                  <Fact label="Window" value={`${strategy.adopted.start} → ${strategy.adopted.end}`} />
                </>
              ) : (
                <>
                  <Fact label="Configurations" value={result.runs || '—'} />
                  <Fact
                    label="Best of them"
                    value={
                      result.best_sharpe !== null && result.best_sharpe !== undefined
                        ? result.best_sharpe.toFixed(2)
                        : '—'
                    }
                  />
                  <Fact label="Asset class" value={result.asset_class || '—'} />
                  <Fact
                    label="Costs"
                    value={result.cost_mode === 'replication' ? 'not modelled' : 'realistic'}
                  />
                  <Fact label="Universe" value={result.universe || '—'} />
                  <Fact label="Instruments" value={result.symbols ?? '—'} />
                  <Fact label="Trials" value={strategy.trials} />
                  <Fact label="Total return" value={fmtPct(result.total_return)} />
                  <Fact label="Max drawdown" value={fmtPct(result.max_drawdown)} />
                  <Fact label="Fills" value={result.fills ?? '—'} />
                  <Fact label="Window" value={result.window_days ? `${result.window_days}d` : '—'} />
                </>
              )}
              <Fact label="Engine" value={strategy.engine} />
              <Fact label="Lookback" value={`${strategy.lookback}d`} />
              <Fact label="Risk manager" value={strategy.risk_manager || '—'} />
              <Fact label="Trade manager" value={strategy.trade_manager || '—'} />
            </div>
          </div>
          <div className="tside">
            {/* Opens the stored run — whatever was last executed from this
                interface, which for a swept strategy is a *different*
                measurement from the adopted report above it.

                This was disabled for adopted strategies, on the reasoning that
                the report above is the strategy's real result. That reasoning
                stranded the operator: running a backtest from this dialog
                stored the run and left no way to open it. A result someone
                explicitly asked for has to be reachable, whatever else the row
                is showing. */}
            <button
              className="tbtn go"
              type="button"
              disabled={strategy.sharpe === null && !result.runs}
              onClick={onReport}
              title={
                strategy.adopted
                  ? 'The last run executed from this interface — a different measurement from the report above, and possibly on a different market.'
                  : strategy.sharpe === null
                    ? 'Never run, so there is nothing to report on.'
                    : 'Per-instrument attribution, the order ledger, and every metric.'
              }
            >
              {strategy.adopted ? 'Last run' : 'Full analysis'}
            </button>
            {strategy.adopted ? (
              <div className="tcaveat">
                <h4>What this number is not</h4>
                {strategy.adopted.sessions} sessions and {strategy.adopted.fills} fills is a
                short record, and the parameters were chosen by a search over{' '}
                {sweep?.candidates ?? 9} settings on this same window. The bar it is drawn
                against has been charged for that search, which is what makes the comparison
                meaningful — but nothing here has been tested out of sample.
              </div>
            ) : (
              result.caveat && (
                <div className="tcaveat">
                  <h4>What this number is not</h4>
                  {result.caveat}
                </div>
              )
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
  const gross =
    result.cost_mode === 'replication'
      ? ', gross of costs because no cost model covers that class'
      : '';
  const base =
    `Most recent backtest: Sharpe ${result.sharpe.toFixed(2)}` +
    (result.asset_class && result.asset_class !== strategy.asset_class
      ? ` on ${result.asset_class}`
      : '') +
    (result.window_days ? ` over ${result.window_days} trading days` : '') +
    (result.universe ? ` on ${result.universe}` : '') +
    (result.symbols ? `, ${result.symbols} instruments` : '') +
    (result.tier ? `, tier ${result.tier}` : '') +
    gross;
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

function SortHead({
  label,
  sort,
  current,
  descending,
  onSort,
  align = 'right',
}: {
  label: string;
  sort: Sort;
  current: Sort;
  descending: boolean;
  onSort: (sort: Sort) => void;
  align?: 'left' | 'right';
}) {
  const active = current === sort;
  return (
    <th className={align === 'left' ? 'l' : 'r'} aria-sort={active ? (descending ? 'descending' : 'ascending') : 'none'}>
      <button type="button" className="st-sort" onClick={() => onSort(sort)}>
        {label}
        <span aria-hidden="true">{active ? (descending ? ' ↓' : ' ↑') : ''}</span>
      </button>
    </th>
  );
}

function ChipGroup({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string; title?: string }[];
}) {
  return (
    <div className="st-chips" role="group" aria-label={label}>
      <span className="st-chips-label">{label}</span>
      <button className="tchip sm" type="button" aria-pressed={value === ''} onClick={() => onChange('')}>
        All
      </button>
      {options.map((option) => (
        <button
          key={option.value}
          className="tchip sm"
          type="button"
          title={option.title}
          aria-pressed={value === option.value}
          onClick={() => onChange(value === option.value ? '' : option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
