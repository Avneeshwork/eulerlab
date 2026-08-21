'use client';

/**
 * The library — the terminal's primary surface.
 *
 * Built from the Robinhood reference (docs/RESEARCH/018), which contributes
 * three things: structural whitespace, a big hero number, and progressive
 * disclosure — a row shows a little and opens to show the rest.
 *
 * It contributes two things that are deliberately inverted:
 *
 *   1. **Their hero number is your money.** Ours is the noise bar. A strategy's
 *      return in that slot would be the whole design arguing that return is
 *      what matters, above every caveat on the page.
 *   2. **Their accent tracks profit.** Ours tracks evidence. Green here means
 *      "cleared the bar", never "did well".
 *
 * And one thing kept from the Bloomberg read (017): the default sort is
 * evidence, not Sharpe. Ranking a strategy library by return is the selection
 * procedure the overfitting tests measure, performed by the interface, at
 * scale, before the user has thought about it.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { CommandPalette } from '@/components/CommandPalette';
import { EvidenceBadge, SharpeCell, Tag } from '@/components/primitives';
import { api } from '@/lib/api';
import type { Fleet, FleetStrategy, RunPrice } from '@/lib/api';

type Sort = 'evidence' | 'name' | 'sharpe';

const RUNG_ORDER: Record<string, number> = {
  live: 0,
  forward_testing: 1,
  backtested: 2,
  registered: 3,
  retired: 4,
};

// Build / Run / Instruments / Live / Data are not built yet (T-3613). They are
// rendered disabled rather than omitted, because a nav that silently lacks them
// claims the product is smaller than it is; and disabled rather than
// clickable-to-nothing, because a dead link is worse than an honest one.
const NAV = [
  { label: 'Library', ready: true },
  { label: 'Build', ready: false },
  { label: 'Run', ready: false },
  { label: 'Instruments', ready: false },
  { label: 'Live', ready: false },
  { label: 'Data', ready: false },
];

export default function TerminalPage() {
  const [fleet, setFleet] = useState<Fleet | null>(null);
  const [problem, setProblem] = useState('');
  const [query, setQuery] = useState('');
  const [assetClass, setAssetClass] = useState('');
  const [sort, setSort] = useState<Sort>('evidence');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [dark, setDark] = useState<boolean | null>(null);
  const [price, setPrice] = useState<RunPrice | null>(null);

  useEffect(() => {
    api
      .fleet()
      .then(setFleet)
      .catch(() => setProblem('Cannot reach the API. Is it running on :8000?'));
  }, []);

  // Null means "follow the OS", which is the state most people are in. Only an
  // explicit choice stamps the attribute.
  useEffect(() => {
    const root = document.querySelector('.terminal');
    if (!root) return;
    if (dark === null) root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', dark ? 'dark' : 'light');
  }, [dark]);

  // ⌘K / Ctrl-K. Bloomberg's mnemonics without the keyboard: one input that
  // reaches strategies, features, papers and actions.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setPaletteOpen((isOpen) => !isOpen);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // What a run costs, priced before the click rather than after it. An
  // interface that makes running feel free is how somebody spends fifty trials
  // in an afternoon without noticing.
  useEffect(() => {
    if (selected.size === 0) {
      setPrice(null);
      return;
    }
    let live = true;
    api
      .priceRun(selected.size, 0)
      .then((quote) => live && setPrice(quote))
      .catch(() => live && setPrice(null));
    return () => {
      live = false;
    };
  }, [selected]);

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
      // included rows nobody rendered would, here, run configurations nobody
      // chose.
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const measured = fleet?.strategies.filter((s) => s.sharpe !== null).length ?? 0;
  const clearing = fleet?.strategies.filter((s) => s.clears_bar).length ?? 0;
  const trials = fleet?.strategies.reduce((sum, s) => sum + s.trials, 0) ?? 0;

  return (
    <>
      <header className="tbar">
        <span className="tbrand">
          <span className="tmark" aria-hidden="true">
            ↗
          </span>
          eulerlab
        </span>
        <nav className="tnav" aria-label="Sections">
          {NAV.map((item) => (
            <button
              key={item.label}
              type="button"
              disabled={!item.ready}
              aria-current={item.label === 'Library' ? 'page' : undefined}
              title={item.ready ? undefined : 'Not built yet (T-3613).'}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="tright">
          <span
            className="tws"
            title="Evidence, strategies and credentials are scoped to this workspace (ADR-040)."
          >
            workspace <b>default</b>
          </span>
          <button className="tcmd" type="button" onClick={() => setPaletteOpen(true)}>
            Jump to anything <kbd>⌘K</kbd>
          </button>
          <button
            className="ticon"
            type="button"
            onClick={() => setDark((value) => (value === null ? true : value ? false : null))}
            title={
              dark === null ? 'Following your system theme' : dark ? 'Dark theme' : 'Light theme'
            }
            aria-label="Change theme"
          >
            {dark === null ? '◐' : dark ? '●' : '○'}
          </button>
        </div>
      </header>

      <div className="tpage">
        {/* The hero. Their big number is the portfolio; ours is the bar. */}
        <section className="thero">
          <div>
            <div className="theyebrow">The number to beat</div>
            <div className="thnum">
              <b>{fleet ? fleet.bar.toFixed(2) : '—'}</b>
              <span className="unit">
                Sharpe{!fleet?.bar_sigma_measured && fleet ? ', assumed' : ''}
              </span>
            </div>
            <p className="thsub">
              {trials} trials have been recorded, so this is the Sharpe the luckiest
              worthless strategy would be expected to show by chance alone. A backtest
              below it is not evidence of anything.
            </p>
          </div>
          <div className="thstats">
            <div className="thstat">
              <span>Strategies</span>
              <b>{fleet?.strategies.length ?? '—'}</b>
            </div>
            <div className="thstat">
              <span>Measured</span>
              <b>{fleet ? measured : '—'}</b>
            </div>
            <div className="thstat">
              <span>Clearing it</span>
              <b className={clearing > 0 ? 'on' : ''}>{fleet ? clearing : '—'}</b>
            </div>
          </div>
        </section>

        {fleet && !fleet.bar_sigma_measured && (
          <div className="tnote">
            <span className="mk" aria-hidden="true">
              ▲
            </span>
            <div>
              <p>
                <b>The bar is assumed, not measured.</b> {fleet.bar_note}
              </p>
              <p style={{ marginTop: 6 }}>
                Screening on this page spends no trial, so any search done here is
                invisible to the bar — it stands lower than the work actually done
                justifies.
              </p>
            </div>
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

        <div className="tcols" aria-hidden="true">
          <span />
          <span>Strategy</span>
          <span>Class · Timeframe · Evidence</span>
          <span className="r">Sharpe vs bar</span>
          <span className="r">Runs</span>
          <span className="r">Trials</span>
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
                onToggle={() => toggle(strategy.id)}
                onOpen={() => setOpen(open === strategy.id ? null : strategy.id)}
              />
            ))}
          {fleet && rows.length === 0 && <div className="tempty">Nothing matches that filter.</div>}
          {!fleet && !problem && <div className="tempty">Reading the registry…</div>}
        </div>

        {selected.size > 0 && (
          <div className="tsel">
            <b>{selected.size}</b> selected
            <span className="price">
              {price
                ? `${price.new_evaluations} new backtests · spends ${price.spends_trials} trials · unrecorded search`
                : 'pricing…'}
            </span>
            <button className="tbtn ghost" type="button" onClick={() => setSelected(new Set())}>
              Clear
            </button>
            <button className="tbtn" type="button" disabled title="Not built yet (T-3613).">
              Backtest
            </button>
          </div>
        )}
      </div>

      {paletteOpen && (
        <CommandPalette strategies={fleet?.strategies ?? []} onClose={() => setPaletteOpen(false)} />
      )}
    </>
  );
}

