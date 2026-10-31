'use client';

/**
 * The research library.
 *
 * A paper is the claim; a linked strategy is one reading of it. Each paper
 * shows its summary, trade idea, implementation logic and red flags, what the
 * source itself reported, and every strategy that tests it with that
 * strategy's latest result. Backtesting goes through the same Backtest dialog
 * and engine as the Strategies page, so a number here is the number there.
 *
 * Papers are files in `research/papers/`, written by the API, so a paper added
 * here is a diff to review and commit like any other research.
 */

import { Info } from '@/components/terminal/ui';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

import { api, assistantStatus, tweezerJob } from '@/lib/api';
import type { AssistantStatus, Paper, PaperView, ResearchLinkView, TweezerResult } from '@/lib/api';
import './builder.css';
import './research.css';

const STATUS_LABEL: Record<Paper['status'], string> = {
  idea: 'Idea',
  specified: 'Rules written',
  backtested: 'Backtested',
  rejected: 'Rejected',
  adopted: 'Adopted',
};

export const BUILDER_PAPER_KEY = 'eulerlab.builder.forPaper';
const AI_MODEL_KEY = 'eulerlab.research.model';

function useResearchModel() {
  const [selection, setSelection] = useState('');
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const choose = (value: string) => {
    setSelection(value);
    try { window.localStorage.setItem(AI_MODEL_KEY, value); } catch { /* this visit only */ }
  };
  useEffect(() => {
    try {
      setSelection(window.localStorage.getItem(AI_MODEL_KEY) ?? window.localStorage.getItem('eulerlab.assistant.model') ?? '');
    } catch { /* use configured default */ }
  }, []);
  const [provider, model] = selection.includes('::') ? selection.split('::', 2) : [selection, ''];
  useEffect(() => {
    let current = true;
    assistantStatus(provider, model).then((next) => current && setStatus(next)).catch(() => current && setStatus(null));
    return () => { current = false; };
  }, [provider, model]);
  // The list is `offered` in config/llm.yaml. A pick kept from when it held
  // other models (an OpenRouter model, Ollama) falls back to the default.
  useEffect(() => {
    if (selection && status && !status.choices.some((choice) => choice.name === selection)) choose('');
  }, [selection, status]);
  return { selection, provider, model, status, choose };
}

function ModelPicker({ selection, status, choose }: ReturnType<typeof useResearchModel>) {
  if (!status || status.choices.length === 0) return <span className="tfine">Checking AI models…</span>;
  return (
    <label className="rl-model">
      AI model
      <select value={selection} onChange={(event) => choose(event.target.value)}>
        <option value="">Default · {status.choices.find((choice) => choice.is_default)?.model ?? 'configured assistant'}</option>
        {status.choices.map((choice) => (
          <option key={choice.name} value={choice.name} disabled={!choice.ready} title={choice.reason}>
            {choice.name} · {choice.model}{choice.ready ? (choice.free ? '' : ' · paid') : ` — ${choice.blocked}`}
          </option>
        ))}
      </select>
    </label>
  );
}

type Section = 'overview' | 'rules' | 'flags' | 'strategies';
type StatusFilter = '' | Paper['status'];

/** Below this width the two columns stack and the page scrolls as usual. */
const TWO_COLUMNS = '(min-width: 901px)';

function blankPaper(): Partial<Paper> {
  return {
    title: '',
    authors: '',
    year: new Date().getFullYear(),
    kind: 'paper',
    source_url: '',
    summary: '',
    trade_idea: '',
    implementation: '',
    red_flags: [],
    reported_results: '',
    hypothesis: '',
    markets: [],
    status: 'idea',
    strategies: [],
  };
}

const num = (value: number | null | undefined, digits = 2, suffix = '') =>
  value === null || value === undefined ? '—' : `${value.toFixed(digits)}${suffix}`;

