/**
 * The AI page: the agent control room (ADR-085), opening on what each agent
 * is doing right now (ADR-091).
 *
 *   Live            one card per agent: running / finished / stopped, the step
 *                   it is on, its last few steps, today's model requests, and a
 *                   feed of every agent's steps, newest first
 *   Inbox           what waits on the operator
 *   Agents & briefs switches, budgets, briefs and a Run button per agent
 *   Ask · Research · Market brief · Data quality · Agent log
 *
 * Nothing here places an order or spends a trial: approving an inbox item
 * records a decision, and registering a draft or relocking a deployment are
 * still commands the operator runs. The trade desk lives on Live & Risk only.
 */

'use client';

import { useCallback, useEffect, useState } from 'react';

import { agentsApi } from '@/lib/api';
import MarketBriefView from './MarketBriefView';
import type {
  ActivityResponse,
  AgentActivity,
  AgentItem,
  AgentOutput,
  AgentsResponse,
  AgentStep,
  DatasetGrade,
  MarketBrief as MarketBriefData,
} from '@/lib/api';

const VIEWS = [
  ['live', 'Live'],
  ['inbox', 'Inbox'],
  ['agents', 'Agents & briefs'],
  ['ask', 'Ask'],
  ['research', 'Research'],
  ['brief', 'Market brief'],
  ['quality', 'Data quality'],
  ['log', 'Agent log'],
] as const;
type View = (typeof VIEWS)[number][0];

type Quality = { grades: DatasetGrade[]; held: { dataset: string; path: string; reason: string; at: string }[] };
type LogView = { verified: boolean; problem: string; entries: { seq: number; at: string; kind: string; agent: string }[] };
type Tone = 'brand' | 'up' | 'down' | 'caveat' | undefined;

function when(at: string): string {
  if (!at) return '—';
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? at : d.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}

/** "12 s ago", "4 min ago", "3 h ago", else the date. */
function ago(at: string, now: number): string {
  const t = new Date(at).getTime();
  if (!at || Number.isNaN(t)) return '';
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return when(at);
}

const STATE: Record<AgentActivity['state'], [string, Tone]> = {
  running: ['Working', 'brand'],
  ok: ['Done', 'up'],
  skipped: ['Skipped', undefined],
  over_budget: ['Out of requests', 'caveat'],
  refused: ['Refused', 'caveat'],
  failed: ['Failed', 'down'],
  stopped: ['Stopped', 'down'],
  idle: ['Never run', undefined],
};

const SEVERITY_TONE: Record<string, Tone> = { info: 'brand', warn: 'caveat', critical: 'down' };

function Badge({ tone, children }: { tone?: Tone; children: React.ReactNode }) {
  return (
    <span className="tbadge" data-tone={tone}>
      {children}
    </span>
  );
}

// ---------------------------------------------------------------- live

function Steps({ steps, now, max }: { steps: AgentStep[]; now: number; max: number }) {
  const shown = steps.slice(-max);
  return (
    <ol className="ai-steps">
      {shown.map((step, i) => (
        <li key={`${step.at}-${i}`} data-kind={step.kind} data-last={i === shown.length - 1}>
          <span className="ai-step-text">{step.text}</span>
          <time dateTime={step.at}>{ago(step.at, now)}</time>
        </li>
      ))}
    </ol>
  );
}

