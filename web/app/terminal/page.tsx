'use client';

/**
 * The terminal shell: top bar, hero, and whichever surface is selected.
 *
 * Built from the Robinhood reference (docs/RESEARCH/018) with two deliberate
 * inversions, both recorded in ADR-041:
 *
 *   1. Their hero number is your money. Ours is the noise bar, because that is
 *      the number that actually decides anything. A strategy's return in that
 *      slot would be the layout itself arguing that return is what matters.
 *   2. Their accent tracks profit. Ours tracks evidence — green means "cleared
 *      the bar", never "did well".
 *
 * Window and tier live here rather than in the Run tab because the library's
 * per-row Backtest button uses them too, and two surfaces silently running
 * different windows would produce two incomparable numbers under one name.
 */

import { useCallback, useEffect, useState } from 'react';
import { CommandPalette } from '@/components/CommandPalette';
import { BuildTab } from '@/components/terminal/BuildTab';
import { ModeBadge } from '@/components/terminal/ModeBadge';
import { OptionsTab } from '@/components/terminal/OptionsTab';
import { RiskTab } from '@/components/terminal/RiskTab';
import { BacktestDialog } from '@/components/terminal/BacktestDialog';
import { DeployDialog } from '@/components/terminal/DeployDialog';
import { ExplainDialog } from '@/components/terminal/ExplainDialog';
import { InstrumentChooser } from '@/components/terminal/InstrumentChooser';
import { ReportDialog } from '@/components/terminal/ReportDialog';
import { ChartTab } from '@/components/terminal/ChartTab';
import { InstrumentsTab } from '@/components/terminal/InstrumentsTab';
import { Library } from '@/components/terminal/Library';
import { LiveTab } from '@/components/terminal/LiveTab';
import { RunTab } from '@/components/terminal/RunTab';
import { SnapshotTab } from '@/components/terminal/SnapshotTab';
import { api } from '@/lib/api';
import type { Fleet, FleetStrategy } from '@/lib/api';

// Data is deliberately not here. Results still mirror to the bucket after every
// backtest — that is automatic and unaffected; what is gone is the manual
// pull-merge-push button and the on-disk counts.
const NAV = [
  'Snapshot',
  'Chart',
  'Options',
  'Library',
  'Build',
  'Run',
  'Instruments',
  'Risk',
  'Live',
] as const;
type Tab = (typeof NAV)[number];

