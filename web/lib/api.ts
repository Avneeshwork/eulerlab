// Every call the interface makes. Typed here so a change to the Python API
// surfaces as a compile error rather than as `undefined` in the UI.

export type Feature = { name: string; description: string };

export type Library = {
  features: Feature[];
  example_code: string;
  sandbox_rules: string[];
};

export type Provider = {
  name: string;
  model: string;
  free: boolean;
  needs_key: boolean;
  ready: boolean;
  reason: string;
  note: string;
  is_default: boolean;
};

export type Health = {
  ok: boolean;
  panel_loaded: boolean;
  trials_logged: number;
  noise_bar: number;
  // The bar is scaled by a dispersion of Sharpes that has never been measured
  // (A-021). Carried in the payload so the caveat travels with the number.
  noise_bar_sigma_measured: boolean;
  noise_bar_sigma: number | null;
  noise_bar_note: string;
};

export type Result = {
  label: string;
  mode: string;
  tier: string;
  strategy: string;
  days: string[];
  equity: number[];
  starting_cash: number;
  final_equity: number;
  total_return: number;
  annualised: number;
  sharpe: number;
  max_drawdown: number;
  fills: number;
  rejections: number;
  costs: number;
  period: [string, string];
  warmup: number;
  noise_bar: number;
  resampled: Resampled | null;
  caveats: string[];
};

// Monte Carlo resampling of the realised returns (ADR-034). Shuffling measures
// path risk only — it cannot move the Sharpe — so the drawdown and the Sharpe
// interval come from two different operations and are labelled separately.
export type Resampled = {
  drawdown_p05: number;
  drawdown_p50: number;
  sharpe_p05: number;
  sharpe_p95: number;
  drawdown_is_understated: boolean;
  sharpe_could_be_zero: boolean;
};

export type Job = {
  ok: boolean;
  id: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  message: string;
  elapsed: number;
  result: Result;
  error: string;
};

export type Draft = {
  ok: boolean;
  mode?: 'composed' | 'code';
  spec?: Record<string, unknown>;
  source?: string;
  explanation?: string;
  warnings?: string[];
  provider?: string;
  model?: string;
  error?: string;
};

export type StrategyInput = {
  mode: 'composed' | 'code';
  source: string;
  feature: string;
  top_n: number;
  rebalance: number;
  min_turnover: number;
};

// --- the fleet ------------------------------------------------------------

export type Stage = 'registered' | 'backtested' | 'forward_testing' | 'live' | 'retired';

export type StrategyResult = {
  sharpe: number | null;
  total_return?: number;
  max_drawdown?: number;
  fills?: number;
  tier?: string;
  window_days?: number;
  // How many distinct configurations have been tried. The headline is the most
  // recent of them, not the best — a maximum over N is a biased estimate of any
  // one of them, and the latest run is simply a measurement.
  runs: number;
  // The best across configurations, carried beside the latest so a better run
  // does not silently disappear now that the headline is not a maximum.
  best_sharpe?: number | null;
  configuration?: string;
  // Which instruments the run could choose from, and how many actually traded.
  // A result without its universe is ambiguous: the same strategy over nifty50
  // and over four thousand names are different answers.
  universe?: string;
  symbols?: number;
  // Which panel the run was pointed at. The declaration says what a strategy is
  // designed for; this says what it was actually run on, and they can differ.
  asset_class?: string;
  // "replication" means no cost model covered that class, so the figure is
  // gross of costs and not comparable to a net one.
  cost_mode?: string;
  // The real equity curve of the best run, downsampled by the server. Empty
  // when nothing has been run — the sparkline renders nothing rather than a
  // flat line, because a flat line is a claim about a run that did not happen.
  curve?: number[];
  unrecorded?: number;
  is_a_maximum?: boolean;
  at?: string;
  caveat: string;
};

export type FleetStrategy = {
  id: string;
  title: string;
  summary: string;
  kind: string;
  shape: string;
  asset_class: string;
  timeframe: string;
  emits: string;
  lookback: number;
  risk_manager: string;
  trade_manager: string;
  is_strategy_subclass: boolean;
  // Whether the interface can run it. Distinct from is_strategy_subclass: an
  // intraday signal cannot be expressed as target weights (ADR-037) and still
  // runs fine through the minute-bar scanner.
  runnable: boolean;
  engine: 'daily' | 'intraday';
  source: string;
  published: string;
  stage: Stage;
  // null means never measured. It is NOT zero and must never render as zero.
  sharpe: number | null;
  trials: number;
  clears_bar: boolean;
  result: StrategyResult;
};

