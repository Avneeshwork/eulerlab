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

/** A strategy run once on the parameters it actually uses, on the market its
 *  paper tested. For a swept strategy this is the result the library shows —
 *  `FleetStrategy.result` is the daily engine's, which for an intraday signal
 *  is a stale run on a different market with the published parameters. */
export type AdoptedResult = {
  strategy_id: string;
  symbol: string;
  market: string;
  start: string;
  end: string;
  params: Record<string, number>;
  adopted: boolean;
  net_pnl: number;
  gross_pnl: number;
  costs: number;
  fills: number;
  wins: number;
  sessions: number;
  sharpe: number | null;
  /** Cumulative P&L by session, starting at zero. Includes flat days, so the
   *  line does not compress time for a signal that rarely fires. */
  curve: number[];
  max_drawdown: number;
  best_session: number;
  worst_session: number;
  exits: Record<string, number>;
  rejections: Record<string, number>;
  at: string;
};

/** Walk-forward evidence: does the setting chosen in sample survive on days it
 *  was not chosen on? The only out-of-sample number this platform produces. */
export type WalkResult = {
  strategy_id: string;
  symbol: string;
  splits: number;
  pbo: number;
  pbo_verdict: string;
  verdict: string;
  modal_winner: Record<string, number>;
  winner_oos_sharpe: number | null;
  winner_oos_pnl: number;
  median_oos_pnl: number;
  oos_positive_splits: number;
  settings_profitable_oos: number;
  settings_total: number;
  /** True when most of the grid works, which makes a high PBO benign — the
   *  parameter does not matter rather than the search picking noise. */
  most_settings_work: boolean;
};

export type OptimizeSetting = {
  params: Record<string, number>;
  net_pnl: number;
  fills: number;
  wins: number;
  sessions: number;
};

export type OptimizeRow = {
  strategy_id: string;
  title: string;
  source: string;
  tested_on: string;
  paper_url?: string;
  paper_pdf?: string;
  market: string;
  symbol: string;
  candidates: number;
  best_pnl: number;
  median_pnl: number;
  fills: number;
  win_rate: number;
  sessions: number;
  best_params: Record<string, number>;
  // Every setting tried, not just the winner — the grid is what shows whether
  // the best was a peak or a plateau.
  settings: OptimizeSetting[];
  error: string;
  profitable: boolean;
  beats_its_median_by: number;
  // Null whenever the median is not positive. A ratio against a losing median
  // is arithmetic without meaning, and the API sends null rather than a number
  // the UI would have to know not to trust.
  spread_ratio: number | null;
};

export type Optimize = {
  ran: boolean;
  note?: string;
  at?: string;
  start?: string;
  end?: string;
  // A dry run produces identical numbers and spends no trials, so the flag has
  // to reach the screen: a figure from a dry run is not in the ledger.
  dry_run?: boolean;
  // False while a sweep is still running. Partial results are shown, labelled.
  complete?: boolean;
  trials_before?: number;
  trials_after?: number;
  required_t?: number;
  skipped?: string[];
  rows: OptimizeRow[];
};

export type TuningStats = {
  sharpe: number;
  cagr: number;
  total_return: number;
  max_drawdown: number;
  days: number;
};

export type TuningSide = {
  setting: string;
  /** [window, names held, rebalance], in sessions and names. */
  params: number[];
  in_sample: TuningStats;
  holdout: TuningStats;
  whole: TuningStats;
  fills: number;
  costs: number;
  plateau_sharpe: number;
  holdout_rank: number;
  at_2x_costs?: { in_sample: TuningStats; holdout: TuningStats };
};

/** A recorded parameter sweep, chosen on in-sample years and tested once on a
 *  holdout (research 067). */
