'use client';

/**
 * The terminal shell: one navigation bar, one page at a time.
 *
 * Laid out after OpenAlgo's interface: a sticky top bar of icon-and-label
 * links, a page title with one line under it, and everything secondary behind
 * a Tools page of cards rather than in the main bar.
 *
 * The rule the layout enforces is that every feature has exactly one home:
 *
 *   Dashboard   the market today (was Snapshot)
 *   Strategies  every strategy and the one way to backtest it; each strategy's
 *               report opens as its own page (#report/<id>)
 *               (was Library, plus the Run tab, which was a second way)
 *   Charts      the charting surface and the macro band
 *   Options     the option chain, its analytics and the payoff builder
 *   Live        deployment readiness and the risk limits that stop trading
 *               (was two tabs, Live and Risk, describing one question)
 *   Tools       the strategy builder, the instrument catalog, data status
 *
 * Backtest settings — period, tier, instruments, capital — are asked in the
 * Backtest dialog. They used to be editable from the Library toolbar, the Run
 * tab and the dialog, and a run's real settings could only be known by checking
 * all three. The Strategy Builder is the one exception, because what it runs is
 * not in the registry yet; it renders the same BacktestOptions bound to the
 * same state, so the two cannot disagree.
 *
 * The page is kept in the URL hash so a page can be bookmarked and the back
 * button works.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Boxes,
  CandlestickChart,
  ChevronRight,
  Database,
  Info,
  LayoutDashboard,
  ListTree,
  Moon,
  Search,
  ShieldCheck,
  Sigma,
  Sun,
  SunMoon,
  Wrench,
  Hammer,
  type LucideIcon,
} from 'lucide-react';
import { CommandPalette } from '@/components/CommandPalette';
import { BuildTab } from '@/components/terminal/BuildTab';
import { ModeBadge } from '@/components/terminal/ModeBadge';
import { OptionsTab } from '@/components/terminal/OptionsTab';
import { RiskTab } from '@/components/terminal/RiskTab';
import { BacktestDialog } from '@/components/terminal/BacktestDialog';
import { DataTab } from '@/components/terminal/DataTab';
import { DeployDialog } from '@/components/terminal/DeployDialog';
import { ExplainDialog } from '@/components/terminal/ExplainDialog';
import { BacktestReport } from '@/components/terminal/BacktestReport';
import { ChartTab } from '@/components/terminal/ChartTab';
import { InstrumentsTab } from '@/components/terminal/InstrumentsTab';
import { Library } from '@/components/terminal/Library';
import { LiveTab } from '@/components/terminal/LiveTab';
import { SnapshotTab } from '@/components/terminal/SnapshotTab';
import { api } from '@/lib/api';
import type { Fleet, FleetStrategy } from '@/lib/api';

type PageId =
  | 'dashboard'
  | 'strategies'
  | 'charts'
  | 'options'
  | 'live'
  | 'tools'
  | 'builder'
  | 'instruments'
  | 'data'
  | 'report';

type NavItem = { id: PageId; label: string; icon: LucideIcon };

const NAV: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'strategies', label: 'Strategies', icon: Boxes },
  { id: 'charts', label: 'Charts', icon: CandlestickChart },
  { id: 'options', label: 'Options', icon: Sigma },
  { id: 'live', label: 'Live & Risk', icon: ShieldCheck },
  { id: 'tools', label: 'Tools', icon: Wrench },
];

type Tool = { id: PageId; title: string; description: string; icon: LucideIcon };

const TOOLS: Tool[] = [
  {
    id: 'builder',
    title: 'Strategy Builder',
    description:
      'Compose a strategy from the feature library or write it as code, validate it, and backtest it.',
    icon: Hammer,
  },
  {
    id: 'instruments',
    title: 'Instruments',
    description:
      'Every instrument that has data, across NSE, US equities, crypto, FX and mutual funds. Search, filter and refresh feeds.',
    icon: ListTree,
  },
  {
    id: 'data',
    title: 'Data Status',
    description:
      'What is landed on disk, which universes exist, and which results are mirrored to the cloud.',
    icon: Database,
  },
];

const TITLES: Record<PageId, { title: string; sub: string; parent?: PageId }> = {
  dashboard: { title: 'Dashboard', sub: 'The market today: regime, breadth, movers and the map.' },
  strategies: {
    title: 'Strategies',
    sub: 'Every strategy with its full backtest report. Select one or several and press Backtest to run them.',
  },
  charts: { title: 'Charts', sub: 'Charting, drawing and the macro picture.' },
  options: { title: 'Options', sub: 'Option chain, Greeks, implied volatility, positioning and payoff.' },
  live: { title: 'Live & Risk', sub: 'What is ready to deploy, and the limits that stop trading.' },
  tools: { title: 'Tools', sub: 'Building strategies, browsing instruments and checking data.' },
  builder: { title: 'Strategy Builder', sub: 'Compose or write a strategy, then validate and backtest it.', parent: 'tools' },
  instruments: { title: 'Instruments', sub: 'Every instrument that has data.', parent: 'tools' },
  data: { title: 'Data Status', sub: 'What data exists, counted rather than claimed.', parent: 'tools' },
  report: { title: 'Backtest Report', sub: '', parent: 'strategies' },
};

const PAGE_IDS = Object.keys(TITLES) as PageId[];

/** `#strategies`, or `#report/<strategy id>` for one strategy's report. */
function readHash(): { page: PageId; strategy: string } {
  if (typeof window === 'undefined') return { page: 'dashboard', strategy: '' };
  const [id, strategy = ''] = window.location.hash.replace(/^#\/?/, '').split('/');
  const page = PAGE_IDS.includes(id as PageId) ? (id as PageId) : 'dashboard';
  return { page, strategy: decodeURIComponent(strategy) };
}

export default function TerminalPage() {
  const [page, setPageState] = useState<PageId>('dashboard');
  const [liveView, setLiveView] = useState<'deploy' | 'risk'>('deploy');
  const [fleet, setFleet] = useState<Fleet | null>(null);
  const [problem, setProblem] = useState('');
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [dark, setDark] = useState<boolean | null>(null);
  const [deploying, setDeploying] = useState<FleetStrategy | null>(null);
  // Every backtest setting lives here, once. The Backtest dialog edits it, and
  // the Strategy Builder renders the same controls over the same state.
  const [days, setDays] = useState(800);
  const [tier, setTier] = useState<'A' | 'B'>('B');
  const [universe, setUniverse] = useState('all');
  const [assetClass, setAssetClass] = useState('equity');
  const [instruments, setInstruments] = useState<string[]>([]);
  const [dateRange, setDateRange] = useState({ start: '', end: '' });
  const [startingCash, setStartingCash] = useState(1_000_000);
  const [explaining, setExplaining] = useState<string | null>(null);
  // Which strategy the report page shows. An id rather than the object, so a
  // bookmarked report resolves once the registry has loaded.
  const [reportId, setReportId] = useState('');
  const [configuring, setConfiguring] = useState<FleetStrategy[] | null>(null);
  const [pendingRun, setPendingRun] = useState<string[]>([]);

  const workspace = '';

  const setPage = useCallback((next: PageId, strategy = '') => {
    setPageState(next);
    setReportId(strategy);
    const hash = strategy ? `#${next}/${encodeURIComponent(strategy)}` : `#${next}`;
    if (typeof window !== 'undefined' && window.location.hash !== hash) {
      window.history.pushState(null, '', hash);
    }
    window.scrollTo({ top: 0 });
  }, []);

  useEffect(() => {
    const apply = () => {
      const { page: next, strategy } = readHash();
      setPageState(next);
      setReportId(strategy);
    };
    apply();
    const onHash = apply;
    window.addEventListener('popstate', onHash);
    window.addEventListener('hashchange', onHash);
    return () => {
      window.removeEventListener('popstate', onHash);
      window.removeEventListener('hashchange', onHash);
    };
  }, []);

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

  // Null means "follow the OS". Only an explicit choice stamps the attribute.
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

  const paletteTargets = useMemo(
    () => [
      ...NAV.map((item) => ({ id: item.id, label: item.label, meta: 'page' })),
      ...TOOLS.map((tool) => ({ id: tool.id, label: tool.title, meta: 'tool' })),
    ],
    []
  );

  const reporting = fleet?.strategies.find((s) => s.id === reportId) ?? null;
  const heading = TITLES[page];
  const activeNav: PageId = heading.parent ?? page;

  return (
    <>
      <header className="tbar">
        <button className="tbrand" type="button" onClick={() => setPage('dashboard')}>
          <span className="tmark" aria-hidden="true">
            ↗
          </span>
          <span className="tbrand-name">EulerLab</span>
        </button>
        <nav className="tnav" aria-label="Sections">
          {NAV.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                title={item.label}
                aria-current={item.id === activeNav ? 'page' : undefined}
                onClick={() => setPage(item.id)}
              >
                <Icon size={16} strokeWidth={2} aria-hidden="true" />
                <span className="tnav-label">{item.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="tright">
          {/* Mode first: no live broker adapter exists, so PAPER is a fact
              about the build rather than a setting someone can flip. */}
          <ModeBadge />
          <button className="tcmd" type="button" onClick={() => setPaletteOpen(true)}>
            <Search size={14} aria-hidden="true" />
            <span className="tcmd-label">Search</span>
            <kbd>⌘K</kbd>
          </button>
          <button
            className="ticon"
            type="button"
            onClick={() => setExplaining('')}
            title="What a backtest here actually does, and which asset classes have data."
            aria-label="How backtests work"
          >
            <Info size={16} aria-hidden="true" />
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
            {dark === null ? (
              <SunMoon size={16} aria-hidden="true" />
            ) : dark ? (
              <Moon size={16} aria-hidden="true" />
            ) : (
              <Sun size={16} aria-hidden="true" />
            )}
          </button>
        </div>
      </header>

      <div className="tpage">
        {page !== 'report' && (
          <div className="tpage-head">
            {heading.parent && (
              <nav className="tcrumb" aria-label="Breadcrumb">
                <button type="button" onClick={() => setPage(heading.parent as PageId)}>
                  {TITLES[heading.parent].title}
                </button>
                <ChevronRight size={14} aria-hidden="true" />
                <span>{heading.title}</span>
              </nav>
            )}
            <h1>{heading.title}</h1>
            <p>{heading.sub}</p>
          </div>
        )}

        {page === 'dashboard' && <SnapshotTab workspace={workspace} />}

        {page === 'strategies' && (
          <>
            <section className="tstats" aria-label="Summary">
              <div className="tstat-card" title={fleet?.bar_note}>
                <span>Sharpe to beat</span>
                <b>{fleet ? fleet.bar.toFixed(2) : '—'}</b>
                <i>
                  {fleet?.bar_trials ?? 0} trials recorded
                  {fleet && !fleet.bar_sigma_measured ? ' · assumed' : ''}
                </i>
              </div>
              <div className="tstat-card">
                <span>Strategies</span>
                <b>{fleet?.strategies.length ?? '—'}</b>
                <i>in the registry</i>
              </div>
              <div className="tstat-card">
                <span>Measured</span>
                <b>{fleet ? measured : '—'}</b>
                <i>have a backtest result</i>
              </div>
              <div className="tstat-card">
                <span>Clearing the bar</span>
                <b className={clearing > 0 ? 'on' : ''}>{fleet ? clearing : '—'}</b>
                <i>Sharpe above what luck explains</i>
              </div>
            </section>

            <Library
              fleet={fleet}
              problem={problem}
              window={days}
              tier={tier}
              universe={universe}
              instruments={instruments}
              runClass={assetClass}
              onRefresh={refresh}
              onDeploy={setDeploying}
              onExplain={setExplaining}
              onReport={(strategy) => setPage('report', strategy.id)}
              onConfigure={setConfiguring}
              dateRange={dateRange}
              startingCash={startingCash}
              pendingRun={pendingRun}
              onRan={() => setPendingRun([])}
            />
          </>
        )}

        {page === 'report' &&
          (reporting ? (
            <BacktestReport
              key={reporting.id}
              strategy={reporting}
              bar={fleet?.bar ?? null}
              workspace={workspace}
              onBack={() => setPage('strategies')}
            />
          ) : (
            <div className="tempty">
              {fleet ? 'No strategy by that name in the registry.' : 'Reading the registry…'}
            </div>
          ))}

        {page === 'charts' && <ChartTab />}
        {page === 'options' && <OptionsTab />}

        {page === 'live' && (
          <>
            <div className="tseg" role="tablist" aria-label="Live and risk">
              <button
                type="button"
                role="tab"
                aria-selected={liveView === 'deploy'}
                onClick={() => setLiveView('deploy')}
              >
                Deployment
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={liveView === 'risk'}
                onClick={() => setLiveView('risk')}
              >
                Risk limits &amp; kill switch
              </button>
            </div>
            {liveView === 'deploy' ? (
              <LiveTab
                fleet={fleet?.strategies ?? []}
                workspace={workspace}
                onDeploy={setDeploying}
              />
            ) : (
              <RiskTab />
            )}
          </>
        )}

        {page === 'tools' && (
          <div className="ttool-grid">
            {TOOLS.map((tool) => {
              const Icon = tool.icon;
              return (
                <button
                  key={tool.id}
                  type="button"
                  className="ttool-card"
                  onClick={() => setPage(tool.id)}
                >
                  <span className="ttool-icon" aria-hidden="true">
                    <Icon size={20} />
                  </span>
                  <b>
                    {tool.title}
                    <ChevronRight size={16} aria-hidden="true" />
                  </b>
                  <span>{tool.description}</span>
                </button>
              );
            })}
          </div>
        )}

        {page === 'builder' && (
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
        {page === 'instruments' && <InstrumentsTab />}
        {page === 'data' && <DataTab workspace={workspace} />}
      </div>

      {paletteOpen && (
        <CommandPalette
          pages={paletteTargets}
          strategies={fleet?.strategies ?? []}
          onPage={(id) => setPage(id as PageId)}
          onStrategy={(id) => {
            setPage('strategies');
            setExplaining(id);
          }}
          onClose={() => setPaletteOpen(false)}
        />
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
      {configuring && (
        <BacktestDialog
          strategies={configuring}
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
            setPendingRun(configuring.map((s) => s.id));
            setConfiguring(null);
          }}
          onClose={() => setConfiguring(null)}
        />
      )}
    </>
  );
}
