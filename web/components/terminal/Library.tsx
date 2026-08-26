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
import { AdoptedReport } from '@/components/terminal/AdoptedReport';
import { SweepPanel } from '@/components/terminal/SweepPanel';
import { WalkPanel } from '@/components/terminal/WalkPanel';
import { UniversePicker } from '@/components/terminal/UniversePicker';
import { api } from '@/lib/api';
import { runBatch } from '@/lib/run';
import type { Fleet, FleetStrategy, OptimizeRow } from '@/lib/api';

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
  runClass,
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
  /** The asset class a run will use. Chosen in the Backtest dialog, shown here
   * so the selection bar cannot claim a run over the wrong panel. */
  runClass: string;
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
        const result = await runBatch(ids, days, tier, universe, instruments, runClass, setNote);
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
    [days, tier, universe, instruments, runClass, onRefresh]
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
        <label
          className="tsort"
          title="Ranking a library by return and taking the top row is the selection procedure the overfitting test measures. The bar, not the order, is what decides anything."
        >
          Sort
          <select value={sort} onChange={(event) => setSort(event.target.value as Sort)}>
            <option value="evidence">Evidence</option>
            <option value="name">Name</option>
            <option value="sharpe">Sharpe</option>
          </select>
        </label>
      </div>

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
              sweep={sweeps.get(strategy.id)}
              sweeping={sweeping}
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
            {runClass !== 'equity' ? `${runClass} · ` : ''}
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
  sweep,
  sweeping,
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
  sweep: OptimizeRow | undefined;
  sweeping: boolean;
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
            {strategy.walk && (
              <span
                className={`ttag ${strategy.walk.pbo <= 0.25 || strategy.walk.most_settings_work ? 'sweep-tag on' : 'sweep-tag off'}`}
                title={strategy.walk.verdict}
              >
                PBO {strategy.walk.pbo.toFixed(2)}
              </span>
            )}
            {strategy.adopted?.adopted && (
              <span
                className="ttag sweep-tag on"
                title={
                  `Running the best of ${sweep?.candidates ?? 9} settings, chosen by a recorded sweep ` +
                  `on ${strategy.adopted.symbol}. Open the row for the full report.`
                }
              >
                tuned
              </span>
            )}
            {/* Which market this signal actually does best on. Shown on the
                row because the alternative is opening the drawer and comparing
                two panels — and the case that matters most, a signal that wins
                somewhere other than its paper's market, is exactly the one
                nobody opens the drawer to look for. */}
            {strategy.best_asset && strategy.best_asset.beats > 1 && (
              <span
                className={`ttag assettag-best ${strategy.best_asset.sharpe > 0 ? 'on' : 'off'}`}
                title={
                  strategy.best_asset.is_away
                    ? `Best on ${strategy.best_asset.symbol} — not the market its paper tested. Sharpe ${strategy.best_asset.sharpe.toFixed(2)} there.`
                    : `Best on ${strategy.best_asset.symbol}, the market its paper tested. Sharpe ${strategy.best_asset.sharpe.toFixed(2)}.`
                }
              >
                best: {strategy.best_asset.symbol}
                {strategy.best_asset.is_away ? ' ↗' : ''}
              </span>
            )}
            {strategy.adopted && !strategy.adopted.adopted && sweep && (
              <span
                className="ttag"
                title={
                  `Swept over ${sweep.candidates} settings on ${sweep.symbol}; none beat the ` +
                  `published parameters, which are still in use.`
                }
              >
                paper params
              </span>
            )}
            {strategy.engine === 'intraday' && (
              <span
                className="ttag"
                title="Runs on minute bars through the intraday scanner. It cannot be expressed as target weights (ADR-037), which is a different thing from not being runnable."
              >
                intraday
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
              {strategy.adopted.net_pnl < 0 ? '−' : '+'}
              {strategy.adopted.market === 'equity' ? '₹' : '$'}
              {Math.abs(Math.round(strategy.adopted.net_pnl)).toLocaleString(
                strategy.adopted.market === 'equity' ? 'en-IN' : 'en-US',
              )}
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
            <span className="tdim">running…</span>
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
                    label={
                      strategy.adopted.market === 'equity'
                        ? 'Return on ₹10L'
                        : 'Return on $1M'
                    }
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
              <Fact label="Engine" value={strategy.engine === 'intraday' ? 'intraday' : 'daily'} />
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
