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

import { useCallback, useEffect, useMemo, useState } from 'react';

import { api, tweezerJob } from '@/lib/api';
import type { Paper, PaperView, ResearchLinkView, TweezerResult } from '@/lib/api';
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
  if (runs.length === 0) return <span className="tfine">Not measured yet. Run it, or `make tweezer-report`.</span>;
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
  const [draft, setDraft] = useState<Partial<Paper>>(initial);
  const [flags, setFlags] = useState((initial.red_flags ?? []).join('\n'));
  const [errors, setErrors] = useState<string[]>([]);
  const set = <K extends keyof Paper>(key: K, value: Paper[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const save = async () => {
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
      <div className="sb-actions">
        <button type="button" className="tbtn" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="tbtn go" onClick={save}>
          Save paper
        </button>
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
  const [papers, setPapers] = useState<PaperView[] | null>(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState<Partial<Paper> | null>(null);
  const [query, setQuery] = useState('');

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
      (v) => !q || [v.paper.title, v.paper.authors, v.paper.summary].some((t) => t.toLowerCase().includes(q))
    );
  }, [papers, query]);
  const current = (papers ?? []).find((v) => v.paper.id === selected) ?? shown[0] ?? null;

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
    <div className="rl">
      <aside className="rl-list">
        <div className="rl-list-head">
          <input className="tsearch" placeholder="Search papers…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <button type="button" className="tbtn go sm" onClick={() => setEditing(blankPaper())}>
            + Add paper
          </button>
        </div>
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
              {v.paper.authors}
              {v.paper.year ? ` · ${v.paper.year}` : ''}
            </span>
            <span className={`rl-status s-${v.paper.status}`}>
              {STATUS_LABEL[v.paper.status]} · {v.links.length} {v.links.length === 1 ? 'strategy' : 'strategies'}
            </span>
          </button>
        ))}
        {shown.length === 0 && <div className="tfine">No paper matches.</div>}
      </aside>

      {current && p && (
        <article className="rl-paper">
          <div className="tpanel">
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
                {runnable.length > 0 && (
                  <button type="button" className="tbtn sm go" onClick={() => onBacktest(runnable)}>
                    Backtest {runnable.length > 1 ? `all ${runnable.length}` : ''}
                  </button>
                )}
              </div>
            </div>
            <span className={`rl-status s-${p.status}`}>{STATUS_LABEL[p.status]}</span>
          </div>

          {(
            [
              ['Summary', p.summary],
              ['Trade idea', p.trade_idea],
              ['Implementation logic', p.implementation],
              ['What the source reports', p.reported_results],
            ] as const
          ).map(([title, text]) =>
            text ? (
              <section key={title} className="tpanel">
                <h3>{title}</h3>
                <div className="rl-prose">{text}</div>
              </section>
            ) : null
          )}

          {p.red_flags.length > 0 && (
            <section className="tpanel">
              <h3>Red flags</h3>
              <ul className="rl-flags">
                {p.red_flags.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </section>
          )}

          <section className="tpanel">
            <h3>Strategies that test it</h3>
            {current.links.length === 0 && (
              <p className="tfine">None yet. "Build its rules" opens the Strategy Builder; what you save there is linked here.</p>
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
        </article>
      )}
      {!current && <div className="tempty">No papers yet. Add one.</div>}
    </div>
  );
}