export default function TerminalPage() {
  const [tab, setTab] = useState<Tab>('Snapshot');
  const [fleet, setFleet] = useState<Fleet | null>(null);
  const [problem, setProblem] = useState('');
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [dark, setDark] = useState<boolean | null>(null);
  const [deploying, setDeploying] = useState<FleetStrategy | null>(null);
  const [days, setDays] = useState(800);
  const [tier, setTier] = useState<'A' | 'B'>('B');
  // Which instruments a run may choose from. Held here with window and tier
  // because the library's per-row Backtest uses them too, and two surfaces
  // silently running different universes would produce two numbers that look
  // comparable and are not.
  const [universe, setUniverse] = useState('all');
  const [assetClass, setAssetClass] = useState('equity');
  // A hand-picked list overrides the universe when non-empty. Held beside it so
  // the library row's Backtest and the Run tab cannot disagree about what a run
  // was pointed at.
  const [instruments, setInstruments] = useState<string[]>([]);
  const [choosing, setChoosing] = useState(false);
  const [explaining, setExplaining] = useState<string | null>(null);
  const [reporting, setReporting] = useState<FleetStrategy | null>(null);
  // Backtest opens a dialog rather than firing on whatever the toolbar was set
  // to. The instruments and the period are the two facts that most change a
  // result, and they were the two the operator could not see when deciding.
  const [configuring, setConfiguring] = useState<FleetStrategy | null>(null);
  // An explicit window and the account it is sized against. Held here beside
  // the other run settings so they survive closing the dialog — an operator
  // testing several strategies over the same 2022 window should set it once.
  const [dateRange, setDateRange] = useState({ start: '', end: '' });
  const [startingCash, setStartingCash] = useState(1_000_000);
  const [pendingRun, setPendingRun] = useState<string[]>([]);

  const workspace = '';

  const refresh = useCallback(() => {
    api
      .fleet()
      .then((next) => {
        setFleet(next);
        setProblem('');
      })
      .catch(() => setProblem('Cannot reach the API. Is it running on :8000?'));
  }, []);

  useEffect(refresh, [refresh]);

  // Null means "follow the OS", which is the state most people are in. Only an
  // explicit choice stamps the attribute.
  useEffect(() => {
    const root = document.querySelector('.terminal');
    if (!root) return;
    if (dark === null) root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', dark ? 'dark' : 'light');
  }, [dark]);

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
              key={item}
              type="button"
              aria-current={item === tab ? 'page' : undefined}
              onClick={() => setTab(item)}
            >
              {item}
            </button>
          ))}
        </nav>
        <div className="tright">
          {/* Mode first, before anything else in the bar. The architecture
              document's first design principle is that mode is always visible
              so nobody places a real order by mistake. Here it is stronger
              than a toggle: no live broker adapter exists, so PAPER is a fact
              about the build rather than a setting someone can flip. */}
          <ModeBadge />
          <span
            className="tws"
            title="Evidence, strategies and credentials are scoped to this workspace (ADR-040)."
          >
            workspace <b>default</b>
          </span>
          <button
            className="ticon"
            type="button"
            onClick={() => setExplaining('')}
            title="What a backtest here actually does, and which asset classes have data."
            aria-label="What this means"
          >
            i
          </button>
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
        {tab === 'Options' && <OptionsTab />}
        {tab === 'Risk' && <RiskTab />}
        {tab === 'Snapshot' && <SnapshotTab workspace={workspace} />}

        {tab === 'Chart' && <ChartTab />}

        {tab === 'Library' && (
          <>
            <section className="thero">
              <div>
                <div className="theyebrow">The number to beat</div>
                <div className="thnum">
                  <b>{fleet ? fleet.bar.toFixed(2) : '—'}</b>
                  <span className="unit" title={fleet?.bar_note}>
                    Sharpe{fleet && !fleet.bar_sigma_measured ? ', assumed' : ''}
                  </span>
                </div>
                <p className="thsub">
                  {fleet?.bar_trials ?? trials} trials have been recorded, so this is the Sharpe the luckiest
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

            <Library
              fleet={fleet}
              problem={problem}
              window={days}
              tier={tier}
              universe={universe}
              onUniverse={setUniverse}
              instruments={instruments}
              runClass={assetClass}
              onChoose={() => setChoosing(true)}
              onRefresh={refresh}
              onDeploy={setDeploying}
              onExplain={setExplaining}
              onReport={setReporting}
              onConfigure={setConfiguring}
              dateRange={dateRange}
              startingCash={startingCash}
              pendingRun={pendingRun}
              onRan={() => setPendingRun([])}
            />
          </>
        )}

        {tab === 'Build' && (
          <BuildTab
            onRefresh={refresh}
            window={days}
            tier={tier}
            dateRange={dateRange}
            startingCash={startingCash}
            onWindow={setDays}
            onTier={setTier}
            onDateRange={setDateRange}
            onStartingCash={setStartingCash}
          />
        )}

        {tab === 'Run' && (
          <RunTab
            fleet={fleet}
            window={days}
            tier={tier}
            universe={universe}
            instruments={instruments}
            assetClass={assetClass}
            onAssetClass={setAssetClass}
            onWindow={setDays}
            onTier={setTier}
            onUniverse={setUniverse}
            onInstruments={setInstruments}
            onRefresh={refresh}
          />
        )}

        {tab === 'Instruments' && <InstrumentsTab />}

        {tab === 'Live' && (
          <LiveTab
            fleet={fleet?.strategies ?? []}
            workspace={workspace}
            onDeploy={setDeploying}
          />
        )}

      </div>

      {paletteOpen && (
        <CommandPalette strategies={fleet?.strategies ?? []} onClose={() => setPaletteOpen(false)} />
      )}
      {deploying && (
        <DeployDialog
          strategy={deploying}
          workspace={workspace}
          onClose={() => setDeploying(null)}
        />
      )}
      {explaining !== null && (
        <ExplainDialog strategy={explaining} onClose={() => setExplaining(null)} />
      )}
      {reporting && (
        <ReportDialog
          strategy={reporting}
          workspace={workspace}
          onClose={() => setReporting(null)}
        />
      )}
      {configuring && (
        <BacktestDialog
          strategy={configuring}
          window={days}
          tier={tier}
          universe={universe}
          instruments={instruments}
          assetClass={assetClass}
          onWindow={setDays}
          onTier={setTier}
          onUniverse={setUniverse}
          onInstruments={setInstruments}
          onAssetClass={setAssetClass}
          dateRange={dateRange}
          onDateRange={setDateRange}
          startingCash={startingCash}
          onStartingCash={setStartingCash}
          onRun={() => {
            setPendingRun([configuring.id]);
            setConfiguring(null);
          }}
          onClose={() => setConfiguring(null)}
        />
      )}
      {choosing && (
        <InstrumentChooser
          chosen={instruments}
          onChange={setInstruments}
          onClose={() => setChoosing(false)}
        />
      )}
    </>
  );
}