function AgentCard({
  agent,
  row,
  now,
  onRun,
}: {
  agent: AgentActivity;
  row?: AgentsResponse['agents'][number];
  now: number;
  onRun: (name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [label, tone] = STATE[agent.state] ?? ['—', undefined];
  const running = agent.state === 'running';
  const used = row?.used_today ?? 0;
  const budget = row?.daily_requests ?? 0;
  return (
    <article className="ai-card" data-state={agent.state}>
      <header>
        <span className="tdot" data-tone={tone} data-live={running} />
        <div className="ai-card-title">
          <b>{agent.title}</b>
          <span>{agent.job}</span>
        </div>
        <Badge tone={tone}>{label}</Badge>
      </header>

      <div className="ai-now">
        <span>{running ? 'Now' : agent.state === 'idle' ? 'Waiting' : 'Last'}</span>
        <p>{running ? agent.now || 'Starting…' : agent.summary || agent.now || 'Has not run yet.'}</p>
        {agent.started && <time dateTime={agent.started}>{running ? `started ${ago(agent.started, now)}` : when(agent.started)}</time>}
      </div>

      {agent.steps.length > 0 && <Steps steps={agent.steps} now={now} max={open ? 60 : 4} />}

      <footer>
        {agent.uses_model ? (
          <span className="ai-meter" title={`${used} of ${budget} model requests used today`}>
            <i style={{ width: `${budget ? Math.min(100, (used / budget) * 100) : 0}%` }} />
            <em>
              {used}/{budget} requests today
            </em>
          </span>
        ) : (
          <span className="ai-meter-none">No model: plain code</span>
        )}
        <span className="ai-card-acts">
          {agent.steps.length > 4 && (
            <button type="button" className="tbtn sm" onClick={() => setOpen((v) => !v)}>
              {open ? 'Fewer steps' : `All ${agent.steps.length} steps`}
            </button>
          )}
          {agent.cli_only ? (
            <code className="ai-cli" title="It reads the whole price panel, so it runs outside the web server">
              make agent NAME={agent.name}
            </code>
          ) : (
            <button
              type="button"
              className="tbtn sm go"
              disabled={!agent.enabled || running}
              title={agent.enabled ? '' : 'Switched off in Agents & briefs'}
              onClick={() => onRun(agent.name)}
            >
              {running ? 'Running' : 'Run now'}
            </button>
          )}
        </span>
      </footer>
    </article>
  );
}

/** Working first, then the most recently run, then those that never ran. */
function ordered(agents: AgentActivity[]): AgentActivity[] {
  const rank = (a: AgentActivity) => (a.state === 'running' ? 0 : a.state === 'idle' ? 2 : 1);
  return [...agents].sort((a, b) => rank(a) - rank(b) || b.started.localeCompare(a.started) || a.title.localeCompare(b.title));
}

function Live({
  data,
  inbox,
  onRead,
  onOpen,
}: {
  data: AgentsResponse;
  inbox: number;
  onRead: () => void;
  onOpen: (view: View) => void;
}) {
  const [activity, setActivity] = useState<ActivityResponse | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [error, setError] = useState('');

  const read = useCallback(() => {
    agentsApi
      .activity(60)
      .then((r) => {
        setActivity(r);
        setNow(Date.now());
        setError('');
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);

  // Fast while something runs, slow when nothing does.
  const busy = (activity?.running ?? 0) > 0;
  useEffect(() => {
    read();
    const timer = window.setInterval(read, busy ? 2500 : 12000);
    return () => window.clearInterval(timer);
  }, [read, busy]);
  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);

  const run = (name: string) => {
    agentsApi
      .run(name)
      .then((r) => {
        setError(r.ok ? '' : r.error ?? 'not started');
        read();
        onRead();
      })
      .catch((e: unknown) => setError(String(e)));
  };

  const rows = new Map(data.agents.map((a) => [a.name, a]));
  const usedToday = data.agents.reduce((sum, a) => sum + (a.uses_model ? a.used_today : 0), 0);
  const budgetToday = data.agents.reduce((sum, a) => sum + (a.uses_model ? a.daily_requests : 0), 0);

  return (
    <>
      <div className="tstats">
        <div className="tstat-card">
          <span>Working now</span>
          <b className={busy ? 'brand' : ''}>{activity?.running ?? '—'}</b>
          <i>of {data.agents.length} agents</i>
        </div>
        <button type="button" className="tstat-card ai-stat-link" onClick={() => onOpen('inbox')}>
          <span>Waiting on you</span>
          <b className={inbox ? 'caveat' : ''}>{inbox}</b>
          <i>{inbox ? 'open the inbox' : 'nothing to decide'}</i>
        </button>
        <div className="tstat-card">
          <span>Agent trials this week</span>
          <b>
            {data.trials.spent}
            <small> / {data.trials.per_week ?? 'no limit'}</small>
          </b>
          <i>each one is logged before its result is read</i>
        </div>
        <div className="tstat-card">
          <span>Model requests today</span>
          <b>
            {usedToday}
            <small> / {budgetToday}</small>
          </b>
          <i>across every agent</i>
        </div>
      </div>

      {error && <p className="tnote bad">{error}</p>}

      <div className="ai-live">
        <div className="ai-grid">
          {ordered(activity?.agents ?? []).map((agent) => (
            <AgentCard key={agent.name} agent={agent} row={rows.get(agent.name)} now={now} onRun={run} />
          ))}
        </div>
        <aside className="tpanel ai-feed">
          <h3>
            Activity <span className="tdot" data-tone={busy ? 'brand' : undefined} data-live={busy} />
          </h3>
          <p className="tfine">Every step every agent reports, newest first. Updates by itself.</p>
          {activity && activity.feed.length === 0 ? (
            // Runs from before the step trail existed have a result but no
            // steps, so "no agent has run" was false on real data.
            <div className="tempty">
              {activity.agents.some((agent) => agent.run_id)
                ? 'No steps recorded yet. Runs from before this view kept none; the next run will show its steps here.'
                : 'No agent has run yet.'}
            </div>
          ) : (
            <ol className="ai-feed-list">
              {(activity?.feed ?? []).map((step, i) => (
                <li key={`${step.agent}-${step.at}-${i}`} data-kind={step.kind}>
                  <b>{step.title}</b>
                  <span>{step.text}</span>
                  <time dateTime={step.at}>{ago(step.at, now)}</time>
                </li>
              ))}
            </ol>
          )}
        </aside>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- inbox

function Inbox({ items, onDone }: { items: AgentItem[]; onDone: () => void }) {
  const [error, setError] = useState('');
  const decide = (id: string, decision: 'approved' | 'dismissed') => {
    agentsApi
      .decide(id, decision)
      .then((r) => {
        setError(r.ok ? '' : r.error ?? 'not recorded');
        onDone();
      })
      .catch((e: unknown) => setError(String(e)));
  };
  return (
    <div className="tpanel">
      <h3>Waiting on you ({items.length})</h3>
      <p className="tfine">
        Approving records your decision and nothing else. A draft still needs <code>make paper-agent-approve</code>; a
        rerun or a relock is still your command.
      </p>
      {error && <p className="tnote bad">{error}</p>}
      {items.length === 0 ? (
        <div className="tempty">Nothing waiting on you.</div>
      ) : (
        <ul className="ai-inbox">
          {items.map((item) => (
            <li key={item.id}>
              <div>
                <span className="ai-inbox-meta">
                  <Badge tone={SEVERITY_TONE[item.severity]}>{item.severity}</Badge>
                  <span>
                    {item.agent} · {item.kind} · {when(item.at)}
                  </span>
                </span>
                <b>{item.title}</b>
                {item.body && <p>{item.body}</p>}
              </div>
              <span className="ai-inbox-acts">
                <button type="button" className="tbtn sm ok" onClick={() => decide(item.id, 'approved')}>
                  Approve
                </button>
                <button type="button" className="tbtn sm" onClick={() => decide(item.id, 'dismissed')}>
                  Dismiss
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- agents & briefs

function BriefBox({ name, initial, label }: { name: string; initial: string; label: string }) {
  const [text, setText] = useState(initial);
  const [saved, setSaved] = useState('');
  useEffect(() => setText(initial), [initial]);
  const save = () => {
    agentsApi
      .brief(name, text)
      .then((r) => setSaved(r.ok ? 'Saved' : r.error ?? 'not saved'))
      .catch((e: unknown) => setSaved(String(e)));
  };
  return (
    <div className="ai-brief">
      <label className="tfine" htmlFor={`brief-${name}`}>
        {label}
      </label>
      <textarea
        id={`brief-${name}`}
        value={text}
        placeholder="What should this agent focus on? It cannot change its rules, tools or limits."
        onChange={(e) => {
          setText(e.target.value);
          setSaved('');
        }}
        rows={2}
      />
      <span className="ai-brief-acts">
        <button type="button" className="tbtn sm" disabled={text === initial} onClick={save}>
          Save brief
        </button>
        {saved && <span className="tfine">{saved}</span>}
      </span>
    </div>
  );
}

function Agents({ data, onChange }: { data: AgentsResponse; onChange: () => void }) {
  const [args, setArgs] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const toggle = (name: string, enabled: boolean) =>
    agentsApi.setting(name, { enabled }).then(onChange).catch((e: unknown) => setError(String(e)));
  const run = (name: string) => {
    const parsed: Record<string, string> = {};
    for (const part of (args[name] ?? '').split(/\s+/)) {
      const at = part.indexOf('=');
      if (at > 0) parsed[part.slice(0, at)] = part.slice(at + 1);
    }
    agentsApi
      .run(name, parsed)
      .then((r) => {
        setError(r.ok ? '' : r.error ?? 'not started');
        onChange();
      })
      .catch((e: unknown) => setError(String(e)));
  };
  return (
    <>
      <div className="tpanel">
        <h3>Brief for every agent</h3>
        {error && <p className="tnote bad">{error}</p>}
        <BriefBox name="all" initial={data.brief_all} label="Read by every agent before its own brief." />
      </div>
      <div className="ai-grid">
        {data.agents.map((a) => (
          <article key={a.name} className="ai-card">
            <header>
              <span className="tdot" data-tone={a.enabled ? 'up' : undefined} />
              <div className="ai-card-title">
                <b>{a.title}</b>
                <span>{a.job}</span>
              </div>
              <label className="ai-switch">
                <input type="checkbox" checked={a.enabled} onChange={(e) => toggle(a.name, e.target.checked)} />
                <span>{a.enabled ? 'On' : 'Off'}</span>
              </label>
            </header>
            <p className="tfine">
              {a.schedule || 'On demand'} · {a.uses_model ? `${a.used_today}/${a.daily_requests} requests today` : 'no model'}
              {a.switched === 'operator' && ' · switched by you'}
            </p>
            {a.never.length > 0 && <p className="tfine">Never: {a.never.join('; ')}</p>}
            <BriefBox name={a.name} initial={a.brief} label="Brief" />
            <footer>
              <input
                aria-label={`arguments for ${a.name}`}
                placeholder="key=value (optional)"
                value={args[a.name] ?? ''}
                onChange={(e) => setArgs({ ...args, [a.name]: e.target.value })}
              />
              <button type="button" className="tbtn sm go" disabled={!a.enabled || a.running} onClick={() => run(a.name)}>
                {a.running ? 'Running' : 'Run'}
              </button>
            </footer>
          </article>
        ))}
      </div>
    </>
  );
}

// ---------------------------------------------------------------- the rest

function MarketBrief() {
  const [brief, setBrief] = useState<{ text?: string; brief?: MarketBriefData | null; at?: string; error?: string } | null>(null);
  useEffect(() => {
    agentsApi.marketBrief().then(setBrief).catch((e: unknown) => setBrief({ error: String(e) }));
  }, []);
  if (!brief) return null;
  if (brief.brief) return <MarketBriefView brief={brief.brief} at={brief.at} />;
  return (
    <div className="tpanel">
      <h3>Market brief</h3>
      {brief.text ? (
        <>
          <p className="tfine">{when(brief.at ?? '')} · an older brief, written before briefs were saved as data</p>
          <pre className="ai-pre">{brief.text}</pre>
        </>
      ) : (
        <div className="tempty">{brief.error}</div>
      )}
    </div>
  );
}

function Ask() {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  const ask = () => {
    if (!question.trim()) return;
    setBusy(true);
    agentsApi
      .ask(question)
      .then((r) => setAnswer(r.ok ? `${r.answer ?? ''}\n\n(${r.model ?? 'model'}, ${r.requests ?? 0} requests)` : r.error ?? 'no answer'))
      .catch((e: unknown) => setAnswer(String(e)))
      .finally(() => setBusy(false));
  };
  return (
    <div className="tpanel">
      <h3>Ask the knowledge agent</h3>
      <p className="tfine">It answers from the papers, cards, decisions and data grades on disk, and names what it read.</p>
      <textarea
        aria-label="question"
        value={question}
        placeholder="e.g. Which momentum ideas have we already rejected, and why?"
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) ask();
        }}
        rows={3}
      />
      <div className="tacts" style={{ marginTop: 8 }}>
        <button type="button" className="tbtn go" disabled={busy || !question.trim()} onClick={ask}>
          {busy ? 'Asking…' : 'Ask'}
        </button>
      </div>
      {answer && <pre className="ai-pre">{answer}</pre>}
    </div>
  );
}

const GRADE_TONE: Record<string, Tone> = { A: 'up', B: 'up', C: 'caveat', D: 'down' };

function QualityTable() {
  const [quality, setQuality] = useState<Quality | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    agentsApi
      .quality()
      .then(setQuality)
      .catch((e: unknown) => setError(String(e)));
  }, []);
  return (
    <div className="tpanel">
      <h3>Data quality</h3>
      <p className="tfine">
        Every dataset graded against one contract: registered, provenance, fingerprint, sense checks, quarantine.
        Freshness is shown apart; a backtest refuses a panel below its grade.
      </p>
      {error && <p className="tnote bad">{error}</p>}
      {quality && (
        <>
          <div className="tscroll">
            <table className="ttable">
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th>Grade</th>
                  <th>Freshness</th>
                  <th>Checks</th>
                </tr>
              </thead>
              <tbody>
                {quality.grades.map((g) => (
                  <tr key={g.name}>
                    <td>
                      <b>{g.name}</b>
                      {g.critical && <span className="tfine"> · critical</span>}
                      {!g.point_in_time && <span className="tfine"> · not point-in-time</span>}
                    </td>
                    <td>
                      <Badge tone={g.usable ? GRADE_TONE[g.grade] : 'down'}>{g.grade}</Badge>
                      {!g.usable && <span className="tfine"> below {g.min_grade}</span>}
                    </td>
                    <td>{g.freshness}</td>
                    <td className="tfine">
                      {g.checks
                        .filter((c) => c.state !== 'pass')
                        .map((c) => `${c.name}: ${c.detail}`)
                        .join(' · ') || 'all pass'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="tfine" style={{ marginTop: 8 }}>
            Held in quarantine:{' '}
            {quality.held.length === 0 ? 'none' : quality.held.map((h) => `${h.path} (${h.reason})`).join('; ')}
          </p>
        </>
      )}
    </div>
  );
}

function Log() {
  const [view, setView] = useState<LogView | null>(null);
  useEffect(() => {
    agentsApi.log(40).then(setView).catch(() => undefined);
  }, []);
  if (!view) return null;
  return (
    <div className="tpanel">
      <h3>Agent log</h3>
      <p className={view.verified ? 'tfine' : 'tnote bad'}>
        {view.verified ? 'The hash chain verifies.' : `The chain does not verify: ${view.problem}`}
      </p>
      {view.entries.length === 0 ? (
        <div className="tempty">Nothing logged yet.</div>
      ) : (
        <table className="ttable">
          <thead>
            <tr>
              <th>#</th>
              <th>When</th>
              <th>Agent</th>
              <th>What</th>
            </tr>
          </thead>
          <tbody>
            {view.entries.map((e) => (
              <tr key={e.seq}>
                <td className="tfine">{e.seq}</td>
                <td className="tfine">{when(e.at)}</td>
                <td>{e.agent}</td>
                <td>{e.kind}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** Start a research or skeptic run and read what came back: drafts, Quantpedia leads, attacks. */
function Research({ onStarted }: { onStarted: () => void }) {
  const [topic, setTopic] = useState('');
  const [strategy, setStrategy] = useState('');
  const [note, setNote] = useState('');
  const [latest, setLatest] = useState<Record<string, AgentOutput | undefined>>({});
  const read = useCallback(() => {
    for (const name of ['research', 'skeptic']) {
      agentsApi
        .outputs(name, 1)
        .then((r) => setLatest((prev) => ({ ...prev, [name]: r.outputs[0] })))
        .catch(() => undefined);
    }
  }, []);
  useEffect(() => {
    read();
    const timer = window.setInterval(read, 15000);
    return () => window.clearInterval(timer);
  }, [read]);
  const start = (name: string, args: Record<string, string>) =>
    agentsApi
      .run(name, args)
      .then((r) => {
        setNote(r.ok ? `${name} started. Watch it work on the Live view.` : r.error ?? 'not started');
        if (r.ok) onStarted();
      })
      .catch((e: unknown) => setNote(String(e)));
  return (
    <>
      <div className="tgrid">
        <div className="tpanel">
          <h3>Find and draft ideas</h3>
          <p className="tfine">
            Searches arXiv and OpenAlex, reads Quantpedia&rsquo;s catalogue if synced (<code>make quantpedia-sync</code>),
            drafts cards and checks them against ideas already tried. It stops at drafts: nothing is registered or
            backtested, and no trial is spent.
          </p>
          <div className="ai-inline">
            <input
              aria-label="research topic"
              placeholder="topic, e.g. delivery percentage and next-day returns"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
            />
            <button type="button" className="tbtn go" disabled={!topic.trim()} onClick={() => start('research', { topic })}>
              Research
            </button>
          </div>
        </div>
        <div className="tpanel">
          <h3>Try to break a result</h3>
          <p className="tfine">
            The skeptic reads a stored backtest and attacks it: without its best year, its best days, Indian stress
            windows, the t-statistic and twice the costs.
          </p>
          <div className="ai-inline">
            <input
              aria-label="strategy id"
              placeholder="strategy id"
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
            />
            <button type="button" className="tbtn go" disabled={!strategy.trim()} onClick={() => start('skeptic', { strategy })}>
              Attack
            </button>
          </div>
        </div>
      </div>
      {note && <p className="tnote">{note}</p>}
      {(['research', 'skeptic'] as const).map((name) => {
        const out = latest[name];
        if (!out) return null;
        return (
          <div key={name} className="tpanel">
            <h3>
              Latest {name} run <Badge tone={out.status === 'ok' ? 'up' : 'caveat'}>{out.status}</Badge>
            </h3>
            <p className="tfine">
              {when(out.started)} · {out.summary}
            </p>
            <ul className="ai-inbox">
              {out.items.map((item) => (
                <li key={item.id}>
                  <div>
                    <span className="ai-inbox-meta">
                      <Badge tone="brand">{item.kind}</Badge>
                    </span>
                    <b>{item.title}</b>
                    {item.body && <p>{item.body}</p>}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </>
  );
}

export function AgentsTab() {
  const [view, setView] = useState<View>('live');
  const [data, setData] = useState<AgentsResponse | null>(null);
  const [items, setItems] = useState<AgentItem[]>([]);
  const [error, setError] = useState('');
  const read = useCallback(() => {
    agentsApi
      .list()
      .then((r) => {
        setData(r);
        setError('');
      })
      .catch((e: unknown) => setError(String(e)));
    agentsApi
      .inbox()
      .then((r) => setItems(r.items))
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    read();
    const timer = window.setInterval(read, 15000);
    return () => window.clearInterval(timer);
  }, [read]);

  if (error) {
    return (
      <section className="tsection">
        <p className="tnote bad">The agents could not be read: {error}</p>
      </section>
    );
  }
  if (!data) return <section className="tsection tempty">Reading the agents…</section>;
  return (
    <>
      <div className="tseg" role="tablist" aria-label="AI">
        {VIEWS.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={view === id} onClick={() => setView(id)}>
            {label}
            {id === 'inbox' && items.length > 0 && <span className="ai-count">{items.length}</span>}
          </button>
        ))}
      </div>
      <section className="tsection ai-section">
        {!data.log_ok && <p className="tnote bad">The agent log does not verify: {data.log_problem}</p>}
        {view === 'live' && <Live data={data} inbox={items.length} onRead={read} onOpen={setView} />}
        {view === 'inbox' && <Inbox items={items} onDone={read} />}
        {view === 'agents' && <Agents data={data} onChange={read} />}
        {view === 'ask' && <Ask />}
        {view === 'research' && <Research onStarted={read} />}
        {view === 'brief' && <MarketBrief />}
        {view === 'quality' && <QualityTable />}
        {view === 'log' && <Log />}
      </section>
    </>
  );
}
