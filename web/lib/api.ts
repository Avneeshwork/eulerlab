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
  providers: () => get<{ ok: boolean; providers: Provider[]; error?: string }>('/api/providers'),
  validate: (input: StrategyInput) =>
    post<{ ok: boolean; label?: string; error?: string }>('/api/validate', input),
  draft: (description: string, mode: 'composed' | 'code', provider: string | null) =>
    post<Draft>('/api/draft', { description, mode, provider }),
  backtest: (input: StrategyInput & { days: number; tier: 'A' | 'B'; starting_cash: number }) =>
    post<{ ok: boolean; job?: string; error?: string }>('/api/backtest', input),
  job: (id: string) => get<Job>(`/api/jobs/${id}`),
};

export const pct = (value: number) =>
  `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;

export const rupees = (value: number) =>
  `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