function Measured({ link }: { link: ResearchLinkView }) {
  const runs = link.measured ?? [];
  if (runs.length === 0) return <span className="tfine">—<Info>Not measured yet. Run it, or `make tweezer-report`.</Info></span>;
  return (
    <table className="ttable rl-mini">
      <thead>
        <tr>
          <th>Held up to</th>
          <th />
          <th>Trades</th>
          <th>Win rate</th>
          <th>Profit factor</th>
          <th>Per trade</th>
          <th>Sum</th>
        </tr>
      </thead>
      <tbody>
        {runs.flatMap((m) =>
          (['gross', 'net'] as const).map((k) => (
            <tr key={`${m.hold_sessions}-${k}`}>
              <td>{k === 'gross' ? (m.hold_sessions === 1 ? 'the close' : `${m.hold_sessions} days`) : ''}</td>
              <td>{k === 'gross' ? 'before costs' : 'after costs'}</td>
              <td>{m[k].trades}</td>
              <td>{num(m[k].win_rate, 1, '%')}</td>
              <td>{num(m[k].profit_factor)}</td>
              <td>{num(m[k].expectancy_pct, 3, '%')}</td>
              <td className={m[k].total_pct >= 0 ? 'pos' : 'neg'}>{num(m[k].total_pct, 1, '%')}</td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}

function TweezerRun({ link }: { link: ResearchLinkView }) {
  const [state, setState] = useState<{ status: string; result?: TweezerResult; error?: string }>({ status: 'idle' });
  const [start, setStart] = useState('2025-06-01');
  const [end, setEnd] = useState('2026-06-30');
  const run = async () => {
    setState({ status: 'Starting…' });
    const started = await api.tweezer({ symbols: [], universe: 'nifty50', timeframe: link.timeframe || 15, start, end });
    if (!started.ok || !started.job) {
      setState({ status: 'failed', error: started.error ?? 'did not start' });
      return;
    }
    for (;;) {
      await new Promise((r) => window.setTimeout(r, 1500));
      const job = await tweezerJob(started.job);
      if (job.status === 'done') return setState({ status: 'done', result: job.result });
      if (job.status === 'failed') return setState({ status: 'failed', error: job.error });
      setState({ status: job.message || 'Scanning…' });
    }
  };
  return (
    <div className="rl-run">
      <span className="tfine">Nifty 50 (most-traded 50) from</span>
      <input type="date" value={start} onChange={(e) => setStart(e.target.value)} aria-label="From" />
      <span className="tfine">to</span>
      <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} aria-label="To" />
      <button type="button" className="tbtn sm go" disabled={state.status !== 'idle' && state.status !== 'done' && state.status !== 'failed'} onClick={run}>
        Scan
      </button>
      {state.status !== 'idle' && state.status !== 'done' && state.status !== 'failed' && <span className="tfine">{state.status}</span>}
      {state.status === 'failed' && <span className="neg">{state.error}</span>}
      {state.status === 'done' && state.result && (
        <span className="tfine">
          {state.result.setups} setups, {state.result.filled} triggered, {state.result.wins} winners, net{' '}
          <b className={state.result.net_pnl >= 0 ? 'pos' : 'neg'}>₹{Math.round(state.result.net_pnl).toLocaleString('en-IN')}</b> on ₹10 lakh at 1%
          risk per trade, after costs.
        </span>
      )}
    </div>
  );
}

function PaperForm({ initial, onSaved, onCancel }: { initial: Partial<Paper>; onSaved: (view: PaperView) => void; onCancel: () => void }) {
  const ai = useResearchModel();
  const [draft, setDraft] = useState<Partial<Paper>>(initial);
  const [flags, setFlags] = useState((initial.red_flags ?? []).join('\n'));
  const [errors, setErrors] = useState<string[]>([]);
  const [sourceText, setSourceText] = useState('');
  const [drafting, setDrafting] = useState(false);
  const [draftNote, setDraftNote] = useState('');
  const set = <K extends keyof Paper>(key: K, value: Paper[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const generate = async () => {
    setDrafting(true);
    setErrors([]);
    setDraftNote('Generating a reviewable draft…');
    try {
      const response = await api.draftPaper({
        title: draft.title ?? '',
        authors: draft.authors ?? '',
        year: draft.year ?? null,
        source_url: draft.source_url ?? '',
        source_text: sourceText,
        provider: ai.provider,
        model: ai.model,
      });
      if (!response.ok) {
        setErrors([response.error]);
        setDraftNote('');
        return;
      }
      setDraft((current) => ({ ...current, ...response.draft }));
      setFlags(response.draft.red_flags.join('\n'));
      setDraftNote(`Draft from ${response.provider} · ${response.model}. Check it against the source before saving.`);
    } catch (e) {
      setErrors([String(e)]);
      setDraftNote('');
    } finally {
      setDrafting(false);
    }
  };
  const save = async () => {
    const incomplete = !draft.summary?.trim() || !draft.trade_idea?.trim() || !draft.implementation?.trim();
    if (incomplete && sourceText.trim()) {
      await generate();
      return;
    }
    if (incomplete) {
      setErrors(['Add the summary fields yourself or paste paper text and use Generate summary.']);
      return;
    }
    const response = await api.savePaper({
      ...draft,
      red_flags: flags
        .split('\n')
        .map((x) => x.trim())
        .filter(Boolean),
    });
    if (response.ok) onSaved(response);
    else setErrors(response.errors);
  };
  return (
    <div className="tpanel rl-form">
      <h3>{initial.id ? 'Edit paper' : 'Add a paper'}</h3>
      <div className="sip-form">
        <label className="wide">
          Title
          <input value={draft.title ?? ''} onChange={(e) => set('title', e.target.value)} />
        </label>
        <label className="wide">
          Authors
          <input value={draft.authors ?? ''} onChange={(e) => set('authors', e.target.value)} placeholder="Surname, A., Surname, B." />
        </label>
        <label>
          Year
          <input type="number" value={draft.year ?? ''} onChange={(e) => set('year', e.target.value ? Number(e.target.value) : null)} />
        </label>
        <label>
          Kind
          <select value={draft.kind} onChange={(e) => set('kind', e.target.value as Paper['kind'])}>
            <option value="paper">Paper</option>
            <option value="report">Report</option>
            <option value="book">Book</option>
            <option value="note">Note</option>
          </select>
        </label>
        <label className="wide">
          Link
          <input value={draft.source_url ?? ''} onChange={(e) => set('source_url', e.target.value)} placeholder="https://arxiv.org/abs/…" />
        </label>
        <label>
          Hypothesis
          <input value={draft.hypothesis ?? ''} onChange={(e) => set('hypothesis', e.target.value)} placeholder="H-0005" />
        </label>
      </div>
      {!initial.id && (
        <label className="rl-text">
          Paper text or abstract for the AI draft (sent to the selected, privacy-checked model; not saved)
          <textarea rows={7} value={sourceText} onChange={(e) => setSourceText(e.target.value)} placeholder="Paste the abstract or relevant paper text. A link alone is not fetched." />
        </label>
      )}
      {!initial.id && <ModelPicker {...ai} />}
      {!initial.id && ai.status && !ai.status.ready && <p className="tnote bad">{ai.status.reason}</p>}
      {(
        [
          ['summary', 'Summary', 'What the paper did and found, in a few sentences.'],
          ['trade_idea', 'Trade idea', 'Why it should make money: the behaviour it exploits.'],
          ['implementation', 'Implementation logic', 'The exact rules: universe, entry, exit, sizing, stops. Enough to code it.'],
          ['reported_results', 'What the source reports', 'Their numbers, copied. Never ours.'],
        ] as const
      ).map(([key, label, hint]) => (
        <label key={key} className="rl-text">
          {label}
          <textarea rows={key === 'implementation' ? 8 : 3} value={(draft[key] as string) ?? ''} placeholder={hint} onChange={(e) => set(key, e.target.value)} />
        </label>
      ))}
      <label className="rl-text">
        Red flags, one per line
        <textarea rows={3} value={flags} placeholder="What could make a good backtest of this misleading?" onChange={(e) => setFlags(e.target.value)} />
      </label>
      {errors.length > 0 && (
        <div className="tnote bad">
          <span className="mk">▲</span>
          <div>
            {errors.map((e) => (
              <div key={e}>{e}</div>
            ))}
          </div>
        </div>
      )}
      {draftNote && <p className="tfine">{draftNote}</p>}
      <div className="sb-actions">
        <button type="button" className="tbtn" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="tbtn go" disabled={drafting} onClick={save}>
          {drafting ? 'Generating…' : 'Save paper'}
        </button>
        {!initial.id && <button type="button" className="tbtn" disabled={drafting || sourceText.trim().length < 80} onClick={generate}>Generate summary</button>}
      </div>
    </div>
  );
}

export function ResearchLibrary({
  selected,
  onSelect,
  onBacktest,
  onReport,
  onBuild,
}: {
  selected: string;
  onSelect: (paperId: string) => void;
  onBacktest: (strategyIds: string[]) => void;
  onReport: (strategyId: string) => void;
  onBuild: () => void;
}) {
  const ai = useResearchModel();
  const [papers, setPapers] = useState<PaperView[] | null>(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState<Partial<Paper> | null>(null);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<StatusFilter>('');
  const [section, setSection] = useState<Section>('overview');
  const [codeRun, setCodeRun] = useState<{ status: 'idle' | 'working' | 'done' | 'failed'; source?: string; provider?: string; model?: string; result?: import('@/lib/api').Result; error?: string }>({ status: 'idle' });
  const frame = useRef<HTMLDivElement>(null);
  const reading = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    api
      .papers()
      .then((r) => setPapers(r.papers))
      .catch((e) => setError(String(e)));
  }, []);
  useEffect(load, [load]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (papers ?? []).filter(
      (v) =>
        (!status || v.paper.status === status) &&
        (!q || [v.paper.title, v.paper.authors, v.paper.summary].some((t) => t.toLowerCase().includes(q)))
    );
  }, [papers, query, status]);
  const current = (papers ?? []).find((v) => v.paper.id === selected) ?? shown[0] ?? null;
  const currentId = current?.paper.id ?? '';

  const counts = useMemo(() => {
    const out: Partial<Record<Paper['status'], number>> = {};
    for (const v of papers ?? []) out[v.paper.status] = (out[v.paper.status] ?? 0) + 1;
    return out;
  }, [papers]);

  // The library is exactly as tall as the window below its own top edge, so
  // the page never scrolls: only the list of papers does, and the paper being
  // read stays where it is.
  const ready = papers !== null && editing === null;
  useLayoutEffect(() => {
    const el = frame.current;
    if (!el || !ready) return;
    const wide = window.matchMedia(TWO_COLUMNS);
    const fit = () => {
      if (!wide.matches) {
        el.style.height = '';
        return;
      }
      const top = el.getBoundingClientRect().top + window.scrollY;
      el.style.height = `${Math.max(420, window.innerHeight - top - 16)}px`;
    };
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, [ready]);

  // A newly chosen paper starts at its top, and its row is brought into view
  // when it was chosen from somewhere other than the list.
  useEffect(() => {
    if (!currentId) return;
    reading.current?.scrollTo({ top: 0 });
    frame.current?.querySelector('.rl-item[aria-pressed="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [currentId]);

  useEffect(() => setCodeRun({ status: 'idle' }), [currentId]);

  const codeAndBacktest = async () => {
    if (!p) return;
    setCodeRun({ status: 'working' });
    try {
      const drafted = await api.paperStrategy(p.id, ai.provider, ai.model);
      if (!drafted.ok || !drafted.source) throw new Error(drafted.error ?? 'The model returned no strategy code.');
      setCodeRun({ status: 'working', source: drafted.source, provider: drafted.provider, model: drafted.model });
      const started = await api.backtest({ mode: 'code', source: drafted.source, feature: '', top_n: 30, rebalance: 21, min_turnover: 0, days: 800, tier: 'B', starting_cash: 1_000_000 });
      if (!started.ok || !started.job) throw new Error(started.error ?? 'The backtest did not start.');
      for (;;) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const job = await api.job(started.job);
        if (job.status === 'done') {
          setCodeRun({ status: 'done', source: drafted.source, provider: drafted.provider, model: drafted.model, result: job.result });
          return;
        }
        if (job.status === 'failed') throw new Error(job.error || job.message || 'Backtest failed.');
      }
    } catch (e) {
      setCodeRun((state) => ({ ...state, status: 'failed', error: String(e) }));
    }
  };

  if (error) {
    return (
      <div className="tnote bad">
        <span className="mk">▲</span>
        <div>The library could not load: {error}</div>
      </div>
    );
  }
  if (!papers) return <div className="tempty">Loading the library…</div>;

  if (editing) {
    return (
      <PaperForm
        initial={editing}
        onCancel={() => setEditing(null)}
        onSaved={(view) => {
          setEditing(null);
          load();
          onSelect(view.paper.id);
        }}
      />
    );
  }

  const p = current?.paper;
  const runnable = (current?.links ?? []).filter((l) => l.kind !== 'tweezer' && l.runnable).map((l) => l.id);

  return (
    <div className="rl" ref={frame}>
      <aside className="rl-list">
        <div className="rl-list-head">
          <div className="rl-list-top">
            <input className="tsearch" placeholder="Search papers…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search papers" />
            <button type="button" className="tbtn go sm" onClick={() => setEditing(blankPaper())}>
              + Add
            </button>
          </div>
          <div className="rl-filter" role="group" aria-label="Status">
            <button type="button" className="tchip sm" aria-pressed={status === ''} onClick={() => setStatus('')}>
              All {papers.length}
            </button>
            {(Object.keys(STATUS_LABEL) as Paper['status'][])
              .filter((key) => counts[key])
              .map((key) => (
                <button key={key} type="button" className="tchip sm" aria-pressed={status === key} onClick={() => setStatus(status === key ? '' : key)}>
                  {STATUS_LABEL[key]} {counts[key]}
                </button>
              ))}
          </div>
        </div>
        <div className="rl-items">
        {shown.map((v) => (
          <button
            key={v.paper.id}
            type="button"
            className="rl-item"
            aria-pressed={current?.paper.id === v.paper.id}
            onClick={() => onSelect(v.paper.id)}
          >
            <b>{v.paper.title}</b>
            <span>
              {[v.paper.authors, v.paper.year].filter(Boolean).join(' · ')}
            </span>
            <span className={`rl-status s-${v.paper.status}`}>
              {STATUS_LABEL[v.paper.status]}
              {v.links.length > 0 && ` · ${v.links.length} ${v.links.length === 1 ? 'strategy' : 'strategies'}`}
            </span>
          </button>
        ))}
        {shown.length === 0 && <div className="tfine">No paper matches.</div>}
        </div>
      </aside>

      {current && p && (
        <article className="rl-paper">
          <header className="rl-head">
            <div className="rl-title">
              <div>
                <h2>{p.title}</h2>
                <p className="tfine">
                  {p.authors}
                  {p.year ? ` (${p.year})` : ''} · {p.kind}
                  {p.hypothesis && ` · ${p.hypothesis}`}
                  {p.source_url && (
                    <>
                      {' · '}
                      <a href={p.source_url} target="_blank" rel="noreferrer">
                        source
                      </a>
                    </>
                  )}
                </p>
              </div>
              <div className="rl-actions">
                <ModelPicker {...ai} />
                <button type="button" className="tbtn sm" onClick={() => setEditing(p)}>
                  Edit
                </button>
                <button
                  type="button"
                  className="tbtn sm"
                  title="Open the Strategy Builder; what you save there is linked to this paper"
                  onClick={() => {
                    try {
                      window.sessionStorage.setItem(BUILDER_PAPER_KEY, p.id);
                    } catch {
                      /* private mode: the link is made by hand instead */
                    }
                    onBuild();
                  }}
                >
                  Build its rules
                </button>
                <button type="button" className="tbtn sm" disabled={codeRun.status === 'working' || !ai.status?.ready} onClick={codeAndBacktest}>
                  {codeRun.status === 'working' ? 'Coding / backtesting…' : 'AI code & backtest'}
                </button>
                {runnable.length > 0 && (
                  <button type="button" className="tbtn sm go" onClick={() => onBacktest(runnable)}>
                    Backtest {runnable.length > 1 ? `all ${runnable.length}` : ''}
                  </button>
                )}
              </div>
            </div>
            <div className="rl-meta">
              <span className={`rl-status s-${p.status}`}>{STATUS_LABEL[p.status]}</span>
              {p.markets.map((m) => (
                <span key={m} className="rl-market">
                  {m}
                </span>
              ))}
            </div>
            <div className="rl-tabs" role="tablist" aria-label="Paper sections">
              {(
                [
                  ['overview', 'Overview'],
                  ['rules', 'Rules'],
                  ['flags', `Red flags ${p.red_flags.length || ''}`],
                  ['strategies', `Strategies ${current.links.length || ''}`],
                ] as const
              ).map(([key, label]) => (
                <button key={key} type="button" role="tab" className="rl-tab" aria-selected={section === key} onClick={() => setSection(key)}>
                  {label}
                </button>
              ))}
            </div>
          </header>

          <div className="rl-body" ref={reading} role="tabpanel">
          {section === 'overview' &&
            (
              [
                ['Summary', p.summary],
                ['Trade idea', p.trade_idea],
                ['What the source reports', p.reported_results],
              ] as const
            ).map(([title, text]) =>
              text ? (
                <section key={title} className="rl-section">
                  <h3>{title}</h3>
                  <div className="rl-prose">{text}</div>
                </section>
              ) : null
            )}

          {codeRun.status !== 'idle' && (
            <section className="rl-section rl-ai-result">
              <h3>AI strategy draft · review before relying on results</h3>
              {codeRun.provider && <p className="tfine">{codeRun.provider} · {codeRun.model} · validated by the existing strategy sandbox</p>}
              {codeRun.error && <p className="neg">{codeRun.error}</p>}
              {codeRun.result && (
                <div className="rl-result">
                  <span>Sharpe <b>{codeRun.result.sharpe.toFixed(2)}</b></span>
                  <span>Return <b className={codeRun.result.total_return >= 0 ? 'pos' : 'neg'}>{(codeRun.result.total_return * 100).toFixed(1)}%</b></span>
                  <span>Max drawdown <b>{(codeRun.result.max_drawdown * 100).toFixed(1)}%</b></span>
                  <span>{codeRun.result.fills} fills</span>
                  <span className="tfine">{codeRun.result.period[0]} to {codeRun.result.period[1]} · Tier {codeRun.result.tier} · ₹10 lakh start</span>
                </div>
              )}
              {codeRun.source && <details><summary>Generated strategy source</summary><pre>{codeRun.source}</pre></details>}
              {codeRun.result && <p className="tfine"><span className="ui-chip warn">Single backtest</span><Info>This is a single backtest, not evidence of robustness or a forecast. The draft is not saved or linked as a maintained strategy.</Info></p>}
            </section>
          )}

          {section === 'rules' && (
            <section className="rl-section">
              <h3>Implementation logic</h3>
              <div className="rl-prose">{p.implementation}</div>
            </section>
          )}

          {section === 'flags' && (
            <section className="rl-section">
              <h3>Red flags</h3>
              {p.red_flags.length === 0 && <p className="tfine">None recorded.</p>}
              <ul className="rl-flags">
                {p.red_flags.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </section>
          )}

          {section === 'strategies' && (
          <section className="rl-section">
            <h3>Strategies that test it</h3>
            {current.links.length === 0 && (
              <p className="tfine">—<Info>None yet. &quot;Build its rules&quot; opens the Strategy Builder; what you save there is linked here.</Info></p>
            )}
            <div className="rl-links">
              {current.links.map((link) => (
                <div key={`${link.kind}:${link.id}:${link.timeframe}`} className="rl-link">
                  <div className="rl-link-head">
                    <b>{link.title}</b>
                    <span className="tfine">
                      {link.kind === 'builder' ? 'Builder rules' : link.kind === 'registered' ? 'Coded strategy' : 'Intraday scanner'} · {link.id}
                      {link.note && ` · ${link.note}`}
                    </span>
                  </div>
                  {!link.exists && <span className="neg">Missing: this strategy no longer exists.</span>}
                  {link.kind === 'tweezer' ? (
                    <>
                      <Measured link={link} />
                      <TweezerRun link={link} />
                    </>
                  ) : (
                    <div className="rl-result">
                      {link.result && link.result.sharpe !== null ? (
                        <>
                          <span>
                            Sharpe <b>{link.result.sharpe.toFixed(2)}</b>
                          </span>
                          {link.result.total_return !== undefined && (
                            <span>
                              Return <b className={link.result.total_return >= 0 ? 'pos' : 'neg'}>{(link.result.total_return * 100).toFixed(1)}%</b>
                            </span>
                          )}
                          <span className="tfine">
                            latest of {link.result.runs} run{link.result.runs === 1 ? '' : 's'}
                          </span>
                          <button type="button" className="tbtn sm" onClick={() => onReport(link.id)}>
                            Report
                          </button>
                        </>
                      ) : (
                        <span className="tfine">Not backtested yet.</span>
                      )}
                      {link.runnable && (
                        <button type="button" className="tbtn sm" onClick={() => onBacktest([link.id])}>
                          Backtest
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
          )}
          </div>
        </article>
      )}
      {!current && <div className="tempty">No papers yet. Add one.</div>}
    </div>
  );
}
