/**
 * The AI page (ADR-151): what the agents are doing, what ran, what came out.
 *
 * It had ten views (Live, Inbox, Org chart, Calendar, Agents & briefs, Ask,
 * Research, Market brief, Data quality, Agent log) and a new reader could not
 * tell where to start. It now has four:
 *
 *   Overview   what needs you, the research pipeline as five steps with last
 *              week's numbers (find ideas, write rules, backtest, gate, paper
 *              trade), the newest results, and what is running and ran today
 *   Results    every outcome, newest first, each with one line on what it
 *              means: autopilot batches, lab tests, gate verdicts, paper books,
 *              research drafts, skeptic attacks, the market brief, agent checks
 *   Agents     the team: one card per agent with its switch, brief and Run
 *              button; the org chart, the schedule, and data and log health
 *   Ask        ask the knowledge agent, research a topic, attack a result
 *
 * Old links (`#agents/inbox`, `#agents/brief`, ...) open the view that now
 * holds them (`lib/aiFlow.openView`). Nothing here places an order or spends
 * a trial: approving an inbox item records a decision (an idea lab survivor
 * goes to the unchanged gate), and live money stays the operator's.
 */

'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowRight,
  CheckCircle2,
  CircleDashed,
  FileSearch,
  FlaskConical,
  Gavel,
  Lightbulb,
  LineChart,
  ListChecks,
  PenLine,
  ShieldAlert,
  XCircle,
} from 'lucide-react';

import { agentsApi } from '@/lib/api';
import { usePoll } from '@/lib/usePoll';
import { AGENTS_TAB } from '@/lib/poll';
import { nowLine } from '@/lib/agentNow';
import { ago, filterResults, openView, todaysRuns } from '@/lib/aiFlow';
import type { AiView, ResultFilter, TeamView } from '@/lib/aiFlow';
import { CalendarView, OrgChartView } from './CompanyViews';
import MarketBriefView from './MarketBriefView';
import type {
  ActivityResponse,
  AgentActivity,
  AgentItem,
  AgentsResponse,
  AgentStep,
  DatasetGrade,
  FlowOutcome,
  FlowResponse,
  FlowResult,
  FlowStage,
  MarketBrief as MarketBriefData,
} from '@/lib/api';
import './aitab.css';

const VIEWS: [AiView, string][] = [
  ['overview', 'Overview'],
  ['results', 'Results'],
  ['team', 'Agents'],
  ['ask', 'Ask'],
];

const TEAM_VIEWS: [TeamView, string][] = [
  ['cards', 'Team'],
  ['org', 'Org chart'],
  ['schedule', 'Schedule'],
  ['health', 'Data & log health'],
];

const FILTERS: [ResultFilter, string][] = [
  ['research', 'Research'],
  ['verdicts', 'Verdicts & paper books'],
  ['brief', 'Market brief'],
  ['checks', 'Agent checks'],
  ['all', 'Everything'],
];

/** Which agents do research, which manage, which keep the lights on. */
const GROUPS: [string, string, string[]][] = [
  ['Research pipeline', 'Find, write, test and challenge trading ideas.', ['research', 'autopilot', 'lab', 'skeptic']],
  ['Heads', 'Managers: split your tasks, unstick their agents, pass problems up to you.', ['head_research', 'head_platform', 'head_portfolio']],
];

/** The command that runs an agent too heavy for the web server. */
const CLI_RUN: Record<string, string> = { autopilot: 'make agents-autopilot' };

type Quality = { grades: DatasetGrade[]; held: { dataset: string; path: string; reason: string; at: string }[] };
type LogView = { verified: boolean; problem: string; entries: { seq: number; at: string; kind: string; agent: string }[] };
type Tone = 'brand' | 'up' | 'down' | 'caveat' | undefined;

