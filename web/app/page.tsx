'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { EquityChart } from '@/components/EquityChart';
import { TweezerPanel } from '@/components/TweezerPanel';
import { api, pct, rupees } from '@/lib/api';
import type { Health, Job, Library, Provider, Result, StrategyInput } from '@/lib/api';

type Tab = 'describe' | 'compose' | 'code';

export default function Page() {
  const [tab, setTab] = useState<Tab>('compose');
  // Daily and intraday are separate surfaces, not another tab in the same card.
  // A Tweezer scan has no Sharpe and no equity curve of target weights; sitting
  // it beside them would invite a comparison that is not meaningful.
  const [surface, setSurface] = useState<'daily' | 'intraday'>('daily');
  const [library, setLibrary] = useState<Library | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);

  const [input, setInput] = useState<StrategyInput>({
    mode: 'composed',
    source: '',
    feature: 'momentum_12_1',
    top_n: 30,
    rebalance: 21,
    min_turnover: 0,
  });
  const [days, setDays] = useState(800);
  const [tier, setTier] = useState<'A' | 'B'>('B');

  const [description, setDescription] = useState('');
  const [provider, setProvider] = useState<string | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [draftNote, setDraftNote] = useState<string>('');

  const [validation, setValidation] = useState<{ ok: boolean; message: string } | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [running, setRunning] = useState(false);
  const [problem, setProblem] = useState('');
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    api.library().then((l) => {
      setLibrary(l);
      setInput((prev) => (prev.source ? prev : { ...prev, source: l.example_code }));
    }).catch(() => setProblem('Cannot reach the API. Is `make api` running on :8000?'));
    api.health().then(setHealth).catch(() => undefined);
    api.providers().then((p) => {
      setProviders(p.providers);
      const preferred = p.providers.find((x) => x.is_default) ?? p.providers.find((x) => x.ready);
      if (preferred) setProvider(preferred.name);
    }).catch(() => undefined);
  }, []);

  // Validate as the operator types, but only in code mode — a composed spec is
  // chosen from a dropdown and cannot be invalid.
  useEffect(() => {
    if (tab !== 'code') { setValidation(null); return; }
    const handle = setTimeout(() => {
      api.validate({ ...input, mode: 'code' })
        .then((r) => setValidation({ ok: r.ok, message: r.ok ? 'Compiles. Nothing here can reach past its decision date.' : (r.error ?? '') }))
        .catch(() => undefined);
    }, 500);
    return () => clearTimeout(handle);
  }, [input, tab]);

  useEffect(() => () => { if (poll.current) clearInterval(poll.current); }, []);

  const run = useCallback(async () => {
    setProblem(''); setJob(null); setRunning(true);
    const mode = tab === 'code' ? 'code' : 'composed';
    const started = await api.backtest({ ...input, mode, days, tier, starting_cash: 1_000_000 });
    if (!started.ok || !started.job) {
      setProblem(started.error ?? 'could not start'); setRunning(false); return;
    }
    poll.current = setInterval(async () => {
      const state = await api.job(started.job!);
      setJob(state);
      if (state.status === 'done' || state.status === 'failed') {
        if (poll.current) clearInterval(poll.current);
        setRunning(false);
        api.health().then(setHealth).catch(() => undefined);
      }
    }, 1200);
  }, [input, tab, days, tier]);

  const askModel = useCallback(async () => {
    setDrafting(true); setDraftNote(''); setProblem('');
    const mode = tab === 'code' ? 'code' : 'composed';
    const drafted = await api.draft(description, mode, provider);
    setDrafting(false);
    if (!drafted.ok) { setDraftNote(drafted.error ?? 'the model could not be reached'); return; }
    if (drafted.mode === 'code' && drafted.source) {
      setInput((p) => ({ ...p, source: drafted.source! }));
      setTab('code');
    } else if (drafted.spec) {
      const s = drafted.spec as Record<string, number | string>;
      setInput((p) => ({
        ...p,
        feature: String(s.feature ?? p.feature),
        top_n: Number(s.top_n ?? p.top_n),
        rebalance: Number(s.rebalance ?? p.rebalance),
        min_turnover: Number(s.min_turnover ?? 0),
      }));
      setTab('compose');
    }
    setDraftNote(
      `${drafted.provider}/${drafted.model} drafted this. ${drafted.explanation ?? ''} ` +
      `Read it before running it — the model chose, it did not verify.` +
      (drafted.warnings?.length ? ` (${drafted.warnings.join('; ')})` : '')
    );
  }, [description, tab, provider]);

  const result: Result | null = job?.status === 'done' ? job.result : null;

  return (
    <div className="shell">
      <header className="top">
        <h1>EulerLab — strategy workbench</h1>
        <p>
          Write a strategy as a description, a composed spec, or code. It runs against
          real NSE history through the same engine <code className="inline">make backtest</code> uses —
          same cost model, same lookahead firewall, same order lifecycle.
        </p>
        {health && (
          <div className="statline">
            <span>trials logged <b>{health.trials_logged}</b></span>
            <span
              title={health.noise_bar_note}
              data-tip={health.noise_bar_note}
            >
              noise bar <b>Sharpe {health.noise_bar.toFixed(2)}</b>
              {!health.noise_bar_sigma_measured && <em className="assumed"> assumed</em>}
            </span>
            <span>panel <b>{health.panel_loaded ? 'cached' : 'not yet loaded'}</b></span>
            <span className="muted">running a backtest here spends no trial</span>
          </div>
        )}
      </header>

      <div className="surface-switch" role="tablist" aria-label="Which engine">
        <button
          role="tab"
          aria-selected={surface === 'daily'}
          onClick={() => setSurface('daily')}
        >
          Daily cross-section
          <span>rank the market, hold the top N</span>
        </button>
        <button
          role="tab"
          aria-selected={surface === 'intraday'}
          onClick={() => setSurface('intraday')}
        >
          Intraday patterns
          <span>Tweezer Bottom on minute bars</span>
        </button>
      </div>

      {problem && <div className="note bad" style={{ marginBottom: 16 }}>{problem}</div>}

      {surface === 'intraday' && <TweezerPanel />}

      {surface === 'daily' && (
      <div className="grid">
        <div>
          <div className="card">
            <h2>Strategy</h2>
            <p className="sub">Three ways in. They all end up as the same <code className="inline">Strategy</code> object.</p>

            <div className="tabs" role="tablist">
              <button role="tab" aria-selected={tab === 'describe'} onClick={() => setTab('describe')}>Describe</button>
              <button role="tab" aria-selected={tab === 'compose'} onClick={() => setTab('compose')}>Compose</button>
              <button role="tab" aria-selected={tab === 'code'} onClick={() => setTab('code')}>Code</button>
            </div>

            {tab === 'describe' && (
              <>
                <label className="field">
                  <span>Describe the idea in plain English</span>
                  <textarea
                    style={{ minHeight: 130 }}
                    value={description}
                    placeholder="Hold the thirty calmest large caps, rebalanced monthly, avoiding anything illiquid."
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </label>
                <label className="field">
                  <span>Model</span>
                  <select value={provider ?? ''} onChange={(e) => setProvider(e.target.value)}>
                    {providers.map((p) => (
                      <option key={p.name} value={p.name} disabled={!p.ready}>
                        {p.name} · {p.model} {p.free ? '· free' : '· paid'} {p.ready ? '' : '· needs a key'}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="actions">
                  <button className="ghost" onClick={askModel} disabled={drafting || description.trim().length < 4}>
                    {drafting && <span className="spinner" />}
                    {drafting ? 'Drafting…' : 'Draft a strategy'}
                  </button>
                  <span className="muted">The model drafts. It never runs anything.</span>
                </div>
                {draftNote && <div className="note warn">{draftNote}</div>}
                {providers.every((p) => !p.ready) && (
                  <div className="note warn">
                    No model is reachable. The default is <code className="inline">ollama</code>, which runs locally
                    and needs no key — install it from ollama.com, then <code className="inline">ollama pull qwen2.5-coder:7b</code>.
                    You can skip this tab entirely and use Compose or Code.
                  </div>
                )}
              </>
            )}

            {tab === 'compose' && (
              <>
                <label className="field">
                  <span>Rank the cross-section by</span>
                  <select value={input.feature} onChange={(e) => setInput({ ...input, feature: e.target.value })}>
                    {library?.features.map((f) => (
                      <option key={f.name} value={f.name}>{f.name} — {f.description}</option>
                    ))}
                  </select>
                </label>
                <div className="row">
                  <label className="field">
                    <span>Hold the top N</span>
                    <input type="number" min={5} max={100} value={input.top_n}
                      onChange={(e) => setInput({ ...input, top_n: Number(e.target.value) })} />
                  </label>
                  <label className="field">
                    <span>Rebalance every (trading days)</span>
                    <input type="number" min={5} max={126} value={input.rebalance}
                      onChange={(e) => setInput({ ...input, rebalance: Number(e.target.value) })} />
                  </label>
                </div>
                <label className="field">
                  <span>Minimum median daily turnover (₹, 0 for no filter)</span>
                  <input type="number" min={0} step={1000000} value={input.min_turnover}
                    onChange={(e) => setInput({ ...input, min_turnover: Number(e.target.value) })} />
                </label>
                <p className="muted">
                  Every feature is oriented so higher is better. <code className="inline">low_volatility</code> is
                  negated volatility, so its top N are the calmest names.
                </p>
              </>
            )}

            {tab === 'code' && (
              <>
                <label className="field">
                  <span>
                    One function: <code className="inline">weights(view)</code> → <code className="inline">{'{symbol: weight}'}</code>
                  </span>
                  <textarea
                    spellCheck={false}
                    value={input.source}
                    onChange={(e) => setInput({ ...input, source: e.target.value })}
                  />
                </label>
                <label className="field">
                  <span>Rebalance every (trading days)</span>
                  <input type="number" min={5} max={126} value={input.rebalance}
                    onChange={(e) => setInput({ ...input, rebalance: Number(e.target.value) })} />
                </label>
                {validation && (
                  <div className={`note ${validation.ok ? 'ok' : 'bad'}`}>
                    <pre>{validation.message}</pre>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="card">
            <h2>Run</h2>
            <p className="sub">Tier B is the real engine. Tier A is a screen and says so.</p>
            <div className="row">
              <label className="field">
                <span>History window (trading days)</span>
                <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
                  <option value={250}>250 — about 1 year</option>
                  <option value={500}>500 — about 2 years</option>
                  <option value={800}>800 — about 3 years</option>
                  <option value={1500}>1500 — about 6 years</option>
                  <option value={2800}>2800 — the full panel</option>
                </select>
              </label>
              <label className="field">
                <span>Engine</span>
                <select value={tier} onChange={(e) => setTier(e.target.value as 'A' | 'B')}>
                  <option value="B">Tier B — event-driven, real orders</option>
                  <option value="A">Tier A — vectorised screen only</option>
                </select>
              </label>
            </div>
            <div className="actions">
              <button className="go" onClick={run} disabled={running || (tab === 'code' && validation?.ok === false)}>
                {running && <span className="spinner" />}
                {running ? 'Running…' : 'Run backtest'}
              </button>
              {job && <span className="muted">{job.message} · {job.elapsed}s</span>}
            </div>
            {job?.status === 'failed' && (
              <div className="note bad"><pre>{job.error}</pre></div>
            )}
          </div>

          {library && (
            <div className="card">
              <h2>What code may do</h2>
              <p className="sub">The sandbox, in four rules.</p>
              <ul className="rules">
                {library.sandbox_rules.map((r) => <li key={r}>{r}</li>)}
              </ul>
            </div>
          )}
        </div>

        <div>
          {!result && !running && (
            <div className="card">
              <h2>No result yet</h2>
              <p className="sub">Nothing has been run in this session.</p>
              {library && (
                <table className="libtable">
                  <tbody>
                    {library.features.map((f) => (
                      <tr key={f.name}><td className="n">{f.name}</td><td className="d">{f.description}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {result && (
            <>
              <div className="card">
                <h2>{result.label}</h2>
                <p className="sub">
                  Tier {result.tier} · {result.period[0]} to {result.period[1]} · {result.days.length} days
                  {result.tier === 'A' && ' · a screen, not a backtest'}
                </p>
                <EquityChart days={result.days} equity={result.equity} startingCash={result.starting_cash} />
              </div>

              <div className="card">
                <h2>Numbers</h2>
                <p className="sub">Same cost model as every other figure in this project.</p>
                <div className="metrics">
                  <Metric k="Total return" v={pct(result.total_return)} sign={result.total_return} help="Change in portfolio value over the whole period, after costs." />
                  <Metric k="Annualised" v={pct(result.annualised)} sign={result.annualised} help="The same return expressed as a per-year rate, so periods of different lengths compare." />
                  <Metric k="Sharpe" v={result.sharpe.toFixed(2)} sign={result.sharpe} help="Return per unit of volatility, annualised. Higher is steadier, not necessarily larger." />
                  <Metric k="Max drawdown" v={pct(result.max_drawdown)} sign={-1} help="The worst peak-to-trough fall along the way. What you would have had to sit through." />
                  <Metric k="Final equity" v={rupees(result.final_equity)} />
                  <Metric k="Costs paid" v={rupees(result.costs)} help="Brokerage, STT, stamp duty, GST and exchange fees — the same model used everywhere in this project." />
                  <Metric k="Fills" v={String(result.fills)} />
                  <Metric k="Rejected" v={String(result.rejections)} help="Orders the engine refused because the stock did not trade that day. Real, not assumed away." />
                </div>
              </div>

              <Verdict sharpe={result.sharpe} bar={result.noise_bar} />

              {result.resampled && (
                <div className="card">
                  <h2>If history had gone differently</h2>
                  <p className="sub">
                    The same returns, resampled 400 times. Two different questions, because
                    reordering returns cannot change a Sharpe ratio &mdash; only the path.
                  </p>
                  <div className="metrics">
                    <Metric
                      k="Drawdown, typical reorder"
                      v={pct(result.resampled.drawdown_p50)}
                      sign={-1}
                      help="Shuffling the order of the same daily returns. Half of the reorderings were worse than this."
                    />
                    <Metric
                      k="Drawdown, unlucky reorder"
                      v={pct(result.resampled.drawdown_p05)}
                      sign={-1}
                      help="The 5th percentile. One reordering in twenty was at least this bad."
                    />
                    <Metric
                      k="Sharpe, low end"
                      v={result.resampled.sharpe_p05.toFixed(2)}
                      sign={result.resampled.sharpe_p05}
                      help="Bootstrap 5th percentile. Resampling with replacement, which — unlike shuffling — does move the Sharpe."
                    />
                    <Metric
                      k="Sharpe, high end"
                      v={result.resampled.sharpe_p95.toFixed(2)}
                      sign={result.resampled.sharpe_p95}
                      help="Bootstrap 95th percentile."
                    />
                  </div>
                  {result.resampled.sharpe_could_be_zero && (
                    <div className="note bad" style={{ marginTop: 12 }}>
                      The low end is at or below zero. <strong>This data cannot rule out that
                      there is no edge at all.</strong>
                    </div>
                  )}
                  {result.resampled.drawdown_is_understated && (
                    <div className="note warn" style={{ marginTop: 12 }}>
                      The realised drawdown was shallower than a typical reordering. History was
                      kind about the order losses arrived in; that is luck, not robustness.
                    </div>
                  )}
                  <p className="footnote">
                    Both assume returns are interchangeable. Real losses cluster, and shuffling
                    breaks up exactly the clustering that causes the worst drawdowns &mdash; so
                    treat this as a floor on the risk, not the whole of it.
                  </p>
                </div>
              )}

              <div className="card">
                <h2>What this does not mean</h2>
                <p className="sub">Returned with the result, not written into the page.</p>
                <ul className="caveats">
                  {result.caveats.map((c) => <li key={c}>{c}</li>)}
                </ul>
              </div>
            </>
          )}
        </div>
      </div>
      )}
    </div>
  );
}

function Metric({ k, v, sign, help }: { k: string; v: string; sign?: number; help?: string }) {
  const cls = sign === undefined ? '' : sign > 0 ? ' pos' : sign < 0 ? ' neg' : '';
  return (
    <div className="metric">
      <div className="k">
        {k}
        {help && <span className="help" tabIndex={0} role="note" aria-label={help} data-tip={help}>?</span>}
      </div>
      <div className={`v${cls}`}>{v}</div>
    </div>
  );
}

// The single most useful thing the interface can say. A Sharpe on its own reads
// as good or bad against nothing; against the bar that 19 logged trials have
// already raised, it reads as what it is.
function Verdict({ sharpe, bar }: { sharpe: number; bar: number }) {
  const clears = sharpe >= bar;
  const frac = Math.max(0, Math.min(1, sharpe / Math.max(bar, 0.01)));
  return (
    <div className={`card verdict ${clears ? 'over' : 'under'}`}>
      <h2>{clears ? 'Above the noise bar — and still probably noise' : 'Below the noise bar'}</h2>
      <p className="sub">
        This project has logged enough trials that a strategy must reach Sharpe {bar.toFixed(2)}
        {' '}before beating it means anything. Try enough ideas and the best of them looks good
        by chance alone.
      </p>
      <div className="bar">
        <div className="fill" style={{ width: `${frac * 100}%` }} />
        <div className="bar-mark" style={{ left: '100%' }} />
      </div>
      <div className="bar-legend">
        <span>this strategy <strong>{sharpe.toFixed(2)}</strong></span>
        <span>noise bar <strong>{bar.toFixed(2)}</strong></span>
      </div>
      {clears && (
        <p className="footnote">
          Clearing the bar is necessary, not sufficient. It says the result is not obviously
          explained by how much has been searched &mdash; nothing more.
        </p>
      )}
    </div>
  );
}