export type Fleet = {
  bar: number;
  bar_sigma_measured: boolean;
  bar_note: string;
  strategies: FleetStrategy[];
};

export type PreflightCheck = {
  name: string;
  passed: boolean;
  detail: string;
  blocking: boolean;
};

export type Preflight = {
  ok: boolean;
  mode: 'paper' | 'live';
  strategy: string;
  checks: PreflightCheck[];
  blockers: number;
};

export type PanelStatus = {
  loaded: boolean;
  rows: number;
  symbols?: number;
  days?: number;
  first?: string | null;
  last?: string | null;
  thinnest?: number;
  fattest?: number;
  error?: string;
};

export type DataSource = {
  name: string;
  present: boolean;
  files: number;
  bytes?: number;
  newest: string | null;
};

export type DataStatus = {
  panel: PanelStatus;
  universes: { name: string; symbols: number; error?: string }[];
  universe_caveat: string;
  sources: DataSource[];
};

export type Universe = {
  name: string;
  symbols: number;
  recommended: boolean;
  note: string;
};

export type UniverseList = {
  universes: Universe[];
  default: string;
  caveat: string;
};

// --- the full report ------------------------------------------------------

export type Constituent = {
  symbol: string;
  fills: number;
  bought_qty: number;
  sold_qty: number;
  bought_value: number;
  sold_value: number;
  costs: number;
  open_qty: number;
  mark: number;
  open_value: number;
  contribution: number;
  traded_value: number;
  first_day: string;
  last_day: string;
};

export type OrderRow = {
  day: string;
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  notional: number;
  cost: number;
  client_order_id: string;
};

export type Drawdown = {
  depth: number;
  peak_day: string | null;
  trough_day: string | null;
  recovered_day: string | null;
  still_underwater: boolean;
};

export type Metrics = {
  sharpe: number;
  sortino: number | null;
  total_return: number;
  annualised: number | null;
  volatility: number;
  trading_days: number;
  years: number;
  flat_days: number;
  // How much of the run was actually invested. A Sharpe over a mostly-flat
  // series is not comparable to one from a fully-invested run.
  invested_fraction: number;
  first_move_day: string | null;
  hit_rate: number | null;
  hit_rate_invested: number | null;
  best_day: number | null;
  worst_day: number | null;
  average_gain: number | null;
  average_loss: number | null;
  skew: number;
  kurtosis: number;
  costs: number;
  traded_value: number;
  cost_drag: number | null;
  turnover_x: number | null;
  drawdown: Drawdown;
};

export type Reconciliation = {
  equity_change: number;
  attributed: number;
  residual: number;
  // False means the per-instrument decomposition does not add up to the
  // headline result, and the reader must know before trusting either.
  exact: boolean;
  unmarked_symbols: string[];
};

export type FullReport = {
  strategy_id: string;
  configuration: string;
  universe: string;
  instruments: string[];
  tier: string;
  window_days: number;
  period: [string | null, string | null];
  starting_cash: number;
  final_equity: number;
  metrics: Metrics;
  warnings: string[];
  constituents: Constituent[];
  reconciliation: Reconciliation;
  orders: OrderRow[];
  rejections: { day: string; symbol: string; reason: string }[];
  equity: { days: string[]; values: number[] };
};

export type RunChoice = {
  configuration: string;
  sharpe: number;
  tier: string;
  window_days: number;
  universe: string;
  symbols: number;
  at: string;
};

export type ReportResponse = {
  ok: boolean;
  error?: string;
  report?: FullReport;
  runs?: RunChoice[];
};

export type WindowInfo = {
  ok: boolean;
  error?: string;
  requested_days: number;
  available_days: number;
  window_days: number;
  truncated: boolean;
  panel_first: string | null;
  panel_last: string | null;
  window_first: string | null;
  window_last: string | null;
  // The leading stretch is never traded. Showing "1200 days" while the
  // strategy trades 947 of them invites reading a result as covering a period
  // it does not.
  warmup_days: number;
  asset_class?: string;
  // "replication" means no cost model covers this class, so the run paid
  // nothing to trade and the result is an upper bound.
  cost_mode?: string;
  traded_first: string | null;
  traded_last: string | null;
  traded_days: number;
  universe: string;
};

