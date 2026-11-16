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
 *   AI          the agent network: inbox, agents and briefs, ask, market brief,
 *               data quality, the agents' log (ADR-085)
 *   Tools       the strategy builder, the instrument catalog, the SIP
 *               backtester, data status
 *
 * Backtest settings — period, tier, instruments, capital — are asked in the
 * Backtest dialog. They used to be editable from the Library toolbar, the Run
 * tab and the dialog, and a run's real settings could only be known by checking
 * all three. The Strategy Builder is the one exception: it saves what it builds
 * and backtests it through the same batch endpoint, with its own window and tier
 * beside the rules being tested.
 *
 * The page is kept in the URL hash so a page can be bookmarked and the back
 * button works.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import dynamic from 'next/dynamic';
import {
  Boxes,
  CandlestickChart,
  ChevronRight,
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
  PiggyBank,
  BookOpen,
  Bot,
  Filter,
  type LucideIcon,
} from 'lucide-react';
import { CommandPalette } from '@/components/CommandPalette';
import AgentStrip from '@/components/terminal/AgentStrip';
import { ModeBadge } from '@/components/terminal/ModeBadge';
import { Info as InfoButton, Move, Stat, Stats } from '@/components/terminal/ui';
import { agentsApi, api } from '@/lib/api';
import type { Fleet, FleetStrategy } from '@/lib/api';

// Each page's code is fetched when the page is first opened, not with the
// shell. Imported statically, every tab was one 242 KB bundle that each page
// downloaded and parsed before it could paint (measured 2026-11-08).
function Loading() {
  return <div className="muted" style={{ padding: 16 }}>Loading…</div>;
}
const AgentsTab = dynamic(() => import('@/components/terminal/AgentsTab').then((m) => m.AgentsTab), { ssr: false, loading: Loading });
const ResearchLibrary = dynamic(() => import('@/components/terminal/ResearchLibrary').then((m) => m.ResearchLibrary), { ssr: false, loading: Loading });
const StrategyBuilder = dynamic(() => import('@/components/terminal/StrategyBuilder').then((m) => m.StrategyBuilder), { ssr: false, loading: Loading });
const OptionsTab = dynamic(() => import('@/components/terminal/OptionsTab').then((m) => m.OptionsTab), { ssr: false, loading: Loading });
const RiskTab = dynamic(() => import('@/components/terminal/RiskTab').then((m) => m.RiskTab), { ssr: false, loading: Loading });
const RiskBookView = dynamic(() => import('@/components/terminal/RiskBook').then((m) => m.RiskBookView), { ssr: false, loading: Loading });
const BacktestDialog = dynamic(() => import('@/components/terminal/BacktestDialog').then((m) => m.BacktestDialog), { ssr: false, loading: Loading });
const DeployDialog = dynamic(() => import('@/components/terminal/DeployDialog').then((m) => m.DeployDialog), { ssr: false, loading: Loading });
const ExplainDialog = dynamic(() => import('@/components/terminal/ExplainDialog').then((m) => m.ExplainDialog), { ssr: false, loading: Loading });
const BacktestReport = dynamic(() => import('@/components/terminal/BacktestReport').then((m) => m.BacktestReport), { ssr: false, loading: Loading });
const ChartTab = dynamic(() => import('@/components/terminal/ChartTab').then((m) => m.ChartTab), { ssr: false, loading: Loading });
const InstrumentsTab = dynamic(() => import('@/components/terminal/InstrumentsTab').then((m) => m.InstrumentsTab), { ssr: false, loading: Loading });
const Library = dynamic(() => import('@/components/terminal/Library').then((m) => m.Library), { ssr: false, loading: Loading });
const LiveTab = dynamic(() => import('@/components/terminal/LiveTab').then((m) => m.LiveTab), { ssr: false, loading: Loading });
const SipTab = dynamic(() => import('@/components/terminal/SipTab').then((m) => m.SipTab), { ssr: false, loading: Loading });
const SnapshotTab = dynamic(() => import('@/components/terminal/SnapshotTab').then((m) => m.SnapshotTab), { ssr: false, loading: Loading });
const ScreenerTab = dynamic(() => import('@/components/terminal/ScreenerTab').then((m) => m.ScreenerTab), { ssr: false, loading: Loading });
const DeskTab = dynamic(() => import('@/components/terminal/DeskTab').then((m) => m.DeskTab), { ssr: false, loading: Loading });

