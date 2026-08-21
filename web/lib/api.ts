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
  // How many distinct configurations the headline figure was the best of.
  // Inseparable from the figure: a Sharpe means one thing as the only run and
  // another as the highest of forty.
  runs: number;
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
};

export type InstrumentList = {
  ok: boolean;
  error?: string;
  batches: string[];
  batch_caveat: string;
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
  instruments: (q: string, batch: string) =>
    get<InstrumentList>(`/api/instruments?q=${encodeURIComponent(q)}&batch=${encodeURIComponent(batch)}`),
  priceRun: (configurations: number, cached: number) =>
    post<RunPrice>('/api/run/price', { configurations, cached }),
  runBatch: (strategies: string[], days: number, tier: 'A' | 'B') =>
    post<{ ok: boolean; job?: string; error?: string }>('/api/run/batch', { strategies, days, tier }),
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