export type ExplainSection = { title: string; body: string };

export type Explain = {
  procedure: ExplainSection[];
  asset_classes: Capability[];
  strategy: {
    id: string;
    title: string;
    summary: string;
    kind: string;
    shape: string;
    asset_class: string;
    timeframe: string;
    emits: string;
    lookback: number;
    is_strategy_subclass: boolean;
    risk_manager: string;
    trade_manager: string;
    how_it_decides: string;
    source: string;
    published: string;
    // What the PAPER tested, which is not what we run it on. Every intraday
    // signal here was published against MNQ futures or US equities and runs on
    // NSE minute bars.
    tested_on: string;
    recommended_class: string;
    logic: string[];
    example: {
      headline: string;
      rows: { symbol: string; score: number; held: boolean }[];
      held_count: number;
      weight_pct: number;
      footer: string;
      real_note: string;
    } | null;
    runs_here: number;
    latest_sharpe: number | null;
    best_sharpe: number | null;
    best_window_days: number | null;
    best_universe: string;
    best_period_note: string;
    bar: number;
    clears_bar: boolean;
  } | null;
  starting_cash: number;
  rebalance_days: number;
};

// --- the trader snapshot --------------------------------------------------

export type Tile = {
  symbol: string;
  return: number;
  turnover: number;
  close: number;
  // Today's turnover against its own recent median. Null when there is too
  // little history to say — not zero, which would read as "no interest".
  relative_volume: number | null;
  sector: string;
  industry: string;
  market_cap: number | null;
  pe: number | null;
};

export type IndexLevel = {
  symbol: string;
  name: string;
  last: number;
  change_pct: number;
  region: string;
  source: string;
};

export type WorldMover = {
  symbol: string;
  name: string;
  price: number;
  change_pct: number;
  exchange: string;
  /** `gainer` | `loser` | `active` */
  kind: string;
};

export type Bar = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type History = {
  ok: boolean;
  error?: string;
  symbol?: string;
  asset_class?: string;
  bars: Bar[];
  /** Where the bars came from — "price panel", "crypto archive". */
  source?: string;
  first?: string;
  last?: string;
};

export type MacroReading = {
  symbol: string;
  name: string;
  unit: string;
  last: number;
  change_pct: number;
  /** `energy` | `metals` | `risk` | `yields` */
  group: string;
};

export type Story = {
  title: string;
  publisher: string;
  link: string;
  symbols: string[];
  /** Every listed company the headline names, not just the one queried. A
   *  sector piece naming four lenders is one event with four exposures. */
  affects?: string[];
  /** Sectors those companies sit in. */
  sectors?: string[];
  /** Hours since publication. Shown on every headline, because a story with no
   *  visible age is indistinguishable from a stale one. */
  age_hours: number;
};

export type Snapshot = {
  ok: boolean;
  error?: string;
  as_of: string;
  previous: string;
  regime: {
    advancers: number;
    decliners: number;
    unchanged: number;
    breadth_ratio: number | null;
    proxy_return_20d: number;
    volatility: number;
    volatility_before: number | null;
    volatility_rising: boolean;
    proxy_note: string;
  };
  map: {
    tiles: Tile[];
    sized_by: string;
    note: string;
    grouped: boolean;
    covered?: number;
    missing: string;
  };
  movers: { gainers: Tile[]; losers: Tile[]; unusual_volume: Tile[] };
  freshness?: {
    live: boolean;
    quoted: number;
    of: number;
    taken_at: string;
    panel_date: string;
    reason?: string;
  };
  world: {
    available: boolean;
    india: IndexLevel[];
    world: IndexLevel[];
    crypto?: IndexLevel[];
    fx?: IndexLevel[];
    movers: WorldMover[];
    sectors?: { sector: string; change_pct: number; exchange: string }[];
    macro?: MacroReading[];
    macro_2s10s?: number | null;
    taken_at?: string;
    /** Groups carrying values older than `taken_at`, and how old. */
    stale_groups?: string[];
    stale_since?: string;
    errors?: Record<string, string>;
  };
  quotes: {
    available: boolean;
    reason?: string;
    /** Which source priced most of them — `zerodha` or `yahoo`. */
    source?: string;
    sources?: Record<string, number>;
    errors?: Record<string, string>;
    asked?: number;
    quotes: Record<
      string,
      { last: number; previous_close: number; change_pct: number; source: string; at: string }
    >;
    note?: string;
  };
  news: {
    available: boolean;
    reason?: string;
    /** Freshest qualifying story per symbol. Absent means no story, not no check. */
    stories: Record<string, Story>;
    tape: Story[];
    covered?: number;
    asked?: number;
    window?: string;
    note?: string;
  };
  catalysts: {
    available: boolean;
    reason: string;
    events?: {
      title: string;
      country: string;
      at: string;
      impact: string;
      forecast: string;
      previous: string;
      past: boolean;
    }[];
    total?: number;
    high_impact?: number;
  };
  cross_asset: {
    asset_class: string;
    label: string;
    instruments: number;
    as_of: string;
    detail: string;
  }[];
  evidence: {
    bar: number;
    strategies: number;
    clearing: number;
    clearing_names: string[];
    trials: number;
  };
  gaps: string[];
};