type PageId =
  | 'dashboard'
  | 'strategies'
  | 'charts'
  | 'options'
  | 'live'
  | 'tools'
  | 'builder'
  | 'instruments'
  | 'sip'
  | 'research'
  | 'report'
  | 'deployment'
  | 'agents'
  | 'screener';

type NavItem = { id: PageId; label: string; icon: LucideIcon };

const NAV: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'strategies', label: 'Strategies', icon: Boxes },
  { id: 'screener', label: 'Screener', icon: Filter },
  { id: 'charts', label: 'Charts', icon: CandlestickChart },
  { id: 'options', label: 'Options', icon: Sigma },
  { id: 'live', label: 'Live & Risk', icon: ShieldCheck },
  { id: 'agents', label: 'AI', icon: Bot },
  { id: 'tools', label: 'Tools', icon: Wrench },
];

type Tool = { id: PageId; title: string; description: string; icon: LucideIcon };

const TOOLS: Tool[] = [
  {
    id: 'research',
    title: 'Research Library',
    description:
      'Papers and reports, each with its summary, trade idea, implementation logic and red flags, and the strategies that test it.',
    icon: BookOpen,
  },
  {
    id: 'builder',
    title: 'Strategy Builder',
    description:
      'Build a strategy from rules: what to trade, when to buy and sell, how much, and where to stop.',
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
    id: 'sip',
    title: 'SIP Backtester',
    description:
      'Invest a fixed amount every month in one instrument and see the value, XIRR and how it compares with investing once.',
    icon: PiggyBank,
  },
];

const TITLES: Record<PageId, { title: string; sub: string; parent?: PageId }> = {
  dashboard: { title: 'Dashboard', sub: 'The market today: the pulse, sectors, who holds the index, and stocks to watch.' },
  strategies: {
    title: 'Strategies',
    sub: 'Every strategy with its full backtest report. Select one or several and press Backtest to run them.',
  },
  screener: {
    title: 'Screener',
    sub: 'Which liquid stocks each model would hold today, long term (monthly) and swing (weekly), with each model\'s backtest and how its past picks did. Not advice; nothing here has passed the gate.',
  },
  charts: { title: 'Charts', sub: 'Charting, drawing and the macro picture.' },
  options: {
    title: 'Options',
    sub: 'Option chain, OI tracker, straddle and IV history, vol surface, payoff and the analytics behind them.',
  },
  live: { title: 'Live & Risk', sub: 'What is ready to deploy, and the limits that stop trading.' },
  tools: { title: 'Tools', sub: 'Building strategies, browsing instruments and checking data.' },
  builder: { title: 'Strategy Builder', sub: 'Pick what to trade, write the rules, size it, set the stops, then backtest.', parent: 'tools' },
  instruments: { title: 'Instruments', sub: 'Every instrument that has data.', parent: 'tools' },
  sip: {
    title: 'SIP Backtester',
    sub: 'A monthly investment plan over landed closes. A calculator, not an engine run.',
    parent: 'tools',
  },
  research: { title: 'Research Library', sub: 'Every paper behind a strategy, and how its strategies did.', parent: 'tools' },
  report: { title: 'Backtest Report', sub: '', parent: 'strategies' },
  deployment: { title: 'Deployment Report', sub: '', parent: 'live' },
  agents: {
    title: 'AI',
    sub: 'The control room: what waits on your decision, every agent at work, and a box to ask. Each agent also shows on the page it works for. Nothing here trades.',
  },
};

/** The strategy in a deployment id, `{mode}-{strategy}-{YYYY-MM-DD}-{hash}` (deploy/deployments.py). */
function strategyOfDeployment(id: string): string {
  return id.match(/^(?:paper|live)-(.+)-\d{4}-\d{2}-\d{2}-[0-9a-f]{6}$/)?.[1] ?? '';
}

const PAGE_IDS = Object.keys(TITLES) as PageId[];

const LIVE_VIEWS = ['overview', 'performance', 'stress', 'deploy', 'desk', 'risk'] as const;
type LiveView = (typeof LIVE_VIEWS)[number];