function when(at: string): string {
  if (!at) return '—';
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? at : d.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
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

const OUTCOME: Record<FlowOutcome, [string, Tone]> = {
  pass: ['Passed', 'up'],
  partial: ['Worth a look', 'caveat'],
  fail: ['Failed', 'down'],
  info: ['Info', undefined],
};

const SEVERITY_TONE: Record<string, Tone> = { info: 'brand', warn: 'caveat', warning: 'caveat', critical: 'down' };

const STAGE_ICON = { find: FileSearch, write: PenLine, test: FlaskConical, gate: Gavel, paper: LineChart } as const;

const KIND_ICON: Record<FlowResult['kind'], typeof FileSearch> = {
  ideas: Lightbulb,
  batch: PenLine,
  test: FlaskConical,
  verdict: Gavel,
  paper: LineChart,
  attack: ShieldAlert,
  brief: FileSearch,
  check: ListChecks,
  problem: XCircle,
};

const KIND_LABEL: Record<FlowResult['kind'], string> = {
  ideas: 'Ideas',
  batch: 'Autopilot',
  test: 'Backtest',
  verdict: 'Gate verdict',
  paper: 'Paper book',
  attack: 'Skeptic',
  brief: 'Market brief',
  check: 'Agent check',
  problem: 'Problem',
};

function Badge({ tone, children }: { tone?: Tone; children: React.ReactNode }) {
  return (
    <span className="tbadge" data-tone={tone}>
      {children}
    </span>
  );
}

/** Ticks once a second so "4 min ago" stays true. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);
  return now;
}

// ================================================================ overview

function NeedsYou({ items, onDone }: { items: AgentItem[]; onDone: () => void }) {
  const [error, setError] = useState('');
  const [gate, setGate] = useState('');
  const [open, setOpen] = useState<string>('');
  const decide = (id: string, decision: 'approved' | 'dismissed') => {
    agentsApi
      .decide(id, decision)
      .then((r) => {
        setError(r.ok ? '' : r.error ?? 'not recorded');
        setGate(r.gate ?? '');
        onDone();
      })
      .catch((e: unknown) => setError(String(e)));
  };
  return (
    <section className="tpanel ai2-needs" data-empty={items.length === 0}>
      <header className="ai2-head">
        <h3>
          Needs you <span className="ai-count">{items.length}</span>
        </h3>
        <p className="tfine">
          Approving an idea lab survivor sends it to the gate. Approving anything else only records your decision.
        </p>
      </header>
      {error && <p className="tnote bad">{error}</p>}
      {gate && <p className="tnote">{gate}</p>}
      {items.length === 0 ? (
        <p className="ai2-calm">
          <CheckCircle2 size={16} /> Nothing waiting on you. The agents carry on by themselves.
        </p>
      ) : (
        <ul className="ai2-needs-list">
          {items.map((item) => (
            <li key={item.id}>
              <div className="ai2-needs-main">
                <span className="ai2-meta">
                  <Badge tone={SEVERITY_TONE[item.severity]}>{item.kind}</Badge>
                  <span>
                    from {item.agent} · {when(item.at)}
                  </span>
                </span>
                <b>{item.title}</b>
                {item.body && (
                  <>
                    <p className={open === item.id ? 'ai2-body open' : 'ai2-body'}>{item.body}</p>
                    {item.body.length > 220 && (
                      <button type="button" className="ai2-more" onClick={() => setOpen(open === item.id ? '' : item.id)}>
                        {open === item.id ? 'Less' : 'Read all'}
                      </button>
                    )}
                  </>
                )}
              </div>
              <span className="ai2-needs-acts">
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
    </section>
  );
}

function StageCard({ stage, index, running, now }: { stage: FlowStage; index: number; running: string[]; now: number }) {
  const Icon = STAGE_ICON[stage.key];
  const busy = running.length > 0;
  const never = stage.last.status === 'never';
  const tone: Tone = busy ? 'brand' : never ? undefined : stage.last.status === 'ok' ? 'up' : 'down';
  return (
    <li className="ai2-stage" data-busy={busy}>
      <span className="ai2-stage-icon">
        <Icon size={18} />
        <em>{index + 1}</em>
      </span>
      <b className="ai2-stage-title">{stage.title}</b>
      <span className="ai2-stage-num">
        <strong>{stage.number}</strong> {stage.label}
      </span>
      <p className="ai2-stage-what">{stage.what}</p>
      <span className="ai2-stage-last">
        <span className="tdot" data-tone={tone} data-live={busy} />
        {busy
          ? `Working now: ${running.join(', ')}`
          : never
            ? stage.key === 'write'
              ? 'First run: today at 17:00 IST'
              : stage.last.summary
            : `${stage.last.agent ? `${stage.last.agent} · ` : ''}${ago(stage.last.at, now)}`}
      </span>
    </li>
  );
}

function Pipeline({ flow, activity, now }: { flow: FlowResponse; activity: ActivityResponse | null; now: number }) {
  const runningNames = new Set((activity?.agents ?? []).filter((a) => a.state === 'running').map((a) => a.name));
  const title = new Map((activity?.agents ?? []).map((a) => [a.name, a.title]));
  return (
    <section className="tpanel ai2-pipeline">
      <header className="ai2-head">
        <h3>How an idea becomes a trade</h3>
        <p className="tfine">
          Every evening the agents run these steps on Indian stocks without you. Numbers cover the last {flow.days} days.
          Only steps 4 and 5 can lead to money, and real money always waits for you.
        </p>
      </header>
      <ol className="ai2-stages">
        {flow.stages.map((stage, i) => (
          <StageCard
            key={stage.key}
            stage={stage}
            index={i}
            now={now}
            running={stage.agents.filter((n) => runningNames.has(n)).map((n) => title.get(n) ?? n)}
          />
        ))}
      </ol>
    </section>
  );
}

function ResultCard({ result, now, compact = false }: { result: FlowResult; now: number; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const Icon = KIND_ICON[result.kind] ?? ListChecks;
  const [label, tone] = OUTCOME[result.outcome] ?? OUTCOME.info;
  const rows = open ? result.rows : result.rows.slice(0, compact ? 0 : 4);
  return (
    <article className="ai2-result" data-outcome={result.outcome}>
      <span className="ai2-result-icon" data-outcome={result.outcome}>
        <Icon size={16} />
      </span>
      <div className="ai2-result-main">
        <span className="ai2-meta">
          <span className="ai2-kind">{KIND_LABEL[result.kind]}</span>
          <span>{result.agent === 'gate' || result.agent === 'paper' ? '' : `${result.agent} · `}</span>
          <time dateTime={result.at} title={when(result.at)}>
            {ago(result.at, now)}
          </time>
        </span>
        <b className="ai2-result-title">{result.title}</b>
        {result.meaning && <p className="ai2-meaning">{result.meaning}</p>}
        {!compact && result.summary && result.summary !== result.title && <p className="tfine">{result.summary}</p>}
        {rows.length > 0 && (
          <ul className="ai2-rows">
            {rows.map((row, i) => (
              <li key={`${row.id}-${i}`}>
                <span className="tdot" data-tone={OUTCOME[row.tone]?.[1]} />
                <span className="ai2-row-main">
                  <span>
                    {row.id && row.id !== row.label && <code>{row.id}</code>} {row.label}
                  </span>
                  {open && row.detail && <span className="tfine">{row.detail}</span>}
                </span>
                <span className="ai2-row-status">{row.status}</span>
              </li>
            ))}
          </ul>
        )}
        {(result.rows.length > rows.length || (open && result.rows.length > 0)) && (
          <button type="button" className="ai2-more" onClick={() => setOpen((v) => !v)}>
            {open ? 'Show less' : `Show all ${result.rows.length} with details`}
          </button>
        )}
        {open && result.ref && (
          <p className="tfine">
            File: <code>{result.ref}</code>
          </p>
        )}
      </div>
      <Badge tone={tone}>{label}</Badge>
    </article>
  );
}

function RunRow({ agent, now }: { agent: AgentActivity; now: number }) {
  const [label, tone] = STATE[agent.state] ?? ['—', undefined];
  const running = agent.state === 'running';
  const line = nowLine(agent.steps, running);
  return (
    <li className="ai2-run" data-state={agent.state}>
      <span className="tdot" data-tone={tone} data-live={running} />
      <span className="ai2-run-main">
        <b>{agent.title}</b>
        <span>{running ? line.text || agent.now || 'Starting…' : agent.summary || agent.now}</span>
      </span>
      <span className="ai2-run-side">
        <Badge tone={tone}>{label}</Badge>
        <time dateTime={agent.started}>{ago(running ? line.since || agent.started : agent.started, now)}</time>
      </span>
    </li>
  );
}

function Overview({
  data,
  flow,
  activity,
  items,
  onRead,
  onOpen,
}: {
  data: AgentsResponse;
  flow: FlowResponse | null;
  activity: ActivityResponse | null;
  items: AgentItem[];
  onRead: () => void;
  onOpen: (view: AiView, filter?: ResultFilter) => void;
}) {
  const now = useNow();
  const working = activity?.running ?? 0;
  const today = todaysRuns(activity?.agents ?? [], now);
  const latest = (flow?.results ?? []).filter((r) => r.pipeline).slice(0, 5);
  const usedToday = data.agents.reduce((sum, a) => sum + (a.uses_model ? a.used_today : 0), 0);
  const budgetToday = data.agents.reduce((sum, a) => sum + (a.uses_model ? a.daily_requests : 0), 0);
  return (
    <>
      <p className="ai2-lead">
        Your AI research team reads papers, turns ideas into exact rules, backtests them and sends only the survivors
        through a fixed gate. It runs every evening by itself. It never trades real money.
      </p>
      <div className="ai2-pills">
        <span className="ai2-pill" data-on={working > 0}>
          <span className="tdot" data-tone={working ? 'brand' : undefined} data-live={working > 0} />
          {working ? `${working} agent${working > 1 ? 's' : ''} working now` : 'No agent working right now'}
        </span>
        <span className="ai2-pill" data-warn={items.length > 0}>
          {items.length ? `${items.length} waiting on you` : 'Nothing waiting on you'}
        </span>
        <span className="ai2-pill">
          {data.trials.spent} trials this week{data.trials.per_week ? ` of ${data.trials.per_week}` : ''}
        </span>
        <span className="ai2-pill">
          {usedToday} of {budgetToday} model requests today
        </span>
      </div>

      {!flow ? <div className="tempty">Reading the pipeline…</div> : <Pipeline flow={flow} activity={activity} now={now} />}

      <NeedsYou items={items} onDone={onRead} />

      <div className="ai2-two">
        <section className="tpanel">
          <header className="ai2-head ai2-head-row">
            <h3>Latest research results</h3>
            <button type="button" className="tbtn sm" onClick={() => onOpen('results', 'research')}>
              All results <ArrowRight size={14} />
            </button>
          </header>
          {latest.length === 0 ? (
            <div className="tempty">No results yet.</div>
          ) : (
            <div className="ai2-results">
              {latest.map((r) => (
                <ResultCard key={r.id} result={r} now={now} compact />
              ))}
            </div>
          )}
        </section>
        <section className="tpanel">
          <header className="ai2-head ai2-head-row">
            <h3>Today</h3>
            <button type="button" className="tbtn sm" onClick={() => onOpen('team')}>
              All agents <ArrowRight size={14} />
            </button>
          </header>
          {today.length === 0 ? (
            <p className="ai2-calm">
              <CircleDashed size={16} /> No agent has run yet today (IST). The first runs are at 08:45.
            </p>
          ) : (
            <ul className="ai2-runs">
              {today.map((a) => (
                <RunRow key={a.name} agent={a} now={now} />
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}

// ================================================================ results

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

function Results({ flow, filter, setFilter }: { flow: FlowResponse | null; filter: ResultFilter; setFilter: (f: ResultFilter) => void }) {
  const now = useNow();
  const shown = useMemo(() => filterResults(flow?.results ?? [], filter), [flow, filter]);
  return (
    <>
      <div className="ai2-chips" role="tablist" aria-label="Which results">
        {FILTERS.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={filter === id} onClick={() => setFilter(id)}>
            {label}
          </button>
        ))}
      </div>
      {filter === 'brief' && <MarketBrief />}
      {!flow ? (
        <div className="tempty">Reading results…</div>
      ) : shown.length === 0 ? (
        <div className="tempty">Nothing here yet.</div>
      ) : (
        <section className="tpanel">
          <p className="tfine ai2-legend">
            Newest first. Each result says what happened and what it means. Green passed, amber is worth a look, red
            failed. A failed idea is normal: most do.
          </p>
          <div className="ai2-results">
            {shown.map((r) => (
              <ResultCard key={r.id} result={r} now={now} />
            ))}
          </div>
        </section>
      )}
    </>
  );
}

// ================================================================ agents

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

function AgentCard({
  agent,
  row,
  now,
  onRun,
  onToggle,
}: {
  agent: AgentActivity;
  row?: AgentsResponse['agents'][number];
  now: number;
  onRun: (name: string, args?: Record<string, string>) => void;
  onToggle: (name: string, enabled: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState(false);
  const [args, setArgs] = useState('');
  const [label, tone] = STATE[agent.state] ?? ['—', undefined];
  const running = agent.state === 'running';
  const line = nowLine(agent.steps, running);
  const used = row?.used_today ?? 0;
  const budget = row?.daily_requests ?? 0;
  const run = () => {
    const parsed: Record<string, string> = {};
    for (const part of args.split(/\s+/)) {
      const at = part.indexOf('=');
      if (at > 0) parsed[part.slice(0, at)] = part.slice(at + 1);
    }
    onRun(agent.name, parsed);
  };
  return (
    <article className="ai-card" data-state={agent.state}>
      <header>
        <span className="tdot" data-tone={tone} data-live={running} />
        <div className="ai-card-title">
          <b>{agent.title}</b>
          <span>{agent.job}</span>
        </div>
        <Badge tone={agent.enabled ? tone : 'caveat'}>{agent.enabled ? label : 'Switched off'}</Badge>
      </header>

      <div className="ai-now">
        <span>{running ? 'Now' : agent.state === 'idle' ? 'Waiting' : 'Last run'}</span>
        <p>{running ? line.text || agent.now || 'Starting…' : agent.summary || agent.now || 'Has not run yet.'}</p>
        {running ? (
          <time dateTime={line.since || agent.started}>
            {line.since ? `this step began ${ago(line.since, now)}` : ''}
            {line.since && agent.started ? ' · ' : ''}
            {agent.started ? `run started ${ago(agent.started, now)}` : ''}
          </time>
        ) : (
          agent.started && <time dateTime={agent.started}>{when(agent.started)}</time>
        )}
      </div>

      {open && line.before.length > 0 && <Steps steps={line.before} now={now} max={60} />}

      <p className="tfine ai2-sched">When: {row?.schedule || agent.schedule || 'on demand'}</p>

      {settings && row && (
        <div className="ai2-settings">
          <label className="ai-switch">
            <input type="checkbox" checked={row.enabled} onChange={(e) => onToggle(agent.name, e.target.checked)} />
            <span>{row.enabled ? 'On: runs on its schedule' : 'Off: will not run'}</span>
          </label>
          {row.never.length > 0 && <p className="tfine">Never: {row.never.join('; ')}</p>}
          <BriefBox name={agent.name} initial={row.brief} label="Brief" />
          {!agent.cli_only && (
            <input
              aria-label={`arguments for ${agent.name}`}
              placeholder="optional key=value for the next run"
              value={args}
              onChange={(e) => setArgs(e.target.value)}
            />
          )}
        </div>
      )}

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
          {line.before.length > 0 && (
            <button type="button" className="tbtn sm" onClick={() => setOpen((v) => !v)}>
              {open ? 'Hide steps' : `Steps (${line.before.length})`}
            </button>
          )}
          <button type="button" className="tbtn sm" onClick={() => setSettings((v) => !v)}>
            {settings ? 'Close settings' : 'Settings'}
          </button>
          {agent.cli_only ? (
            <code className="ai-cli" title="It reads the whole price panel, so it runs outside the web server">
              {CLI_RUN[agent.name] ?? `make agent NAME=${agent.name}`}
            </code>
          ) : (
            <button
              type="button"
              className="tbtn sm go"
              disabled={!agent.enabled || running}
              title={agent.enabled ? '' : 'Switched off: turn it on in Settings'}
              onClick={run}
            >
              {running ? 'Running' : 'Run now'}
            </button>
          )}
        </span>
      </footer>
    </article>
  );
}

function Team({
  data,
  activity,
  onChange,
}: {
  data: AgentsResponse;
  activity: ActivityResponse | null;
  onChange: () => void;
}) {
  const now = useNow();
  const [error, setError] = useState('');
  const rows = new Map(data.agents.map((a) => [a.name, a]));
  const agents = activity?.agents ?? [];
  const grouped = new Set(GROUPS.flatMap(([, , names]) => names));
  const groups: [string, string, AgentActivity[]][] = [
    ...GROUPS.map(([title, what, names]): [string, string, AgentActivity[]] => [
      title,
      what,
      names.map((n) => agents.find((a) => a.name === n)).filter((a): a is AgentActivity => Boolean(a)),
    ]),
    ['Support', 'Keep data, briefs, schedules and the other agents healthy.', agents.filter((a) => !grouped.has(a.name))],
  ];
  const run = (name: string, args: Record<string, string> = {}) => {
    agentsApi
      .run(name, args)
      .then((r) => {
        setError(r.ok ? '' : r.error ?? 'not started');
        onChange();
      })
      .catch((e: unknown) => setError(String(e)));
  };
  const toggle = (name: string, enabled: boolean) =>
    agentsApi.setting(name, { enabled }).then(onChange).catch((e: unknown) => setError(String(e)));
  return (
    <>
      {error && <p className="tnote bad">{error}</p>}
      <details className="tpanel ai2-all-brief">
        <summary>
          <b>Brief for every agent</b>
          <span className="tfine">{data.brief_all ? ` · ${data.brief_all.slice(0, 90)}` : ' · none set'}</span>
        </summary>
        <BriefBox name="all" initial={data.brief_all} label="Read by every agent before its own brief." />
      </details>
      {groups.map(([title, what, list]) =>
        list.length === 0 ? null : (
          <section key={title} className="ai2-group">
            <header className="ai2-head">
              <h3>{title}</h3>
              <p className="tfine">{what}</p>
            </header>
            <div className="ai-grid">
              {list.map((agent) => (
                <AgentCard
                  key={agent.name}
                  agent={agent}
                  row={rows.get(agent.name)}
                  now={now}
                  onRun={run}
                  onToggle={toggle}
                />
              ))}
            </div>
          </section>
        ),
      )}
    </>
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
        {view.verified
          ? 'Every agent action is written to a hash-chained log, and the chain verifies: nothing was edited afterwards.'
          : `The chain does not verify: ${view.problem}`}
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

// ================================================================ ask

function Ask({ onStarted }: { onStarted: () => void }) {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  const [topic, setTopic] = useState('');
  const [strategy, setStrategy] = useState('');
  const [note, setNote] = useState('');
  const ask = () => {
    if (!question.trim()) return;
    setBusy(true);
    agentsApi
      .ask(question)
      .then((r) => setAnswer(r.ok ? `${r.answer ?? ''}\n\n(${r.model ?? 'model'}, ${r.requests ?? 0} requests)` : r.error ?? 'no answer'))
      .catch((e: unknown) => setAnswer(String(e)))
      .finally(() => setBusy(false));
  };
  const start = (name: string, args: Record<string, string>) =>
    agentsApi
      .run(name, args)
      .then((r) => {
        setNote(r.ok ? `The ${name} agent started. Its progress shows on Overview and its result under Results.` : r.error ?? 'not started');
        if (r.ok) onStarted();
      })
      .catch((e: unknown) => setNote(String(e)));
  return (
    <>
      <section className="tpanel">
        <h3>Ask a question</h3>
        <p className="tfine">
          The knowledge agent answers from the papers, strategy cards, decisions and data grades on disk, and names what
          it read.
        </p>
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
      </section>
      <div className="tgrid">
        <section className="tpanel">
          <h3>Research a topic now</h3>
          <p className="tfine">
            The research agent searches arXiv and OpenAlex and drafts ideas. It stops at drafts: nothing is tested and no
            trial is spent. It also runs every evening on its own topic list.
          </p>
          <div className="ai-inline">
            <input
              aria-label="research topic"
              placeholder="e.g. delivery percentage and next-day returns"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
            />
            <button type="button" className="tbtn go" disabled={!topic.trim()} onClick={() => start('research', { topic })}>
              Research
            </button>
          </div>
        </section>
        <section className="tpanel">
          <h3>Try to break a result</h3>
          <p className="tfine">
            The skeptic attacks a stored backtest: without its best year, its best days, Indian stress windows, the
            t-statistic and twice the costs.
          </p>
          <div className="ai-inline">
            <input aria-label="strategy id" placeholder="strategy id" value={strategy} onChange={(e) => setStrategy(e.target.value)} />
            <button type="button" className="tbtn go" disabled={!strategy.trim()} onClick={() => start('skeptic', { strategy })}>
              Attack
            </button>
          </div>
        </section>
      </div>
      {note && <p className="tnote">{note}</p>}
    </>
  );
}

// ================================================================ the page

/** `#agents/<old or new view>` opens that view, so old links still land. */
export function AgentsTab({ open = '' }: { open?: string }) {
  const wanted = openView(open);
  const [view, setView] = useState<AiView>(wanted.view);
  const [team, setTeam] = useState<TeamView>(wanted.team ?? 'cards');
  const [filter, setFilter] = useState<ResultFilter>(wanted.filter ?? 'research');
  useEffect(() => {
    if (!open) return;
    const next = openView(open);
    setView(next.view);
    if (next.team) setTeam(next.team);
    if (next.filter) setFilter(next.filter);
  }, [open]);

  const [data, setData] = useState<AgentsResponse | null>(null);
  const [items, setItems] = useState<AgentItem[]>([]);
  const [flow, setFlow] = useState<FlowResponse | null>(null);
  const [activity, setActivity] = useState<ActivityResponse | null>(null);
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
    agentsApi
      .flow()
      .then(setFlow)
      .catch(() => undefined);
  }, []);
  const readActivity = useCallback(() => {
    agentsApi
      .activity(60)
      .then(setActivity)
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    read();
    const timer = window.setInterval(read, 30000);
    return () => window.clearInterval(timer);
  }, [read]);
  // Faster while something runs, slow when nothing does, never while hidden.
  usePoll(readActivity, AGENTS_TAB, (activity?.running ?? 0) > 0);

  const refresh = () => {
    read();
    readActivity();
  };
  const go = (next: AiView, nextFilter?: ResultFilter) => {
    setView(next);
    if (nextFilter) setFilter(nextFilter);
  };

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
            {id === 'overview' && items.length > 0 && <span className="ai-count">{items.length}</span>}
          </button>
        ))}
      </div>
      <section className="tsection ai-section ai2">
        {!data.log_ok && <p className="tnote bad">The agent log does not verify: {data.log_problem}</p>}
        {view === 'overview' && (
          <Overview data={data} flow={flow} activity={activity} items={items} onRead={refresh} onOpen={go} />
        )}
        {view === 'results' && <Results flow={flow} filter={filter} setFilter={setFilter} />}
        {view === 'team' && (
          <>
            <div className="ai2-chips" role="tablist" aria-label="Agents">
              {TEAM_VIEWS.map(([id, label]) => (
                <button key={id} type="button" role="tab" aria-selected={team === id} onClick={() => setTeam(id)}>
                  {label}
                </button>
              ))}
            </div>
            {team === 'cards' && <Team data={data} activity={activity} onChange={refresh} />}
            {team === 'org' && <OrgChartView />}
            {team === 'schedule' && <CalendarView />}
            {team === 'health' && (
              <>
                <QualityTable />
                <Log />
              </>
            )}
          </>
        )}
        {view === 'ask' && <Ask onStarted={refresh} />}
      </section>
    </>
  );
}