export type CloudStatus = {
  configured: boolean;
  reason: string;
  workspace: string;
  bucket: string;
  prefix: string;
  local_files: string[];
  remote_files: string[];
  reachable: boolean;
};

export type MirrorResult = {
  ok: boolean;
  pushed: number;
  pulled: number;
  merged_rows: number;
  failed: string[];
};

export type Capability = {
  asset_class: string;
  timeframe: string;
  supported: boolean;
  detail: string;
};

export type Instrument = {
  symbol: string;
  asset_class: string;
  has_daily: boolean;
  has_minute: boolean;
  rank: number;
  // A scheme code is not a name. Empty for equities and crypto, where the
  // ticker already is one.
  name?: string;
  detail?: string;
};

export type InstrumentList = {
  ok: boolean;
  error?: string;
  batches: string[];
  batch_caveat: string;
  // Classes with data on disk. Anything absent here has no instruments to show.
  asset_classes: string[];
  instruments: Instrument[];
};

export type RunPrice = {
  logged: number;
  configurations: number;
  cached: number;
  new_evaluations: number;
  // Always 0. A batch of backtests writes nothing to the ledger; only
  // `make validate` and `make gate` do, and neither is reachable from here.
  spends_trials: number;
  bar_now: number;
  // Where the bar WOULD stand if this search were recorded. It will not be.
  would_move_bar_to: number;
  unrecorded_search: boolean;
  note: string;
};

export type BatchResult = {
  total: number;
  cached: number;
  computed: number;
  failed: number;
  // Configurations evaluated that the trial ledger will never know about.
  unrecorded: number;
  spent_trials: number;
  note: string;
  // Whether the results reached the bucket. Present because a run that
  // succeeded locally but did not mirror is a real state the UI must be able
  // to show, rather than one it silently reports as a clean success.
  cloud?: { ok: boolean; pushed: number; pulled: number; failed: string[] };
  results: {
    strategy: string;
    cached: boolean;
    error: string;
    result?: { sharpe: number; total_return: number; max_drawdown: number; fills: number };
  }[];
};

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return (await response.json()) as T;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return (await response.json()) as T;
}