/** `#strategies`, or `#report/<strategy id>` for one strategy's report. */
function readHash(): { page: PageId; strategy: string } {
  if (typeof window === 'undefined') return { page: 'dashboard', strategy: '' };
  const [id, strategy = ''] = window.location.hash.replace(/^#\/?/, '').split('/');
  const page = PAGE_IDS.includes(id as PageId) ? (id as PageId) : 'dashboard';
  return { page, strategy: decodeURIComponent(strategy) };
}

export default function TerminalPage() {
  const [page, setPageState] = useState<PageId>('dashboard');
  // False until the URL's page is read. The first render used to be the
  // dashboard whatever the URL said, so every page also fetched the dashboard's
  // snapshot and market context before switching (2026-11-08).
  const [hashRead, setHashRead] = useState(false);
  const [liveView, setLiveView] = useState<LiveView>('overview');
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
  // How many agents are working, for the dot on the AI link (ADR-091).
  const [agentsBusy, setAgentsBusy] = useState(0);

  const workspace = '';

  // A dialog belongs to the page it was opened on. Left open, the Deploy and
  // explain dialogs followed the operator to every other page (2026-10-29).
  const closeDialogs = useCallback(() => {
    setDeploying(null);
    setExplaining(null);
    setConfiguring(null);
    setPaletteOpen(false);
  }, []);

  const setPage = useCallback((next: PageId, strategy = '') => {
    closeDialogs();
    setPageState(next);
    setReportId(strategy);
    const hash = strategy ? `#${next}/${encodeURIComponent(strategy)}` : `#${next}`;
    if (typeof window !== 'undefined' && window.location.hash !== hash) {
      window.history.pushState(null, '', hash);
    }
    window.scrollTo({ top: 0 });
  }, [closeDialogs]);

  useEffect(() => {
    const apply = () => {
      closeDialogs();
      const { page: next, strategy } = readHash();
      setPageState(next);
      setReportId(strategy);
      setHashRead(true);
      // `#live/performance` opens that view of Live & Risk, so a view can be linked to.
      if (next === 'live' && (LIVE_VIEWS as readonly string[]).includes(strategy)) {
        setLiveView(strategy as LiveView);
      }
    };
    apply();
    const onHash = apply;
    window.addEventListener('popstate', onHash);
    window.addEventListener('hashchange', onHash);
    return () => {
      window.removeEventListener('popstate', onHash);
      window.removeEventListener('hashchange', onHash);
    };
  }, [closeDialogs]);

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

  useEffect(() => {
    const read = () =>
      agentsApi
        .activity(1)
        .then((r) => setAgentsBusy(r.running))
        .catch(() => setAgentsBusy(0));
    read();
    const timer = window.setInterval(read, 20000);
    return () => window.clearInterval(timer);
  }, []);

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
  const deployedStrategy =
    page === 'deployment' ? (fleet?.strategies.find((s) => s.id === strategyOfDeployment(reportId)) ?? null) : null;
  const heading = TITLES[page];
  const activeNav: PageId = heading.parent ?? page;

  return (
    <>
      <header className="tbar">
        <button className="tbrand" type="button" onClick={() => setPage('dashboard')}>
          <span className="tbrand-mark" aria-hidden="true">E</span>
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
                {item.id === 'agents' && agentsBusy > 0 && (
                  <span className="tnav-dot" title={`${agentsBusy} agent${agentsBusy === 1 ? '' : 's'} working`} />
                )}
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
        {/* Charts and Options have no title at all (operator, 2026-11-16): the
            nav names the page. */}
        {page !== 'report' && page !== 'charts' && page !== 'options' && (
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
            {/* The title alone; what the page is for opens from its info
                button (ADR-102). */}
            <h1 className="tpage-title">
              {heading.title}
              <InfoButton label={`About ${heading.title}`}>{heading.sub}</InfoButton>
            </h1>
          </div>
        )}

        {hashRead && (
          <AgentStrip page={page} onOpenAI={(view) => setPage('agents', view ?? '')} />
        )}

        {hashRead && page === 'dashboard' && <SnapshotTab workspace={workspace} />}

        {page === 'strategies' && (
          <>
            <div className="st-headline">
              <Stats>
                <Stat label="Strategies" value={fleet?.strategies.length ?? '—'} />
                <Stat
                  label={fleet?.bar_label ? `Beat the ${fleet.bar_label}` : 'Beat the noise bar'}
                  value={fleet ? clearing : '—'}
                  tone={fleet && clearing > 0 ? 'up' : ''}
                  sub={
                    fleet
                      ? fleet.bar_families != null
                        ? `${fleet.bar_label ?? 'Sharpe'} ${fleet.bar.toFixed(2)} · ${fleet.bar_families} idea families`
                        : `Sharpe ${fleet.bar.toFixed(2)} · ${fleet.bar_trials ?? 0} trials`
                      : undefined
                  }
                  info={fleet?.bar_note}
                />
                <Stat label="Backtested" value={fleet ? measured : '—'} />
                {fleet?.market?.total_return !== null && fleet?.market?.total_return !== undefined && (
                  <Stat
                    label={`Nifty held since ${fleet.market.since.slice(0, 4)}`}
                    value={<Move value={fleet.market.total_return} digits={0} />}
                  />
                )}
              </Stats>
            </div>

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
              onRecommend={(setting) => {
                setDateRange({ start: setting.start, end: setting.end });
                setDays(setting.window_days);
                setUniverse(setting.universe);
                setTier(setting.tier);
                setAssetClass(setting.asset_class);
                setStartingCash(setting.capital);
              }}
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

        {page === 'deployment' &&
          (deployedStrategy ? (
            <BacktestReport
              key={reportId}
              strategy={deployedStrategy}
              deployment={reportId}
              bar={fleet?.bar ?? null}
              workspace={workspace}
              backLabel="Live & Risk"
              onBack={() => setPage('live')}
            />
          ) : (
            <div className="tempty">
              {fleet ? 'No deployment by that name.' : 'Reading the registry…'}
            </div>
          ))}

        {page === 'agents' && <AgentsTab open={reportId} />}
        {page === 'screener' && <ScreenerTab />}
        {page === 'charts' && <ChartTab />}
        {page === 'options' && <OptionsTab />}

        {page === 'live' && (
          <>
            <div className="tseg" role="tablist" aria-label="Live and risk">
              <button type="button" role="tab" aria-selected={liveView === 'overview'} onClick={() => setLiveView('overview')}>
                Risk overview
              </button>
              <button type="button" role="tab" aria-selected={liveView === 'performance'} onClick={() => setLiveView('performance')}>
                Performance
              </button>
              <button type="button" role="tab" aria-selected={liveView === 'stress'} onClick={() => setLiveView('stress')}>
                Stress &amp; exposure
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={liveView === 'deploy'}
                onClick={() => setLiveView('deploy')}
              >
                Deployment
              </button>
              <button type="button" role="tab" aria-selected={liveView === 'desk'} onClick={() => setLiveView('desk')}>
                Trade desk
              </button>
            </div>
            {/* The limits and kill switch sit on Risk overview as one line (operator,
                2026-11-16); an old `#live/risk` link lands there too. */}
            {liveView === 'overview' || liveView === 'risk' ? (
              <>
                <RiskTab />
                <RiskBookView view="overview" onReport={(id) => setPage('deployment', id)} />
              </>
            ) : liveView === 'performance' || liveView === 'stress' ? (
              <RiskBookView view={liveView} onReport={(id) => setPage('deployment', id)} />
            ) : liveView === 'deploy' ? (
              <LiveTab
                fleet={fleet?.strategies ?? []}
                workspace={workspace}
                onDeploy={setDeploying}
                onReport={(id) => setPage('deployment', id)}
                onStrategyReport={(id) => setPage('report', id)}
              />
            ) : liveView === 'desk' ? (
              <DeskTab titles={Object.fromEntries((fleet?.strategies ?? []).map((s) => [s.id, s.title]))} />
            ) : null}
          </>
        )}

        {page === 'tools' && (
          <div className="ttool-grid">
            {TOOLS.map((tool) => {
              const Icon = tool.icon;
              return (
                <div key={tool.id} className="ttool-card">
                  <button type="button" className="ttool-open" onClick={() => setPage(tool.id)}>
                    <span className="ttool-icon" aria-hidden="true">
                      <Icon size={20} />
                    </span>
                    <b>
                      {tool.title}
                      <ChevronRight size={16} aria-hidden="true" />
                    </b>
                  </button>
                  <span className="ttool-info">
                    <InfoButton align="right" label={`About ${tool.title}`}>
                      {tool.description}
                    </InfoButton>
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {page === 'builder' && <StrategyBuilder onRefresh={refresh} />}
        {page === 'research' && (
          <ResearchLibrary
            selected={reportId}
            onSelect={(id) => setPage('research', id)}
            onBacktest={(ids) => {
              const chosen = (fleet?.strategies ?? []).filter((s) => ids.includes(s.id));
              if (chosen.length) setConfiguring(chosen);
            }}
            onReport={(id) => setPage('report', id)}
            onBuild={() => setPage('builder')}
          />
        )}
        {page === 'instruments' && <InstrumentsTab />}
        {page === 'sip' && <SipTab />}
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
          onDeployed={() => {
            setDeploying(null);
            setLiveView('deploy');
            setPage('live');
          }}
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
            // The run happens on the Strategies page, where its progress shows.
            setPage('strategies');
          }}
          onClose={() => setConfiguring(null)}
        />
      )}
    </>
  );
}