function Row({
  strategy,
  bar,
  checked,
  open,
  onToggle,
  onOpen,
}: {
  strategy: FleetStrategy;
  bar: number;
  checked: boolean;
  open: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  const result = strategy.result;
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
            aria-label={`Select ${strategy.title}`}
          />
        </div>
        <div className="tname">
          <div className="nm">{strategy.title}</div>
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
        </div>
        <div className="tmeta">
          <Tag>{strategy.asset_class}</Tag>
          <Tag>{strategy.timeframe}</Tag>
          <EvidenceBadge stage={strategy.stage} />
        </div>
        <SharpeCell
          sharpe={strategy.sharpe}
          bar={bar}
          runs={result.runs}
          isMax={Boolean(result.is_a_maximum)}
        />
        <div className="truns c-hide">
          {result.runs || <span className="tdim">—</span>}
          {result.is_a_maximum && <span className="mx">max</span>}
        </div>
        <div className="ttrials c-hide">
          {strategy.trials || <span className="tdim">0</span>}
        </div>
      </div>

      {open && (
        <div className="tdetail">
          <div>
            <p className="tdesc">{strategy.summary}</p>
            <div className="tfacts">
              <Fact label="Total return" value={result.total_return} kind="pct" />
              <Fact label="Max drawdown" value={result.max_drawdown} kind="pct" />
              <Fact label="Fills" value={result.fills} kind="int" />
              <Fact label="Window" value={result.window_days} kind="days" />
              <Fact label="Tier" value={result.tier} kind="text" />
              <Fact label="Lookback" value={strategy.lookback} kind="days" />
              <Fact label="Risk manager" value={strategy.risk_manager} kind="text" />
              <Fact label="Trade manager" value={strategy.trade_manager} kind="text" />
            </div>
          </div>
          <div className="tside">
            {result.caveat && (
              <div className="tcaveat">
                <h4>What this number is not</h4>
                {result.caveat}
              </div>
            )}
            {!result.caveat && strategy.sharpe === null && (
              <div className="tcaveat">
                <h4>No result</h4>
                This strategy has never been backtested in this workspace. The column reads
                &ldquo;not measured&rdquo; rather than zero, because zero would be a finding.
              </div>
            )}
            <div className="tacts">
              <button className="tbtn go" type="button" disabled title="Not built yet (T-3613).">
                Backtest
              </button>
              <button className="tbtn" type="button" disabled title="Not built yet (T-3613).">
                Trials
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Fact({
  label,
  value,
  kind,
}: {
  label: string;
  value: number | string | undefined;
  kind: 'pct' | 'int' | 'days' | 'text';
}) {
  let text = '—';
  let tone = '';
  if (value !== undefined && value !== null && value !== '') {
    if (kind === 'pct' && typeof value === 'number') {
      text = `${value >= 0 ? '' : '−'}${Math.abs(value * 100).toFixed(1)}%`;
      tone = value < 0 ? 'neg' : '';
    } else if (kind === 'days') {
      text = `${value}d`;
    } else {
      text = String(value);
    }
  } else {
    tone = 'dim';
  }
  return (
    <div className="tfact">
      <span>{label}</span>
      <b className={tone}>{text}</b>
    </div>
  );
}