export type Tuning = {
  ran: true;
  strategy: string;
  grid: { window: number[]; top: number[]; rebalance: number[] };
  settings_run: number;
  in_sample: [string, string];
  holdout_from: string;
  chosen: TuningSide;
  paper: TuningSide | null;
  best_single_point: TuningSide;
  walk_forward: {
    folds: { year: number; chosen: string; next_year: number }[];
    stitched: TuningStats;
    paper_same_years: TuningStats | null;
  };
  pbo: { value: number; splits: number; verdict: string };
  deflated_sharpe: { probability: number; trials: number; noise_bar_sharpe: number };
  rank_correlation_in_sample_vs_holdout: number;
  table: {
    setting: string;
    params: number[];
    in_sample_sharpe: number;
    plateau_sharpe: number;
    holdout_sharpe: number;
    fills: number;
  }[];
  curves: Partial<Record<'chosen' | 'paper' | 'nifty', [string, number][]>>;
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

/** `/api/risk/book`: the deployed book's risk (ADR-071). Money in rupees, shares as fractions. */
export type RiskVarMethod = { method: string; label: string; var95: number; var99: number; es95: number; es99: number };
export type RiskDrawdown = { now: number; deepest: number; deepest_day: string | null; peak_day: string | null; path: [string, number][] };
export type RiskAgainstBacktest = {
  live: { day: number; value: number }[];
  band: { day: number; low: number; mid: number; high: number }[];
  verdict: 'inside' | 'below' | 'above' | 'too_early' | 'no_backtest' | 'not_started';
  expected: number | null;
};
/** A position held only from a close to the next open (ADR-072). */
export type RiskGap = {
  contract: string;
  lots: number;
  lot_size: number;
  notional: number;
  nights: number;
  nights_held: number;
  held_share: number;
  enough: boolean;
  var95_when_held: number;
  es95_when_held: number;
  worst_night: { day: string; pnl: number } | null;
  holds_tonight: boolean;
  held_now: number;
  worst_ever: { day: string; gap: number; pnl: number } | null;
};
export type RiskWhatIf =
  | {
      ok: true;
      deployments: number;
      enough_history: boolean;
      history_days: number;
      var_before?: number;
      var_after?: number;
      var_added?: number;
      var_own?: number;
      var_before_pct?: number;
      var_after_pct?: number;
      correlation_with_book?: number | null;
      most_alike?: { title: string; correlation: number } | null;
      coverage?: number;
      names?: number;
      gap?: RiskGap | null;
    }
  | { ok: false; error: string };
export type RiskDeployment = {
  id: string;
  strategy_id: string;
  title: string;
  status: string;
  /** Its place in the order deployments were created; its colour follows this. */
  slot: number;
  /** The book's VaR if this deployment were stopped. */
  var_without: number | null;
  gap: RiskGap | null;
  /** Starting capital plus deposits, less withdrawals. */
  capital: number;
  starting_capital: number;
  /** Net deposits (+) or withdrawals (−) so far. */
  moved: number;
  equity: number;
  cash: number;
  invested: number;
  positions: number;
  /** Rupees: equity less the money put in. */
  made: number;
  /** Time-weighted: deposits and withdrawals are not returns. */
  since_start: number;
  today: number;
  volatility: number | null;
  var95: number | null;
  var_share: number;
  var_component: number;
  capital_share: number;
  beta: number | null;
  drawdown_now: number;
  drawdown_deepest: number;
  backtest_worst_drawdown: number | null;
  days_live: number;
  coverage: number;
  flat: boolean;
  against_backtest: RiskAgainstBacktest;
};
export type RiskLimit = {
  name: string;
  now: number;
  limit: number;
  unit: string;
  used: number;
  state: 'ok' | 'near' | 'over';
  kind: 'enforced' | 'watch';
  when: string;
};
export type RiskBook = {
  as_of: string | null;
  history_days: number;
  enough_history: boolean;
  window: [string, string] | null;
  book: {
    deployments: number;
    capital: number;
    equity: number;
    cash: number;
    invested: number;
    exposure: number;
    today: number;
    moved: number;
    today_pct: number;
    since_start: number;
    since_start_pct: number;
    var95: number;
    var95_pct: number;
    es95: number;
    var99: number;
    standalone_sum: number;
    diversification: number;
    beta: number | null;
    volatility: number | null;
    drawdown: RiskDrawdown;
    curve: [string, number][];
    names: number;
    shared_names: number;
    coverage: number;
  };
  var: {
    methods: RiskVarMethod[];
    histogram: { from: number; to: number; days: number }[];
    worst_day: { day: string; pnl: number; pct: number } | null;
  };
  deployments: RiskDeployment[];
  names: { symbol: string; value: number; share: number; held_by: number; sector: string }[];
  sectors: { sector: string; value: number; share: number }[];
  correlation: { ids: string[]; titles: string[]; matrix: (number | null)[][] };
  alike: { a: string; b: string; correlation: number }[];
  stress: { key: string; label: string; note: string; loss: number; share: number }[];
  stopped: { id: string; title: string; slot: number; capital: number; equity: number; made: number; made_pct: number; days_live: number; last_day: string | null }[];
  limits: RiskLimit[];
  watch_note: string;
};
export type RiskBookResponse =
  | ({ ok: true; empty: false } & RiskBook)
  | { ok: true; empty: true; reason: string }
  | { ok: false; error: string };

export type FleetStrategy = {
  /** The run on the parameters this strategy actually uses, on the market its
   *  paper tested. Null when no recorded sweep has covered it. */
  adopted?: AdoptedResult | null;
  /** The same strategy on QQQ, whatever market its paper used. For the ten
   *  crypto signals this is the only US evidence there is. */
  on_us?: AdoptedResult | null;
  /** Walk-forward and PBO for this strategy, when one has been run. */
  walk?: WalkResult | null;
  /** The market this signal does best on, of those it has been run on.
   *  Derived server-side from the stored runs, never a stored verdict. */
  best_asset?: {
    market: string;
    symbol: string;
    sharpe: number;
    net_pnl: number;
    /** True when the best market is not the one its paper tested — the case
     *  worth surfacing, and invisible from the row before this existed. */
    is_away: boolean;
    beats: number;
  } | null;
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
  /** `overnight`: a close-to-next-open hold, run as a calculation (research 072). */
  engine: 'daily' | 'intraday' | 'overnight' | 'study';
  /** Why paper trading cannot run it; empty when it can (`deploy.runner.paper_blocker`). */
  deploy_blocker?: string;
  /** Put away by the operator: hidden from the default list, nothing else (ADR-069). */
  archived?: boolean;
  source: string;
  published: string;
  stage: Stage;
  // null means never measured. It is NOT zero and must never render as zero.
  sharpe: number | null;
  trials: number;
  clears_bar: boolean;
  result: StrategyResult;
  /** The rules, one sentence each. */
  logic?: string[];
  /** What one row of the Strategies table shows, in plain terms. */
  table?: StrategyTableFigures;
};

export type StrategyVerdict = 'beats_bar' | 'positive' | 'loses' | 'not_run';

export type StrategyTableFigures = {
  annual_return: number | null;
  trades: number | null;
  win_rate: number | null;
  period: [string | null, string | null];
  /** NIFTYBEES held over the same period, before costs. Equity strategies only. */
  nifty_return: number | null;
  verdict: StrategyVerdict;
};

export type Fleet = {
  market?: { symbol: string; since: string; total_return: number | null };
  bar: number;
  /** The count the bar was actually computed from — both ledgers summed. Not
   *  the same as summing each strategy's own trial count, which is what the
   *  header used to show beside a bar derived from a much larger number. */
  bar_trials: number;
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

export type DeploymentPosition = {
  symbol: string;
  quantity: number;
  average_price: number | null;
  last_price: number;
  value: number;
  weight: number;
  last_traded: string | null;
};

export type DeploymentState = {
  status?: 'ok' | 'halted' | 'waiting' | 'error';
  reason?: string;
  ran_at?: string;
  traded_through?: string | null;
  as_of?: string;
  capital?: number;
  invested?: number;
  equity?: number;
  cash?: number;
  total_return?: number;
  flows?: { amount: number; last_decided: string; entered_at: string; decision_day?: string; applied_day?: string }[];
  pending?: { amount: number; last_decided: string; entered_at: string }[];
  costs?: number;
  curve?: [string, number][];
  book?: DeploymentPosition[];
  fills?: { day: string; symbol: string; side: string; quantity: number; price: number; cost: number }[];
  fills_total?: number;
  rejections?: { day: string; symbol: string; reason: string }[];
  sent_this_run?: number;
  rebalance_every?: number;
  next_rebalance?: string;
  intended?: { wanted?: number; affordable?: number; names?: string[]; cut?: string[]; error?: string };
  warnings?: string[];
  refused_reducing?: number;
  /** The loss limits as the last run saw them (ADR-092). Shares, not percent. */
  loss_limit?: {
    drawdown: number;
    worst: number;
    reduce_at: number | null;
    halt_at: number | null;
    reducing: boolean;
    action: '' | 'reducing' | 'halted';
  };
};

/** One strategy trading forward with its own money (paper only for now). */
export type Deployment = {
  id: string;
  strategy_id: string;
  mode: 'paper' | 'live';
  capital: number;
  start: string;
  created_at: string;
  status: 'active' | 'stopped' | 'halted';
  status_reason: string;
  slippage_bps: number;
  running: string;
  state: DeploymentState;
  reducing: { from: string; to: string | null; why: string; by: string }[];
  reducing_now: boolean;
  limits: { reduce_at: number | null; halt_at: number | null };
};

export type DeployPreview = {
  ok: boolean;
  as_of?: string;
  wanted?: number;
  affordable?: number;
  names?: string[];
  cut?: string[];
  error?: string;
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
  /** The market this run was on. Decides the currency the report is written
   *  in — a QQQ report labelled in rupees is off by the exchange rate. */
  asset_class?: string;
  window_days: number;
  /** The window the scan *saw*, which is not the window it traded. Two runs can
   *  trade the same days and fill identically while seeing different leading
   *  history — which changes indicator warmup and therefore the result. */
  /** Holding the instrument over the same sessions. Null where the run touched
   *  more than one name — a basket is a different claim than "holding this". */
  benchmark?: {
    symbol: string;
    net_pnl: number;
    total_return: number;
    sharpe: number | null;
    max_drawdown: number;
    costs: number;
  } | null;
  data_window?: string[];
  sessions_seen?: number;
  requested_days?: number;
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
  /** Set on a paper or live deployment's report (`deploy/analysis.py`). Its
   *  `equity` is time-weighted; rupees made are here. */
  deployment?: {
    id: string;
    mode: 'paper' | 'live';
    status: string;
    status_reason: string;
    start: string;
    starting_capital: number;
    put_in: number;
    equity: number;
    made: number;
    time_weighted_return: number;
    flows: { day: string; amount: number }[];
    slippage_bps: number;
    actual_equity: number[];
  };
  /** The strategy's longest stored backtest, beside a deployment's figures. */
  backtest?: {
    period: [string, string] | null;
    metrics: Partial<Record<'total_return' | 'annualised' | 'sharpe' | 'sortino' | 'volatility' | 'hit_rate' | 'best_day' | 'worst_day' | 'cost_drag' | 'turnover_x', number | null>>;
    max_drawdown: number | null;
  } | null;
};

export type OptionHistoryPoint = {
  day: string;
  expiry: string;
  days_to_expiry: number;
  forward: number | null;
  atm_strike: number;
  call: number;
  put: number;
  straddle: number;
  atm_iv: number | null;
  pcr_oi: number | null;
  max_pain: number | null;
  traded: boolean;
};

export type OptionHistory = {
  ok: boolean;
  error?: string;
  underlying?: string;
  points?: OptionHistoryPoint[];
  skipped: string[];
};

/** One chain as the options endpoint returns it. */
export type OptionChain = Awaited<ReturnType<(typeof api)['optionChain']>>;

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
  attribution?: Attribution;
};

type Num = number | null;

/** The detailed attribution (`attribution_detail.py`, research 115). */
export type AttributionDetail = {
  seconds: number;
  market_label: string;
  rebuild: { max_gap: Num; trusted: boolean; note: string };
  exposure: {
    invested_mean: Num;
    invested_max: Num;
    by_year: { year: number; invested: Num; holdings: Num; effective_holdings: Num }[];
    frozen: { symbol: string; last_price: string; held_until: string; value: number }[];
    note: string;
  } | null;
  brinson: {
    months: number;
    benchmark: string;
    portfolio_buy_hold: Num;
    benchmark_total: Num;
    benchmark_annual: Num;
    actual_total: Num;
    active: Num;
    allocation: Num;
    selection: Num;
    interaction: Num;
    trading: Num;
    sectors: { sector: string; allocation: Num; selection: Num; interaction: Num; total: Num; average_weight: Num; benchmark_weight: Num }[];
  } | null;
  factors: {
    months: number;
    period_from: string | null;
    period_through: string | null;
    market_label: string;
    model_name: string;
    source_url: string | null;
    r_squared: Num;
    adjusted_r_squared: Num;
    alpha_annual: Num;
    alpha_t: Num;
    strategy_annual: Num;
    risk_free_annual: Num;
    inference: string;
    yearly: { year: number; months: number; strategy_annual: Num; contributions: Record<string, Num> }[];
    exposures: Record<string, { beta: Num; t: Num; factor_annual: Num; contribution_annual: Num }>;
    factors: string;
  } | null;
  factor_note: string | null;
  brinson_note: string | null;
  rolling: { month: string; beta: Num; alpha_annual: Num }[];
  risk: {
    as_of: string;
    volatility_annual: Num;
    invested: Num;
    holdings: { symbol: string; weight: Num; share_of_risk: Num }[];
    sectors: { sector: string; share_of_risk: Num }[];
  } | null;
  drawdowns: { peak: string; trough: string; recovered: string | null; depth: Num; days_to_trough: number; worst: { symbol: string; loss: number; share: Num }[] }[];
  months: Record<'best' | 'worst', { month: string; return: Num; drivers: { symbol: string; profit: number }[] }[]>;
  trades: {
    closed: number;
    best_1pct_trades?: number;
    best_1pct_share_of_gross_profit?: Num;
    payoff_ratio?: Num;
    by_holding_period?: { holding: string; trades: number; net: number; win_rate: Num; average_return: Num }[];
    by_sector?: { sector: string; trades: number; net: number; win_rate: Num }[];
  };
  capacity: {
    entries: number;
    participation: number;
    note?: string;
    median_days_to_trade: Num;
    p90_days_to_trade: Num;
    capital_where_90pct_trade_in_a_day: number;
    capital_where_median_trades_in_a_day: number;
    tightest: { symbol: string; day: string; capital_for_one_day: number }[];
  } | null;
};

/** Where a report's return came from (`attribution.py`). */
export type Attribution = {
  holdings: {
    net_profit: number;
    names: number;
    winners: number;
    losers: number;
    share_of_profit: Record<'top_1' | 'top_5' | 'top_10', number | null>;
    share_of_gross_profit: Record<'top_1' | 'top_5' | 'top_10', number | null>;
    names_for_half: number | null;
    names_for_four_fifths: number | null;
    without_top_1: { total_return: number | null; annualised: number | null };
    without_top_5: { total_return: number | null; annualised: number | null };
    best: { symbol: string; contribution: number }[];
    worst: { symbol: string; contribution: number }[];
  };
  sectors: Record<'sector' | 'industry', { name: string; contribution: number; share: number | null; names: number; winners: number }[]> | null;
  years: { year: string; return: number | null; trading_profit: number; top_symbol: string | null; top_profit: number | null; top_share: number | null }[];
  market: {
    beta: number | null;
    alpha_annual: number | null;
    r_squared: number | null;
    correlation: number | null;
    strategy_total: number | null;
    market_total: number | null;
    from: string;
    through: string;
    strategy_mean_annual: number | null;
    market_mean_annual: number | null;
    from_market_annual: number | null;
    days: number;
    index: string;
  } | null;
  note: string;
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
    /** Where the source can be read. A citation says what to look for; a link
     *  is what a reader actually follows. */
    paper_url?: string;
    /** API path serving the fetched PDF, empty when it is not downloaded. */
    paper_pdf?: string;
    /** What a recorded sweep changed, if anything. Null means no recorded sweep
     *  has covered this strategy — a different fact from a sweep that ran and
     *  found nothing worth adopting, which returns a record with adopted:false. */
    tuning?: {
      adopted: boolean;
      reason: string;
      symbol: string;
      market: string;
      swept_at: string;
      candidates: number;
      fills: number;
      sessions: number;
      best_pnl: number;
      median_pnl: number;
      tail_share: number;
      changed: { name: string; paper: number; adopted: number }[];
      params: Record<string, number>;
      paper_params: Record<string, number>;
      caveat: string;
    } | null;
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
  /** Equity bars back-adjusted for splits and bonuses. */
  adjusted?: boolean;
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
    /** Not live, but newer than the panel: the last prices this machine saw. */
    last_seen?: boolean;
    panel_date: string;
    reason?: string;
  };
  us?: {
    available: boolean;
    reason?: string;
    as_of?: string;
    previous?: string;
    advancers?: number;
    decliners?: number;
    unchanged?: number;
    proxy_return?: number;
    movers: { gainers: Tile[]; losers: Tile[] };
    tiles: Tile[];
    symbols?: number;
    sectors_known?: number;
    source?: string;
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
  listed_at?: string;
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

/** `/api/market-context` (research 120): context a trader reads before the
 *  open. Each section can be unavailable on its own, with a reason. */
export type Unavailable = { available: false; reason: string };
export type Horizon = '1d' | '1w' | '1m' | '3m' | '1y';
export type IndexTrend = {
  name: string;
  as_of: string;
  close: number;
  change: Record<Horizon, number | null>;
  spark: number[];
};
export type ValuationCell = {
  value: number;
  percentile: number | null;
  median: number | null;
  low: number | null;
  high: number | null;
  since: string;
} | null;
/** One verdict card. The gauge fields depend on `key`: Trend draws `spark`
 *  against `spark_average`; Participation and Fear draw `value` on a 0-100
 *  dial with `zones`; Big money draws `value` (0-1) with its `usual` tick. */
export type PulseCard = {
  key: 'trend' | 'participation' | 'fear' | 'money';
  title: string;
  word: string;
  direction: 'up' | 'down' | 'flat';
  tone: 'good' | 'bad' | 'neutral';
  info: string;
  value: number;
  zones?: [number, number];
  spark?: number[];
  spark_average?: number[];
  close?: number;
  average?: number;
  new_highs?: number;
  new_lows?: number;
  level?: number;
  median?: number;
  usual?: number | null;
  percentile?: number;
  /** Trend (Faber): the month-end the word was read on, today's fall from the
   *  52-week high, and its band ("Correction", "Bear market") if any. */
  month_end?: string;
  drawdown?: number;
  badge?: string | null;
  /** Participation: the High-Low Index that confirms it, the 50-day share
   *  and its extreme tag ("Washed out", "Stretched") if any. */
  high_low?: number;
  above_50?: number | null;
  tag?: string | null;
};
/** `/api/market-reports`: the Deals & filings tab (ADR-096). Each section
 *  either carries its data or says why it is missing. */
type Section<T> = ({ available: true } & T) | { available: false; reason: string };
export type Deal = {
  date: string;
  kind: 'bulk' | 'block';
  symbol: string;
  client: string;
  side: string;
  qty: number;
  price: number;
  value_cr: number;
};
export type DealClient = { client: string; buy_cr: number; sell_cr: number; net_cr: number };
export type MtfRow = { symbol: string; cr: number; change: number | null };
export type SastFiling = {
  time: string;
  symbol: string;
  company: string;
  who: string;
  promoter: boolean;
  side: string;
  shares: number;
  pct: number;
  after_pct: number;
  mode: string;
};
export type InsiderFiling = {
  time: string;
  symbol: string;
  company: string;
  regulation: string;
  type: string;
  link: string;
};
export type MarketReports = {
  ok: boolean;
  reason?: string;
  built_at?: string;
  deals?: Section<{
    as_of: string;
    since: string;
    today: Deal[];
    today_count: number;
    largest: Deal[];
    buyers: DealClient[];
    sellers: DealClient[];
    count: number;
  }>;
  ban?: Section<{ as_of: string; symbols: string[]; added: string[]; removed: string[] }>;
  mtf?: Section<{
    as_of: string;
    compared_with: string;
    totals_cr: Record<string, number>;
    largest: MtfRow[];
    rising: MtfRow[];
    falling: MtfRow[];
  }>;
  shorts?: Section<{
    as_of: string;
    short_sold: { symbol: string; qty: number }[];
    short_count: number;
    slbm_as_of: string | null;
    lent: { symbol: string; qty: number; fee: number }[];
  }>;
  filings?: Section<{ days: number; sast: SastFiling[]; insider: InsiderFiling[]; insider_count: number }>;
  pledges?: Section<{
    as_of: string;
    count: number;
    top: {
      company: string;
      of_promoter_pct: number;
      of_company_pct: number;
      promoter_pct: number;
      quarter: string;
    }[];
  }>;
  ipos?: Section<{
    as_of: string;
    open: {
      symbol: string;
      company: string;
      opens: string;
      closes: string;
      price: string;
      subscribed: number;
      series: string;
    }[];
    listed: { symbol: string; company: string; listed: string; price: string; series: string }[];
  }>;
};

export type MarketContext = {
  ok: boolean;
  pulse: { available: true; cards: PulseCard[]; note: string } | Unavailable;
  strip:
    | {
        available: true;
        indices: IndexTrend[];
        vix: { level: number; percentile_1y: number | null; median_1y: number; note: string } | null;
        gsec_note: string;
      }
    | Unavailable;
  valuation:
    | {
        available: true;
        indices: { name: string; as_of: string; since: string; pe: ValuationCell; pb: ValuationCell; dy: ValuationCell }[];
        note: string;
      }
    | Unavailable;
  sectors:
    | {
        available: true;
        benchmark: string;
        sectors: {
          name: string;
          change_1d: number | null;
          relative: { '1w': number | null; '1m': number | null; '3m': number | null };
          momentum: number | null;
          rising: boolean;
          phase: 'leading' | 'weakening' | 'lagging' | 'improving' | null;
        }[];
        note: string;
      }
    | Unavailable;
  breadth:
    | {
        available: true;
        as_of: string;
        stocks: number;
        latest: {
          above_20: number | null;
          above_50: number | null;
          above_200: number | null;
          new_highs: number;
          new_lows: number;
          record_high_percent: number | null;
          high_low_index: number | null;
        };
        series: {
          days: string[];
          above_20: (number | null)[];
          above_50: (number | null)[];
          above_200: (number | null)[];
          new_highs: number[];
          new_lows: number[];
          high_low_index: (number | null)[];
        };
        new_high_names: BreadthName[];
        new_low_names: BreadthName[];
        note: string;
      }
    | Unavailable;
  positioning:
    | {
        available: true;
        as_of: string;
        filling: boolean;
        participants: {
          participant: 'FII' | 'DII' | 'Pro' | 'Client';
          index_futures_long_share: number | null;
          change_1d: number | null;
          change_5d: number | null;
          percentile: number | null;
          usual: number | null;
          history_days: number;
          index_calls_net: number;
          index_puts_net: number;
        }[];
        series: { days: string[] } & Record<'FII' | 'DII' | 'Pro' | 'Client', (number | null)[]>;
        note: string;
      }
    | (Unavailable & { filling?: boolean });
  options:
    | {
        available: true;
        as_of: string;
        expiry: string;
        days_to_expiry: number | null;
        spot_forward: number | null;
        pcr_oi: number | null;
        pcr_oi_before: number | null;
        max_pain: number | null;
        atm_iv: number | null;
        atm_iv_before: number | null;
        straddle: number | null;
        since: string;
        note: string;
        expected_move?: { points: number; share: number; low: number; high: number };
      }
    | Unavailable;
  delivery:
    | {
        available: true;
        as_of: string;
        sessions: number;
        found: number;
        stocks: {
          symbol: string;
          delivery_pct: number;
          usual_pct: number;
          ratio: number;
          change_1d: number | null;
          turnover_cr: number;
        }[];
        note: string;
      }
    | Unavailable;
};
export type BreadthName = { symbol: string; close: number; change_1d: number | null; turnover_cr: number };

/** `/api/fii-dii` (ADR-098): NSE's provisional cash flows, ₹ crore. */
export type FiiDiiGroup = {
  buy: number;
  sell: number;
  net: number;
  net_5d: number;
  net_month: number;
  /** Sessions in a row on the latest side: +3 buying, −2 selling. */
  streak: number;
};
export type FiiDiiMonth = { month: string; fii: number; dii: number; days: number };
export type FiiDiiFlows =
  | {
      available: true;
      as_of: string;
      known_at: string;
      days_held: number;
      first_day: string;
      fii: FiiDiiGroup;
      dii: FiiDiiGroup;
      series: { days: string[]; fii: number[]; dii: number[] };
      months: FiiDiiMonth[];
      note: string;
    }
  | { available: false; reason: string };

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

/* ---------------- strategy builder ---------------- */

export type BuilderParam = {
  name: string;
  label: string;
  default: number;
  min: number;
  max: number;
  integer: boolean;
};

export type BuilderIndicator = {
  name: string;
  label: string;
  group: string;
  description: string;
  unit: 'price' | 'percent' | 'ratio' | 'volume';
  params: BuilderParam[];
};

export type BuilderOperand = {
  kind: 'indicator' | 'value';
  name: string;
  params: Record<string, number>;
  multiplier: number;
  value: number;
};

export type BuilderComparator = 'above' | 'below' | 'crosses_above' | 'crosses_below';

export type BuilderRule = { left: BuilderOperand; op: BuilderComparator; right: BuilderOperand };

export type BuilderRuleGroup = { match: 'all' | 'any'; rules: BuilderRule[] };

export type BuilderSpec = {
  id: string;
  name: string;
  description: string;
  universe: {
    asset_class: string;
    universe: string;
    instruments: string[];
    min_price: number;
    max_price: number;
    min_turnover: number;
  };
  entry: BuilderRuleGroup;
  exit: BuilderRuleGroup;
  sizing: {
    method: 'equal' | 'volatility_scaled';
    max_positions: number;
    vol_target_pct: number;
    ranking: { by: BuilderOperand; order: 'highest' | 'lowest' } | null;
  };
  risk: {
    stop_loss_pct: number;
    take_profit_pct: number;
    trailing_stop_pct: number;
    max_hold_days: number;
  };
};

export type BuilderCatalog = {
  indicators: BuilderIndicator[];
  comparators: { name: BuilderComparator; label: string }[];
  templates: BuilderSpec[];
  limits: { max_rules: number; max_positions: number };
  caveats: string[];
};

export type BuilderCheck =
  | { ok: true; id: string; summary: string[]; warmup: number; digest: string }
  | { ok: false; errors: string[] };

export type SavedBuilderStrategy = {
  spec: BuilderSpec;
  summary: string[];
  result: { sharpe: number | null; runs: number; caveat: string; total_return?: number; max_drawdown?: number; fills?: number };
};

/* ---------------- research library ---------------- */

export type ResearchLinkKind = 'builder' | 'registered' | 'tweezer';

export type ResearchLink = { kind: ResearchLinkKind; id: string; note: string; timeframe: number };

export type ResearchStats = {
  trades: number;
  win_rate: number | null;
  profit_factor: number | null;
  avg_win_pct: number | null;
  avg_loss_pct: number | null;
  expectancy_pct: number | null;
  total_pct: number;
  max_drawdown_pct: number;
};

export type ResearchLinkView = ResearchLink & {
  title: string;
  exists: boolean;
  runnable: boolean;
  result: SavedBuilderStrategy['result'] | null;
  measured?: {
    window: [string, string];
    universe: string;
    hold_sessions: number;
    signals: number;
    triggered: number;
    gross: ResearchStats;
    net: ResearchStats;
  }[];
};

export type Paper = {
  id: string;
  title: string;
  authors: string;
  year: number | null;
  kind: 'paper' | 'report' | 'book' | 'note';
  source_url: string;
  pdf: string;
  added: string;
  status: 'idea' | 'specified' | 'backtested' | 'rejected' | 'adopted';
  markets: string[];
  summary: string;
  trade_idea: string;
  implementation: string;
  red_flags: string[];
  reported_results: string;
  hypothesis: string;
  strategies: ResearchLink[];
};

export type PaperView = { paper: Paper; links: ResearchLinkView[] };

export type PaperDraft = Pick<Paper, 'summary' | 'trade_idea' | 'implementation' | 'red_flags' | 'reported_results' | 'markets'>;

async function del<T>(path: string): Promise<T> {
  const response = await fetch(path, { method: 'DELETE' });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return (await response.json()) as T;
}

export const api = {
  builderCatalog: () => get<BuilderCatalog>('/api/builder/catalog'),
  papers: () => get<{ papers: PaperView[] }>('/api/research/papers'),
  draftPaper: (input: { title: string; authors: string; year: number | null; source_url: string; source_text: string; provider: string; model: string }) =>
    post<{ ok: true; draft: PaperDraft; provider: string; model: string } | { ok: false; error: string }>('/api/research/draft', input),
  paperStrategy: (paperId: string, provider: string, model: string) =>
    post<Draft>(`/api/research/papers/${encodeURIComponent(paperId)}/strategy`, { provider, model }),
  savePaper: (paper: Partial<Paper>) =>
    post<({ ok: true } & PaperView) | { ok: false; errors: string[] }>('/api/research/papers', { paper }),
  linkPaper: (paperId: string, link: Partial<ResearchLink>) =>
    post<{ ok: boolean; errors?: string[] }>(`/api/research/papers/${encodeURIComponent(paperId)}/links`, { link }),
  builderValidate: (spec: BuilderSpec) => post<BuilderCheck>('/api/builder/validate', { spec }),
  builderSave: (spec: BuilderSpec) =>
    post<
      | { ok: true; id: string; summary: string[]; spec: BuilderSpec }
      | { ok: false; errors: string[] }
    >('/api/builder/save', { spec }),
  builderStrategies: () => get<{ strategies: SavedBuilderStrategy[] }>('/api/builder/strategies'),
  builderDelete: (id: string) =>
    del<{ ok: boolean; error?: string }>(`/api/builder/strategies/${encodeURIComponent(id)}`),
  health: () => get<Health>('/api/health'),
  library: () => get<Library>('/api/library'),
  fleet: () => get<Fleet>('/api/fleet'),
  archiveStrategies: (ids: string[], archived: boolean) =>
    post<{ ok: true; archived: string[] } | { ok: false; error: string }>('/api/strategies/archive', { ids, archived }),
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
    assetClass = 'equity',
    // An options bag rather than a seventh and eighth positional argument.
    // `runBatch(ids, 800, 'B', 'all', [], 'us', '2022-01-01', '2022-12-31', 500000)`
    // is a line nobody can read, and a call that transposes two of them is a
    // different backtest that still runs.
    options: { start?: string; end?: string; startingCash?: number } = {}
  ) =>
    post<{ ok: boolean; job?: string; error?: string }>('/api/run/batch', {
      strategies,
      days,
      tier,
      universe,
      instruments,
      asset_class: assetClass,
      start: options.start ?? '',
      end: options.end ?? '',
      starting_cash: options.startingCash ?? 1_000_000,
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
  /** One point per landed day: the nearest-expiry ATM straddle, its IV and the forward. */
  optionHistory: (underlying: string, days = 30) =>
    get<OptionHistory>(
      `/api/options/history?underlying=${encodeURIComponent(underlying)}&days=${days}`
    ),
  optionDays: () => get<{ ok: boolean; days: string[]; total: number }>('/api/options/days'),
  optionChain: (underlying: string, expiry = '', day = '') =>
    get<{
      ok: boolean;
      underlying: string;
      day: string;
      expiry: string;
      expiries: string[];
      days_to_expiry: number;
      forward: number | null;
      forward_source: string;
      discount: number;
      strikes: {
        strike: number;
        call_price: number | null;
        call_oi: number | null;
        call_iv: number | null;
        call_traded: boolean;
        put_price: number | null;
        put_oi: number | null;
        put_iv: number | null;
        put_traded: boolean;
        call_delta: number | null;
        call_gamma: number | null;
        call_vega: number | null;
        call_theta: number | null;
        put_delta: number | null;
        put_gamma: number | null;
        put_vega: number | null;
        put_theta: number | null;
        lot_size: number | null;
      }[];
      atm_strike: number | null;
      max_pain: { strike: number; payout: number; curve: [number, number][] } | null;
      put_call_ratio: {
        by_open_interest: number | null;
        by_volume: number | null;
        call_open_interest: number;
        put_open_interest: number;
        call_volume: number;
        put_volume: number;
      };
      gamma: {
        total: number;
        flip: number | null;
        convention: string;
        points: { strike: number; exposure: number }[];
      };
      smile: {
        strike: number;
        moneyness: number;
        call_iv: number | null;
        put_iv: number | null;
      }[];
      findings: { check: string; severity: string; detail: string }[];
      findings_note: string;
      error?: string;
      available?: string[];
    }>(
      `/api/options/chain?underlying=${encodeURIComponent(underlying)}` +
        (expiry ? `&expiry=${encodeURIComponent(expiry)}` : '') +
        (day ? `&day=${encodeURIComponent(day)}` : '')
    ),
  mode: () =>
    get<{
      ok: boolean;
      mode: string;
      live_possible: boolean;
      why: string;
      kill_switch_tripped: boolean;
    }>('/api/mode'),
  riskBook: () => get<RiskBookResponse>('/api/risk/book'),
  riskWhatIf: (strategy: string, capital: number) => post<RiskWhatIf>('/api/risk/what-if', { strategy, capital }),
  risk: () =>
    get<{
      ok: boolean;
      tripped: boolean;
      reason: string;
      limits: { name: string; value: number; unit: string; note: string }[];
      reset_note: string;
      error?: string;
    }>('/api/risk'),
  explain: (strategy = '') => get<Explain>(`/api/explain?strategy=${encodeURIComponent(strategy)}`),
  optimize: () => get<Optimize>('/api/optimize'),
  tuning: (strategy: string) =>
    get<Tuning | { ran: false; strategy: string }>(`/api/tuning?strategy=${encodeURIComponent(strategy)}`),
  batchJob: (id: string) => get<Omit<Job, 'result'> & { result: BatchResult }>(`/api/jobs/${id}`),
  providers: () => get<{ ok: boolean; providers: Provider[]; error?: string }>('/api/providers'),
  validate: (input: StrategyInput) =>
    post<{ ok: boolean; label?: string; error?: string }>('/api/validate', input),
  draft: (description: string, mode: 'composed' | 'code', provider: string | null) =>
    post<Draft>('/api/draft', { description, mode, provider }),
  backtest: (input: StrategyInput & { days: number; tier: 'A' | 'B'; starting_cash: number }) =>
    post<{ ok: boolean; job?: string; error?: string }>('/api/backtest', input),
  job: (id: string) => get<Job>(`/api/jobs/${id}`),
  cloudStatus: (workspace = '', refresh = false) =>
    get<CloudStatus>(
      `/api/cloud/status?workspace=${encodeURIComponent(workspace)}${refresh ? '&refresh=true' : ''}`
    ),
  mirror: (workspace = '') => post<MirrorResult>('/api/cloud/mirror', { workspace }),
  preflight: (strategy: string, mode: 'paper' | 'live', workspace = '') =>
    post<Preflight>('/api/deploy/preflight', { strategy, mode, workspace }),
  deployments: () => get<{ deployments: Deployment[] }>('/api/deployments'),
  reportAttribution: (strategy: string, workspace = '', configuration = '') =>
    get<{ ok: boolean; detail?: AttributionDetail; error?: string }>(
      `/api/report/attribution?strategy=${encodeURIComponent(strategy)}&workspace=${encodeURIComponent(workspace)}&configuration=${encodeURIComponent(configuration)}`,
    ),
  deploymentAttribution: (id: string, workspace = '') =>
    get<{ ok: boolean; detail?: AttributionDetail; error?: string }>(
      `/api/deployments/${encodeURIComponent(id)}/attribution?workspace=${encodeURIComponent(workspace)}`,
    ),
  deploymentReport: (id: string, workspace = '') =>
    get<{ ok: boolean; report?: FullReport; error?: string; attribution?: Attribution }>(
      `/api/deployments/${encodeURIComponent(id)}/report?workspace=${encodeURIComponent(workspace)}`,
    ),
  deployPreview: (strategy: string, capital: number) =>
    post<DeployPreview>('/api/deployments/preview', { strategy, capital }),
  deploy: (strategy: string, mode: 'paper' | 'live', capital: number) =>
    post<{ ok: boolean; error?: string; deployment?: Deployment }>('/api/deployments', {
      strategy,
      mode,
      capital,
    }),
  runDeployment: (id: string) =>
    post<{ ok: boolean; error?: string }>(`/api/deployments/${encodeURIComponent(id)}/run`, {}),
  stopDeployment: (id: string) =>
    post<{ ok: boolean; error?: string }>(`/api/deployments/${encodeURIComponent(id)}/stop`, {}),
  reduceOnly: (id: string, on: boolean) =>
    post<{ ok: boolean; error?: string }>(`/api/deployments/${encodeURIComponent(id)}/reduce`, { on }),
  deploymentLimits: (id: string, reduce_at: number | null, halt_at: number | null) =>
    post<{ ok: boolean; error?: string }>(`/api/deployments/${encodeURIComponent(id)}/limits`, {
      reduce_at,
      halt_at,
    }),
  deploymentFlow: (id: string, action: 'add' | 'withdraw', amount: number) =>
    post<{ ok: boolean; error?: string; flow?: { amount: number; last_decided: string; entered_at: string } }>(
      `/api/deployments/${encodeURIComponent(id)}/flow`,
      { action, amount },
    ),
  data: () => get<DataStatus>('/api/data'),
  /** `adjusted` back-adjusts equity bars for splits and bonuses (the SIP needs it). */
  history: (symbol: string, assetClass = 'equity', days = 400, adjusted = false) =>
    get<History>(
      `/api/history?symbol=${encodeURIComponent(symbol)}&asset_class=${assetClass}&days=${days}${adjusted ? '&adjusted=true' : ''}`,
    ),
  syncData: () => post<{ ok: boolean; job?: string; error?: string }>('/api/data/sync', {}),
  /** Fetch today's data from every source, then mirror it. Different from
   *  `syncData`, which uploads whatever is already on disk — that can mirror a
   *  stale landing zone to the cloud and report success. */
  feedPlan: () =>
    get<{
      ok: boolean;
      sources: string[];
      excluded: string[];
      keeps_local: boolean;
      busy: { what?: string; since?: string } | null;
    }>('/api/data/feed/plan'),
  /** Every dataset: last day held, the day it should reach, and the fix. */
  coverage: () => get<DataCoverage>('/api/data/coverage'),
  /** Run feed steps: every step by default, or only `only` (one dataset's
   *  button), with or without the B2 mirror at the end. */
  refreshFeed: (only: string[] = [], mirror = true) =>
    post<{ ok: boolean; job?: string; error?: string }>('/api/data/feed', { only, mirror }),
  /** Count (dry run) or delete local landing files B2 holds at the same size. */
  pruneData: (dryRun: boolean) =>
    post<{ ok: boolean; job?: string; error?: string }>('/api/data/prune', { dry_run: dryRun }),
  /** `live` false answers from held data alone, without waiting on a broker. */
  marketContext: () => get<MarketContext>('/api/market-context'),
  fiiDii: () => get<FiiDiiFlows>('/api/fii-dii'),
  marketReports: () => get<MarketReports>('/api/market-reports'),
  snapshot: (workspace = '', live = true) =>
    get<Snapshot>(`/api/snapshot?workspace=${encodeURIComponent(workspace)}&live=${live}`),
  tweezer: (input: {
    symbols: string[];
    start: string;
    end: string;
    universe?: string;
    timeframe?: number;
  }) =>
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

export type CoverageRow = {
  group: string;
  name: string;
  last: string;
  expected: string;
  behind: number;
  status: 'ok' | 'behind' | 'stale' | 'missing' | 'info';
  detail: string;
  fix: string;
  /** The feed steps its own Update button runs; empty when no button can. */
  steps: string[];
};

export type DataCoverage = {
  ok: boolean;
  rows: CoverageRow[];
  summary: Record<string, number>;
  busy: { what?: string; since?: string } | null;
  checked_at: string;
};

/* ---------------- assistant ---------------- */

export type AssistantTool = { name: string; description: string };

/** Whether the assistant can answer, and which host a question would go to. */
export type AssistantStatus = {
  ready: boolean;
  reason: string;
  provider?: string;
  model?: string;
  host?: string;
  local?: boolean;
  /** How retention is handled on that host, in words. */
  policy?: string;
  tools: AssistantTool[];
  choices: AssistantChoice[];
};

/** One configured model. `ready` false means a lock refuses it; `reason` says why. */
export type AssistantChoice = {
  name: string;
  model: string;
  host: string;
  free: boolean;
  ready: boolean;
  reason: string;
  /** The reason in two or three words, for the list. Empty when ready. */
  blocked: string;
  policy: string;
  is_default: boolean;
};

export type AssistantLiveModel = { id: string; name: string };

export type AssistantTurn = { role: 'user' | 'assistant'; content: string };

/** One tool the model called: this, and the question, is all that was sent. */
export type AssistantUse = { tool: string; arguments: string; characters: number };

export type AssistantReply =
  | { ok: true; text: string; provider: string; model: string; host: string; used: AssistantUse[] }
  | { ok: false; error: string };

export const assistantStatus = (provider = '', model = '') =>
  get<AssistantStatus>(`/api/assistant/status?provider=${encodeURIComponent(provider)}&model=${encodeURIComponent(model)}`);
export const assistantModels = () =>
  get<{ ok: boolean; models: AssistantLiveModel[]; error?: string }>('/api/assistant/models');
export const assistantChat = (messages: AssistantTurn[], provider = '', model = '') =>
  post<AssistantReply>('/api/assistant/chat', { messages, provider, model });

/* ---------------- company pages ---------------- */

/** One statement: periods oldest first, rows in the source's order. */
export type CompanyTable = {
  periods: string[];
  rows: { label: string; values: (number | null)[] }[];
};

export type CompanyPeer = {
  symbol: string;
  name: string;
  market_cap: number | null;
  pe: number | null;
  roce: number | null;
  roe: number | null;
};

export type FairValue = {
  status: 'available' | 'unavailable';
  symbol?: string;
  model_version?: string;
  run_id?: string;
  confidence?: string;
  confidence_reason?: string;
  reason?: string;
  fair_value_per_share?: number | null;
  current_price?: number | null;
  upside?: number | null;
  range_type?: 'roe_persistence_scenarios' | 'none';
  valuation_method?: string;
  price_as_of?: string;
  fundamentals_as_of?: string;
  fundamentals_path?: string;
  sector_model?: string;
  models?: Record<string, number | null>;
  model_range?: { low: number; high: number } | null;
  cost_of_equity?: {
    rate: number;
    uncapped_rate: number;
    risk_free_rate: number;
    risk_free_source: string;
    risk_free_as_of: string;
    risk_free_fallback: boolean;
    premia: { market: number; size: number; value: number };
    market_erp_as_of?: string;
    premia_sources?: { market: string; size: string; value: string };
    betas: { MF: number; SMB: number; HML: number };
    raw_betas?: { MF: number; SMB: number; HML: number } | null;
    beta_observations: number;
    beta_fallback: boolean;
    clamped?: boolean;
    method?: string;
    factor_release: string;
    factor_through: string;
    factor_premium_observations: Record<string, number>;
    factor_source: string;
    factor_sha256: string;
    beta_source: string;
    beta_sha256: string;
  };
  assumptions?: {
    book_value_per_share: number;
    reported_eps_per_share: number;
    current_roe?: number;
    historical_roe?: { period: string; roe: number }[];
    terminal_roe_source?: string;
    payout_ratio: number;
    payout_assumed: boolean;
    forecast_method: string;
    forecast_roe: { year_1: number; year_2: number; year_3: number; year_5?: number; year_10?: number };
    forecast_eps: { year_1: number; year_2?: number; year_5?: number; year_10?: number };
    valuation_scenarios?: Record<string, {
      value: number;
      year_5_roe_anchor: number;
      long_run_roe: number;
      terminal_mode: string;
      terminal_growth: number;
      terminal_payout: number;
      terminal_book_value: number;
      terminal_value: number;
      year_1_eps: number;
      year_5_eps: number;
      year_10_eps: number;
      year_1_roe: number;
      year_5_roe: number;
      year_10_roe: number;
      explicit_years: number;
    }>;
    book_value_roll_forward?: { year_1: number; year_2: number };
    sector_model: string;
    sensitivity: Record<string, number>;
  };
  warnings?: string[];
};

/** Everything held about one company. Statement figures are in ₹ crore;
 *  prices and per-share figures in ₹; `market_cap` in ₹. */
export type CompanyPage = {
  ok: true;
  symbol: string;
  name: string;
  /** Date of the fundamentals file the page was built from. */
  as_of: string;
  consolidated: boolean | null;
  profile: {
    sector: string;
    industry: string;
    sector_levels: string[];
    market_cap: number | null;
    price: number | null;
    pe: number | null;
    roce: number | null;
    roe: number | null;
    book_value: number | null;
    dividend_yield: number | null;
    indices: string[];
  };
  /** Computed from the statements; null when an input is missing. */
  metrics: {
    annual_period: string | null;
    quarter_period: string | null;
    debt_to_equity: number | null;
    net_margin: number | null;
    operating_margin: number | null;
    eps: number | null;
    eps_ttm: number | null;
    sales_growth: number | null;
    profit_growth: number | null;
    quarter_sales_growth: number | null;
    quarter_profit_growth: number | null;
    free_cash_flow: number | null;
    promoter_holding: number | null;
  };
  tables: Record<string, CompanyTable>;
  peers: {
    industry: string;
    count: number;
    median_pe: number | null;
    pe_count?: number;
    valuation_median_pe?: number | null;
    valuation_median_pb?: number | null;
    median_roe?: number | null;
    rows: CompanyPeer[];
  };
  price: {
    /** Adjusted closes, oldest first. */
    series: [string, number][];
    /** Dividend-reinvested closes used for risk estimation. */
    total_return_series?: [string, number][];
    total_return_factor_through?: string;
    day?: string;
    close?: number;
    previous_close?: number | null;
    open?: number | null;
    volume?: number | null;
    high_52w?: number;
    low_52w?: number;
    /** A session the bhavcopy has not reached yet, built from Kite minute bars. */
    provisional?: {
      d: string;
      open: number;
      high: number;
      low: number;
      close: number;
      volume: number;
      source: string;
    };
  };
  news: { title: string; link: string; publisher: string; time: string }[];
  fair_value?: FairValue;
  /** What a stock page usually shows and no landed file holds. */
  not_held: string[];
};

export type CompanyHit = {
  symbol: string;
  name: string;
  industry: string;
  market_cap: number | null;
};

export const companyPage = (symbol: string) =>
  get<CompanyPage | { ok: false; error: string }>(`/api/company/${encodeURIComponent(symbol)}`);
export const companySearch = (q: string, limit = 8) =>
  get<{ total: number; rows: CompanyHit[] }>(
    `/api/companies?q=${encodeURIComponent(q)}&limit=${limit}`,
  );

/* ---------------- Kite login ---------------- */

/** Whether today's Kite token is held. Never carries the token itself. */
export type KiteStatus = {
  configured: boolean;
  fresh: boolean;
  user?: string;
  expires_at?: string;
  /** Zerodha's own login page for this app. */
  login_url?: string;
  reason: string;
};

export const kiteStatus = () => get<KiteStatus>('/api/kite/status');
/** `pasted` is the address Zerodha redirected to, or the request_token alone. */
export const kiteLogin = (pasted: string) =>
  post<{ ok: true; user: string; expires_at: string } | { ok: false; error: string }>(
    '/api/kite/login',
    { pasted },
  );

/* ---------------- FYERS login ---------------- */

/** Whether today's FYERS token is held. Never carries the token itself. */
export type FyersStatus = {
  configured: boolean;
  fresh: boolean;
  user?: string;
  expires_at?: string;
  login_url?: string;
  reason: string;
};

export const fyersStatus = () => get<FyersStatus>('/api/fyers/status');
/** The full redirect address contains the one-time auth code and state. */
export const fyersLogin = (pasted: string) =>
  post<{ ok: true; user: string; expires_at: string } | { ok: false; error: string }>(
    '/api/fyers/login',
    { pasted },
  );
/* ---------------- agent network (ADR-085) ---------------- */

export type AgentRow = {
  name: string;
  title: string;
  job: string;
  enabled: boolean;
  switched: 'definition' | 'operator';
  schedule: string;
  uses_model: boolean;
  daily_requests: number;
  ceiling: number;
  used_today: number;
  never: string[];
  running: boolean;
  brief: string;
  latest: {
    run_id: string;
    status: string;
    summary: string;
    started: string;
    items: number;
    model: string;
  } | null;
};

export type AgentsResponse = {
  ok: boolean;
  agents: AgentRow[];
  trials: { per_week: number | null; spent: number };
  brief_all: string;
  inbox: number;
  log_ok: boolean;
  log_problem: string;
};

export type AgentItem = {
  id: string;
  agent: string;
  run: string;
  at: string;
  kind: string;
  title: string;
  body: string;
  severity: 'info' | 'warn' | 'critical';
  needs_approval: boolean;
  ref: string;
  data: Record<string, unknown>;
};

export type AgentOutput = {
  agent: string;
  run_id: string;
  started: string;
  finished: string;
  status: string;
  summary: string;
  items: AgentItem[];
  briefs: string[];
  model: string;
  requests: number;
  notes: string[];
  data: Record<string, unknown>;
};

export type QualityCheck = { name: string; state: 'pass' | 'warn' | 'fail' | 'info'; detail: string };
export type DatasetGrade = {
  name: string;
  grade: 'A' | 'B' | 'C' | 'D';
  freshness: string;
  critical: boolean;
  min_grade: string;
  usable: boolean;
  point_in_time: boolean;
  checks: QualityCheck[];
};

export type DeskTicket = {
  id: string;
  deployment: string;
  strategy: string;
  mode: string;
  rebalance: string;
  equity: number;
  sells: { symbol: string; quantity: number; value: number }[];
  buys: { symbol: string; target_value: number }[];
  holds: string[];
  est_cost: number;
  checks: { name: string; ok: boolean; detail: string }[];
  reason: string;
  decision: string;
  blocked: boolean;
};

export type AgentStep = { at: string; kind: string; text: string };

/** One agent's newest run as it stands: `/api/agents/activity` (ADR-091). */
export type AgentActivity = {
  name: string;
  title: string;
  job: string;
  enabled: boolean;
  uses_model: boolean;
  cli_only: boolean;
  schedule?: string;
  state: 'idle' | 'running' | 'stopped' | 'ok' | 'skipped' | 'over_budget' | 'refused' | 'failed';
  run_id: string;
  started: string;
  summary: string;
  now: string;
  steps: AgentStep[];
  /** The last run's items, worst first. */
  findings?: AgentFinding[];
  findings_total?: number;
};

/** The market brief as data (ADR-105): `agents/workers/market_brief.build_brief`. */
export type MarketBrief = {
  mode: 'pre-open' | 'after-close' | 'weekend';
  day: string;
  as_of: string | null;
  headline: string;
  tone: 'weak' | 'supportive' | 'mixed' | 'incomplete';
  missing: string[];
  matters: { key: string; score: number; title: string; fact: string; meaning: string; page: string }[];
  range: { close?: number; low?: number; high?: number; move?: number };
  levels: string[];
  scenarios: string[];
  coming_up: { items: { when: string; what: string; why: string }[]; not_covered: string[] };
  attention: { book: string; why: string }[];
  books: string[];
  rows: { signal: string; value: string; normal: string; word: string; why: string }[];
  underneath: {
    leading: string[];
    lagging: string[];
    new_highs: string[];
    new_lows: string[];
    delivery: string[];
    deals: string[];
    deals_as_of?: string | null;
    flows?: string;
  };
  review: string[];
  review_title?: string;
  history?: string[];
  books_history?: string[];
  left_out: string[];
  note?: string;
  detail: [string, string[]][];
};

export type AgentFinding = {
  kind: string;
  severity: 'info' | 'warn' | 'critical';
  title: string;
  body: string;
  ref: string;
};

export type SkepticTarget = { strategy: string; report: string; at: string };

export type ActivityResponse = {
  ok: boolean;
  running: number;
  agents: AgentActivity[];
  feed: (AgentStep & { agent: string; title: string })[];
};

export const agentsApi = {
  list: () => get<AgentsResponse>('/api/agents'),
  activity: (steps = 40) => get<ActivityResponse>(`/api/agents/activity?steps=${steps}`),
  inbox: () => get<{ ok: boolean; items: AgentItem[] }>('/api/agents/inbox'),
  skepticTargets: () => get<{ ok: boolean; targets: SkepticTarget[] }>('/api/agents/skeptic/targets'),
  decide: (id: string, decision: 'approved' | 'dismissed', note = '') =>
    post<{ ok: boolean; error?: string }>(`/api/agents/inbox/${encodeURIComponent(id)}`, { decision, note }),
  setting: (name: string, change: { enabled?: boolean; daily_requests?: number }) =>
    post<{ ok: boolean; error?: string }>(`/api/agents/${encodeURIComponent(name)}/settings`, change),
  brief: (name: string, text: string) =>
    post<{ ok: boolean; error?: string }>(`/api/agents/${encodeURIComponent(name)}/brief`, { text }),
  run: (name: string, args: Record<string, string> = {}) =>
    post<{ ok: boolean; error?: string }>(`/api/agents/${encodeURIComponent(name)}/run`, { args }),
  outputs: (name: string, limit = 5) =>
    get<{ ok: boolean; running: boolean; outputs: AgentOutput[] }>(
      `/api/agents/${encodeURIComponent(name)}/outputs?limit=${limit}`,
    ),
  log: (limit = 60) =>
    get<{
      ok: boolean;
      verified: boolean;
      problem: string;
      entries: { seq: number; at: string; kind: string; agent: string; detail: Record<string, unknown> }[];
    }>(`/api/agents/log?limit=${limit}`),
  ask: (question: string, history: { role: string; content: string }[] = []) =>
    post<{ ok: boolean; answer?: string; error?: string; model?: string; requests?: number; notes?: string[] }>(
      '/api/agents/knowledge/ask',
      { question, history },
    ),
  marketBrief: () =>
    get<{ ok: boolean; text?: string; brief?: MarketBrief | null; mode?: string; at?: string; error?: string }>(
      '/api/agents/market_brief/latest',
    ),
  quality: () =>
    get<{
      ok: boolean;
      grades: DatasetGrade[];
      held: { dataset: string; path: string; reason: string; at: string; by: string }[];
    }>('/api/quality'),
  tickets: () => get<{ ok: boolean; tickets: DeskTicket[]; error?: string }>('/api/desk/tickets'),
  decideTicket: (id: string, decision: 'approved' | 'rejected', note = '') =>
    post<{ ok: boolean; error?: string }>(`/api/desk/tickets/${encodeURIComponent(id)}`, { decision, note }),
};