export const api = {
  health: () => get<Health>('/api/health'),
  library: () => get<Library>('/api/library'),
  fleet: () => get<Fleet>('/api/fleet'),
  capabilities: () => get<{ matrix: Capability[] }>('/api/capabilities'),
  instruments: (q: string, batch: string, assetClass = '', limit = 60) =>
    get<InstrumentList>(
      `/api/instruments?q=${encodeURIComponent(q)}&batch=${encodeURIComponent(batch)}` +
        `&asset_class=${encodeURIComponent(assetClass)}&limit=${limit}`
    ),
  universes: () => get<UniverseList>('/api/universes'),
  priceRun: (configurations: number, cached: number) =>
    post<RunPrice>('/api/run/price', { configurations, cached }),
  runBatch: (
    strategies: string[],
    days: number,
    tier: 'A' | 'B',
    universe: string,
    instruments: string[] = [],
    assetClass = 'equity'
  ) =>
    post<{ ok: boolean; job?: string; error?: string }>('/api/run/batch', {
      strategies,
      days,
      tier,
      universe,
      instruments,
      asset_class: assetClass,
    }),
  report: (strategy: string, workspace = '', configuration = '') =>
    get<ReportResponse>(
      `/api/report?strategy=${encodeURIComponent(strategy)}` +
        `&workspace=${encodeURIComponent(workspace)}` +
        `&configuration=${encodeURIComponent(configuration)}`
    ),
  window: (days: number, universe = 'all', assetClass = 'equity') =>
    get<WindowInfo>(
      `/api/window?days=${days}&universe=${encodeURIComponent(universe)}` +
        `&asset_class=${encodeURIComponent(assetClass)}`
    ),
  explain: (strategy = '') => get<Explain>(`/api/explain?strategy=${encodeURIComponent(strategy)}`),
  batchJob: (id: string) => get<Omit<Job, 'result'> & { result: BatchResult }>(`/api/jobs/${id}`),
  providers: () => get<{ ok: boolean; providers: Provider[]; error?: string }>('/api/providers'),
  validate: (input: StrategyInput) =>
    post<{ ok: boolean; label?: string; error?: string }>('/api/validate', input),
  draft: (description: string, mode: 'composed' | 'code', provider: string | null) =>
    post<Draft>('/api/draft', { description, mode, provider }),
  backtest: (input: StrategyInput & { days: number; tier: 'A' | 'B'; starting_cash: number }) =>
    post<{ ok: boolean; job?: string; error?: string }>('/api/backtest', input),
  job: (id: string) => get<Job>(`/api/jobs/${id}`),
  cloudStatus: (workspace = '') =>
    get<CloudStatus>(`/api/cloud/status?workspace=${encodeURIComponent(workspace)}`),
  mirror: (workspace = '') => post<MirrorResult>('/api/cloud/mirror', { workspace }),
  preflight: (strategy: string, mode: 'paper' | 'live', workspace = '') =>
    post<Preflight>('/api/deploy/preflight', { strategy, mode, workspace }),
  data: () => get<DataStatus>('/api/data'),
  history: (symbol: string, assetClass = 'equity', days = 400) =>
    get<History>(
      `/api/history?symbol=${encodeURIComponent(symbol)}&asset_class=${assetClass}&days=${days}`,
    ),
  syncData: () => post<{ ok: boolean; job?: string; error?: string }>('/api/data/sync', {}),
  snapshot: (workspace = '') =>
    get<Snapshot>(`/api/snapshot?workspace=${encodeURIComponent(workspace)}`),
  tweezer: (input: { symbols: string[]; start: string; end: string }) =>
    post<{ ok: boolean; job?: string; error?: string }>('/api/tweezer', input),
};

// A Tweezer job returns a different result shape from a backtest job, so it is
// read through its own accessor rather than widening `Job.result`.
export type TweezerJob = Omit<Job, 'result'> & { result: TweezerResult };

export const tweezerJob = (id: string) => get<TweezerJob>(`/api/jobs/${id}`);

export const pct = (value: number) =>
  `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;

export const rupees = (value: number) =>
  `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

// --- Tweezer Bottom -------------------------------------------------------
// A separate shape from BacktestResult on purpose. Tweezer is intraday with a
// conditional entry and a bracket exit; it has no equity curve of target
// weights and no Sharpe, and pretending otherwise would invite comparison
// between two things that are not comparable.

export type TweezerExit = { reason: string; price: number; shares: number };

export type TweezerTrade = {
  symbol: string;
  entry_ts: string | null;
  entry: number;
  stop: number;
  target_1: number;
  target_2: number;
  risk_pct: number;
  shares: number;
  net_pnl: number;
  r_multiple: number;
  exits: TweezerExit[];
};

export type TweezerSymbol = {
  symbol: string;
  sessions: number;
  candles: number;
  setups: number;
  filled: number;
  net_pnl: number;
  costs: number;
};

export type TweezerResult = {
  symbols: TweezerSymbol[];
  trades: TweezerTrade[];
  rejections: [string, number][];
  candles: number;
  sessions: number;
  setups: number;
  filled: number;
  wins: number;
  net_pnl: number;
  period: [string, string];
  caveats: string[];
};
