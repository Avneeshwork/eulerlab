/**
 * The agent company as a family tree (ADR-124), on the AI tab's Org chart view.
 *
 *            You (CEO) ─ ─ ─ Gate and mandate (outside the chart)
 *       ┌────────┼─────────┐
 *     Head     Head       Head          click anyone: their job, duties, what
 *      │        │          │            they can be given, today's plan, their
 *    agents   agents     agents         tasks with every event, and the checks
 *
 * Everything shown is read from the API's files: the tree from config, tasks
 * from data/agents/tasks.jsonl, plans from the launchd schedule and the runs
 * that happened. The page's only writes are your task form and your buttons on
 * a task (run one that waits for you, retry, send back, close, cancel).
 */

'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { agentsApi } from '@/lib/api';
import { buttonHelp, headline, needsYou, whatItDoes, whyRaised } from '@/lib/taskWords';
import type {
  AgentPlan,
  AgentTask,
  CapabilitiesResponse,
  OrgChart,
  OrgGoal,
  OrgPerson,
  PlanTask,
  TaskAction,
  TasksResponse,
} from '@/lib/api';

type Tone = 'brand' | 'up' | 'down' | 'caveat' | undefined;

function Badge({ tone, children }: { tone?: Tone; children: React.ReactNode }) {
  return (
    <span className="tbadge" data-tone={tone}>
      {children}
    </span>
  );
}

const STATUS_TONE: Record<AgentTask['status'], Tone> = {
  open: 'brand',
  assigned: 'brand',
  doing: 'brand',
  review: 'caveat',
  done: 'up',
  blocked: 'down',
  closed: undefined,
  cancelled: undefined,
};
const STATUS_WORD: Record<AgentTask['status'], string> = {
  open: 'new, for its head',
  assigned: 'to do',
  doing: 'running',
  review: 'being checked',
  done: 'done',
  blocked: 'needs you',
  closed: 'closed',
  cancelled: 'cancelled',
};
const SLOT_TONE: Record<string, Tone> = { ran: 'up', upcoming: undefined, due: 'brand', missed: 'down', 'not run': 'caveat' };
const ACTIVE = new Set(['open', 'assigned', 'doing', 'review', 'blocked']);
const GOAL_TONE: Record<OrgGoal['status'], Tone> = { proposed: 'caveat', approved: 'up', retired: undefined };

type Selected = { kind: 'ceo' } | { kind: 'gate'; id: string } | { kind: 'person'; name: string; dept: string; head: boolean };

function when(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function Goals({ goals }: { goals: OrgGoal[] }) {
  if (goals.length === 0) return <p className="tfine">No goals set.</p>;
  return (
    <ul className="org-goals">
      {goals.map((g) => (
        <li key={g.id}>
          <Badge tone={GOAL_TONE[g.status]}>{g.status}</Badge> {g.text}
          <span className="tfine"> · measured by {g.measure}</span>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- one task

/** What every card needs from the chart: display names, and each skill's sentence and auto flag. */
type CardInfo = {
  titles: Map<string, string>;
  skills: Map<string, { what: string; auto: boolean }>;
  byId: Map<string, AgentTask>;
};
const CardContext = createContext<CardInfo>({
  titles: new Map(),
  skills: new Map(),
  byId: new Map(),
});

function TaskCard({
  task,
  all,
  onAct,
  busy,
  depth = 0,
}: {
  task: AgentTask;
  all: AgentTask[];
  onAct: (id: string, action: TaskAction) => void;
  busy: Set<string>;
  depth?: number;
}) {
  const { titles, skills, byId } = useContext(CardContext);
  const [open, setOpen] = useState(false);
  const subs = all.filter((t) => t.parent === task.id);
  const isHeadTask = task.owner.startsWith('head_');
  const running = busy.has(`task:${task.id}`) || busy.has(`wake:${task.department}`);
  const skill = skills.get(`${task.owner}:${task.kind}`);
  const actions: [TaskAction, string, string][] = [];
  if (!isHeadTask && task.status === 'assigned') actions.push(['run', 'Run now', 'go']);
  const stuckSubs = subs.some((x) => x.status === 'blocked');
  if ((task.status === 'blocked' && !isHeadTask) || (isHeadTask && stuckSubs))
    actions.push(['assist', task.help_wanted ? 'AI help asked…' : 'Ask AI for help', 'primary']);
  if (task.status === 'blocked' || task.status === 'cancelled') actions.push(['retry', 'Retry', '']);
  if (isHeadTask && task.status === 'done') {
    actions.push(['close', 'Accept and close', 'ok']);
    actions.push(['send_back', 'Send back', '']);
  }
  if (ACTIVE.has(task.status) && task.status !== 'doing') actions.push(['cancel', 'Cancel', '']);
  const last = task.history[task.history.length - 1];
  const parentTitle = byId.get(task.parent)?.title ?? '';
  const need = needsYou(task, { auto: skill?.auto, stuckSteps: stuckSubs });
  const due = ACTIVE.has(task.status) && task.due < new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
  return (
    <li className="org-task" data-depth={depth}>
      <div className="org-task-head">
        <Badge tone={STATUS_TONE[task.status]}>{STATUS_WORD[task.status]}</Badge>
        <b>{headline(task)}</b>
        {running && <Badge tone="brand">working…</Badge>}
      </div>
      <dl className="org-task-plain">
        <dt>What it is for</dt>
        <dd>{whatItDoes(task, skill?.what ?? '', titles)}</dd>
        <dt>Why it was raised</dt>
        <dd>{whyRaised(task, titles, parentTitle)}</dd>
        <dt>Does it need you?</dt>
        <dd>
          <Badge tone={need.yes ? 'caveat' : 'up'}>{need.yes ? 'Yes' : 'No'}</Badge> {need.text}
          {due && ` It was due ${task.due}.`}
        </dd>
      </dl>
      {task.summary && <p className="org-task-summary">Result: {task.summary}</p>}
      {last?.note && task.status === 'blocked' && <p className="tnote bad">{String(last.note)}</p>}
      {actions.length > 0 && (
        <ul className="org-task-buttons">
          {actions.map(([action, label, tone]) => (
            <li key={action}>
              <button
                type="button"
                className={`tbtn sm ${tone}`}
                disabled={running || (action === 'assist' && task.help_wanted)}
                onClick={() => onAct(task.id, action)}
              >
                {label}
              </button>
              <span className="tfine">{buttonHelp(action, task, titles)}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="org-task-actions">
        <button type="button" className="tbtn sm" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? 'Hide details' : 'Details for engineers'}
        </button>
        {subs.length > 0 && <span className="tfine">{subs.length} step(s) below</span>}
      </div>
      {open && (
        <div className="org-task-details">
          <p className="tfine">
            {task.id} · title “{task.title}” · owner {task.owner} · from {task.created_by} · due {task.due}
            {task.kind && ` · skill ${task.kind}`}
            {task.planned_by && ` · steps planned by ${task.planned_by === 'model' ? 'the AI model' : 'fixed rules'}`}
            {task.returns > 0 && ` · sent back ${task.returns}×`}
            {task.assists > 0 && ` · AI helped ${task.assists}×`}
          </p>
          {Object.keys(task.args).length > 0 && (
            <p className="tfine">
              {Object.entries(task.args)
                .map(([k, v]) => `${k}: ${v}`)
                .join(' · ')}
            </p>
          )}
          {task.detail && <p className="tfine org-task-detail">{task.detail}</p>}
          <ol className="org-history">
            {task.history.map((e, i) => (
              <li key={`${e.at}-${i}`}>
                <span className="tfine">{when(e.at)}</span> <b>{e.by}</b> {e.assist ? 'AI help' : e.event.replace('_', ' ')}
                {(e.note || e.summary) && <span> · {String(e.note || e.summary)}</span>}
                {typeof e.run_id === 'string' && e.run_id && <span className="tfine"> · run {e.run_id}</span>}
              </li>
            ))}
          </ol>
        </div>
      )}
      {subs.length > 0 && (
        <ul className="org-tasks org-subtasks">
          {subs.map((s) => (
            <TaskCard key={s.id} task={s} all={all} onAct={onAct} busy={busy} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

function TaskList({
  tasks,
  all,
  onAct,
  busy,
  empty,
}: {
  tasks: AgentTask[];
  all: AgentTask[];
  onAct: (id: string, action: TaskAction) => void;
  busy: Set<string>;
  empty: string;
}) {
  if (tasks.length === 0) return <p className="tfine">{empty}</p>;
  return (
    <ul className="org-tasks">
      {tasks.map((t) => (
        <TaskCard key={t.id} task={t} all={all} onAct={onAct} busy={busy} />
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- panels

function TodayPlan({ plan }: { plan?: AgentPlan }) {
  if (!plan) return <p className="tfine">No plan read for today.</p>;
  return (
    <div className="org-plan">
      <h4>Every day</h4>
      {plan.duties.length ? (
        <ul className="org-list">
          {plan.duties.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      ) : (
        <p className="tfine">No duties written in its definition.</p>
      )}
      <h4>Today, {plan.day}</h4>
      {plan.scheduled.length === 0 && plan.tasks.length === 0 && plan.to_check.length === 0 && (
        <p className="tfine">Nothing scheduled and no tasks today.</p>
      )}
      {plan.scheduled.length > 0 && (
        <ul className="org-list">
          {plan.scheduled.map((s) => (
            <li key={`${s.time}-${s.job}`}>
              <b>{s.time}</b> {s.job} <Badge tone={SLOT_TONE[s.state]}>{s.state}</Badge>
              {s.status && <span className="tfine"> · {s.status}</span>}
            </li>
          ))}
        </ul>
      )}
      {plan.tasks.length > 0 && (
        <ul className="org-list">
          {plan.tasks.map((t: PlanTask) => (
            <li key={t.id}>
              <Badge tone={STATUS_TONE[t.status]}>{STATUS_WORD[t.status]}</Badge> {t.title}
              <span className="tfine">
                {' '}
                · due {t.due}
                {!t.auto && ' · waits for you to start it'}
              </span>
            </li>
          ))}
        </ul>
      )}
      {plan.to_check.length > 0 && (
        <p className="tfine">{plan.to_check.length} finished task(s) waiting for this head&apos;s checklist.</p>
      )}
      {plan.done_today.length > 0 && <p className="tfine">{plan.done_today.length} finished today.</p>}
      {plan.overdue > 0 && <p className="tnote caveat">{plan.overdue} task(s) past their due day.</p>}
    </div>
  );
}

function Skills({ person }: { person: OrgPerson }) {
  if (person.can_do.length === 0) return <p className="tfine">Takes no tasks: it gives them.</p>;
  return (
    <ul className="org-list">
      {person.can_do.map((s) => (
        <li key={s.kind}>
          <b>{s.kind}</b> {s.what}
          {s.arg && <span className="tfine"> · needs a {s.arg}{s.choices.length ? ` (${s.choices.join(' or ')})` : ''}</span>}
          {!s.auto && <Badge tone="caveat">waits for you</Badge>}
        </li>
      ))}
    </ul>
  );
}

function Checks({ caps, who }: { caps: CapabilitiesResponse | null; who: string[] }) {
  if (!caps?.ok) return null;
  const mine = caps.checks.filter((c) => who.includes(c.who));
  if (mine.length === 0) return null;
  const bad = mine.filter((c) => !c.ok);
  return (
    <details className="org-checks">
      <summary>
        Can it do its work? {bad.length === 0 ? <Badge tone="up">{mine.length} checks pass</Badge> : <Badge tone="down">{bad.length} gap(s)</Badge>}
      </summary>
      <ul className="org-list">
        {mine.map((c) => (
          <li key={`${c.who}-${c.check}`}>
            <Badge tone={c.ok ? 'up' : 'down'}>{c.ok ? 'ok' : 'gap'}</Badge> {c.check} <span className="tfine">· {c.detail}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function NewTask({ chart, onMade }: { chart: OrgChart; onMade: () => void }) {
  const [department, setDepartment] = useState(chart.departments[0]?.id ?? '');
  const [title, setTitle] = useState('');
  const [detail, setDetail] = useState('');
  const [due, setDue] = useState('');
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const head = chart.departments.find((d) => d.id === department)?.head;
  const send = () => {
    setSending(true);
    setMessage('');
    agentsApi
      .createTask({ department, title: title.trim(), detail: detail.trim(), due })
      .then((r) => {
        if (!r.ok) return setMessage(r.error ?? 'refused');
        setTitle('');
        setDetail('');
        setMessage(`Given to the ${head?.title ?? 'head'}. It splits the task now; agents that may start do.`);
        onMade();
      })
      .catch((e: unknown) => setMessage(String(e)))
      .finally(() => setSending(false));
  };
  return (
    <form
      className="org-form"
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      <label>
        To
        <select value={department} onChange={(e) => setDepartment(e.target.value)}>
          {chart.departments.map((d) => (
            <option key={d.id} value={d.id}>
              {d.head.title}
            </option>
          ))}
        </select>
      </label>
      <label>
        Task
        <input value={title} maxLength={200} placeholder="e.g. Find papers on low-volatility stocks in India" onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label>
        Detail (optional)
        <textarea value={detail} maxLength={2000} rows={3} onChange={(e) => setDetail(e.target.value)} />
      </label>
      <label>
        Due (optional; today if empty)
        <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
      </label>
      {head && <p className="tfine">This head assigns {head.assigns}. It can only give work its agents list.</p>}
      <button type="submit" className="tbtn go" disabled={sending || title.trim().length < 3}>
        {sending ? 'Giving…' : 'Give task'}
      </button>
      {message && <p className="tfine">{message}</p>}
    </form>
  );
}

// ---------------------------------------------------------------- the tree

function Node({
  title,
  sub,
  tone,
  picked,
  counts,
  onPick,
  className = '',
}: {
  title: string;
  sub: string;
  tone?: Tone;
  picked: boolean;
  counts?: { open: number; blocked: number; ran: number; scheduled: number };
  onPick: () => void;
  className?: string;
}) {
  return (
    <button type="button" className={`org-node ${className}`} aria-pressed={picked} data-tone={tone} onClick={onPick}>
      <b>{title}</b>
      <span>{sub}</span>
      {counts && (
        <span className="org-node-counts">
          {counts.scheduled > 0 && (
            <em>
              {counts.ran}/{counts.scheduled} runs
            </em>
          )}
          {counts.open > 0 && <em>{counts.open} task(s)</em>}
          {counts.blocked > 0 && <em data-tone="down">{counts.blocked} need you</em>}
        </span>
      )}
    </button>
  );
}

export function OrgChartView() {
  const [chart, setChart] = useState<OrgChart | null>(null);
  const [tasks, setTasks] = useState<TasksResponse | null>(null);
  const [plans, setPlans] = useState<Record<string, AgentPlan>>({});
  const [caps, setCaps] = useState<CapabilitiesResponse | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [picked, setPicked] = useState<Selected>({ kind: 'ceo' });

  const read = useCallback(() => {
    Promise.all([agentsApi.org(), agentsApi.tasks(), agentsApi.plansToday(), agentsApi.capabilities()])
      .then(([o, t, p, c]) => {
        if (!o.ok) return setError(o.error ?? 'unknown error');
        setChart(o);
        setTasks(t);
        setPlans(p.ok ? p.plans : {});
        setCaps(c);
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);
  useEffect(() => {
    read();
  }, [read]);
  const busy = useMemo(() => new Set(tasks?.busy ?? []), [tasks]);
  useEffect(() => {
    // Poll while a head or a task is working, so its result appears without a click.
    if (busy.size === 0) return undefined;
    const timer = window.setInterval(read, 5000);
    return () => window.clearInterval(timer);
  }, [busy, read]);

  const act = (id: string, action: TaskAction) => {
    setNotice('');
    agentsApi
      .actOnTask(id, action)
      .then((r) => {
        if (!r.ok) setNotice(r.error ?? 'refused');
        read();
      })
      .catch((e: unknown) => setNotice(String(e)));
  };

  if (error) return <p className="tnote bad">The org chart could not be read: {error}</p>;
  if (!chart || !tasks) return <div className="tempty">Reading the org chart…</div>;
  const all = tasks.tasks;
  const counts = (name: string) => {
    const plan = plans[name];
    return {
      open: all.filter((t) => t.owner === name && ACTIVE.has(t.status) && t.status !== 'blocked').length,
      blocked: all.filter((t) => t.owner === name && t.status === 'blocked').length,
      ran: plan ? plan.scheduled.filter((s) => s.state === 'ran').length : 0,
      scheduled: plan ? plan.scheduled.length : 0,
    };
  };
  const skills = new Map(chart.departments.flatMap((d) => d.agents.flatMap((a) => a.can_do.map((k) => [`${a.name}:${k.kind}`, k.auto] as const))));
  // A task waits for you when it is blocked, passed up for you to close, or of a
  // kind the runner may not start (the lab's card tests, engineering's fixes).
  const waitsForYou = (t: AgentTask) =>
    t.status === 'blocked' ||
    (t.owner.startsWith('head_') && t.status === 'done') ||
    (t.status === 'assigned' && skills.get(`${t.owner}:${t.kind}`) === false);
  const yours = all.filter((t) => t.created_by === 'ceo' && !t.parent);
  const needsYou = all.filter(waitsForYou);
  const openCount = all.filter((t) => ACTIVE.has(t.status)).length;
  const today = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
  const doneToday = all.filter((t) => (t.status === 'done' || t.status === 'closed') && t.updated.slice(0, 10) === today).length;
  const proposed = [...chart.goals, ...chart.departments.flatMap((d) => d.goals)].some((g) => g.status === 'proposed');
  const isPicked = (name: string) => picked.kind === 'person' && picked.name === name;

  let panel: React.ReactNode = null;
  if (picked.kind === 'ceo') {
    panel = (
      <>
        <div className="org-panel-head">
          <b>{chart.ceo}, CEO</b>
          <span>You give tasks to the heads, approve what they pass up, and own the gate.</span>
        </div>
        <Goals goals={chart.goals} />
        {proposed && (
          <p className="tfine">
            Goals marked proposed were drafted for you. Approve, edit or delete them in <code>config/company.yaml</code>.
          </p>
        )}
        <h4>Give a task</h4>
        <NewTask chart={chart} onMade={read} />
        <h4>Needs you ({needsYou.length})</h4>
        <TaskList tasks={needsYou} all={[]} onAct={act} busy={busy} empty="Nothing waits for you." />
        <h4>Your tasks ({yours.length})</h4>
        <TaskList tasks={yours} all={all} onAct={act} busy={busy} empty="You have not given a task yet." />
        <h4>How a head checks work</h4>
        <ol className="org-list">
          {tasks.checklist.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ol>
        <p className="tfine">
          A task that fails is sent back at most {tasks.max_returns} times, then it is blocked. Its head then asks
          the AI (Groq) for help once: the AI reads what the agent returned and either fixes the task and puts it
          back in the queue, or writes you what it needs. Ask AI for help on a blocked task to try again. Without
          the AI, the task stays blocked here for you.
        </p>
        {caps?.ok && (
          <details className="org-checks">
            <summary>
              Can every agent do its work?{' '}
              {caps.gaps.length === 0 ? (
                <Badge tone="up">{caps.checks.length} checks pass</Badge>
              ) : (
                <Badge tone="down">{caps.gaps.length} gap(s)</Badge>
              )}
            </summary>
            {caps.gaps.length > 0 && (
              <ul className="org-list">
                {caps.gaps.map((g) => (
                  <li key={g}>{g}</li>
                ))}
              </ul>
            )}
            <h4>Who resolves what the doctor finds</h4>
            <ul className="org-list">
              {caps.doctor.map((d) => (
                <li key={d.kind}>
                  <b>{d.kind.replace('_', ' ')}</b> → {d.owner === 'ceo' ? 'you' : d.owner}
                  {d.skill && ` (${d.skill})`} <span className="tfine">· {d.how}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </>
    );
  } else if (picked.kind === 'gate') {
    const o = chart.outside.find((x) => x.id === picked.id);
    panel = (
      <div className="org-panel-head">
        <b>{o?.title}</b>
        <span>{o?.note}</span>
      </div>
    );
  } else {
    const dept = chart.departments.find((d) => d.id === picked.dept);
    const person: OrgPerson | undefined = picked.head ? dept?.head : dept?.agents.find((a) => a.name === picked.name);
    if (dept && person) {
      const mine = all.filter((t) => t.owner === person.name);
      const activeMine = mine.filter((t) => ACTIVE.has(t.status));
      const finished = mine.filter((t) => !ACTIVE.has(t.status)).slice(0, 10);
      const who = picked.head ? [person.name, ...dept.agents.map((a) => a.name)] : [person.name];
      panel = (
        <>
          <div className="org-panel-head">
            <b>
              {person.title} {!person.enabled && <Badge tone="down">off</Badge>}
              {person.uses_model && <Badge>uses a model</Badge>}
            </b>
            <span>{person.job}</span>
            <span className="tfine">
              {picked.head ? `Answers to you · runs ${dept.agents.length} agent(s)` : `Reports to the ${dept.head.title}`} ·{' '}
              {person.schedule || 'on demand'}
            </span>
          </div>
          {picked.head && (
            <>
              <p className="tfine">
                Assigns {dept.head.assigns}. Passes up {dept.head.passes_up}.
              </p>
              <Goals goals={dept.goals} />
            </>
          )}
          <TodayPlan plan={plans[person.name]} />
          {!picked.head && (
            <>
              <h4>Tasks it can be given</h4>
              <Skills person={person} />
            </>
          )}
          <h4>
            {picked.head ? 'Tasks you gave it' : 'Its tasks'} ({activeMine.length} open)
          </h4>
          <TaskList
            tasks={picked.head ? activeMine.filter((t) => !t.parent) : activeMine}
            all={all}
            onAct={act}
            busy={busy}
            empty="No open tasks."
          />
          {finished.length > 0 && (
            <details>
              <summary>Finished ({finished.length})</summary>
              <TaskList tasks={finished} all={all} onAct={act} busy={busy} empty="" />
            </details>
          )}
          {person.never.length > 0 && (
            <details>
              <summary>What it can never do</summary>
              <ul className="org-list">
                {person.never.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </details>
          )}
          <Checks caps={caps} who={who} />
        </>
      );
    }
  }

  const info: CardInfo = {
    titles: new Map(
      chart.departments.flatMap((d) => [[d.head.name, d.head.title] as const, ...d.agents.map((a) => [a.name, a.title] as const)]),
    ),
    skills: new Map(
      chart.departments.flatMap((d) =>
        [d.head, ...d.agents].flatMap((a) => a.can_do.map((k) => [`${a.name}:${k.kind}`, { what: k.what, auto: k.auto }] as const)),
      ),
    ),
    byId: new Map(all.map((t) => [t.id, t] as const)),
  };

  return (
    <CardContext.Provider value={info}>
      <div className="org">
      {chart.problems.length > 0 && <p className="tnote bad">The chart has problems: {chart.problems.join('; ')}</p>}
      <div className="org-strip">
        <span>
          <b>{openCount}</b> open task(s)
        </span>
        <span>
          <b>{needsYou.length}</b> need you
        </span>
        <span>
          <b>{doneToday}</b> finished today
        </span>
        {caps?.ok && (
          <span>
            <b>{caps.gaps.length === 0 ? 'no' : caps.gaps.length}</b> capability gap(s)
          </span>
        )}
        <button type="button" className="tbtn sm" onClick={read}>
          Refresh
        </button>
      </div>
      {notice && <p className="tnote bad">{notice}</p>}
      <div className="org-layout">
        <nav className="org-tree" aria-label="Who reports to whom">
          <div className="org-root">
            <Node
              className="org-ceo"
              title={`${chart.ceo}, CEO`}
              sub={chart.company}
              tone="brand"
              picked={picked.kind === 'ceo'}
              counts={{ open: yours.filter((t) => ACTIVE.has(t.status)).length, blocked: needsYou.length, ran: 0, scheduled: 0 }}
              onPick={() => setPicked({ kind: 'ceo' })}
            />
            {chart.outside.map((o) => (
              <Node
                key={o.id}
                className="org-outside"
                title={o.title}
                sub="outside the chart; answers only to you"
                picked={picked.kind === 'gate' && picked.id === o.id}
                onPick={() => setPicked({ kind: 'gate', id: o.id })}
              />
            ))}
          </div>
          <ul className="org-branches">
            {chart.departments.map((d) => (
              <li key={d.id} className="org-branch">
                <Node
                  className="org-headnode"
                  title={d.head.title}
                  sub={d.title}
                  tone={d.head.running ? undefined : 'caveat'}
                  picked={isPicked(d.head.name)}
                  counts={counts(d.head.name)}
                  onPick={() => setPicked({ kind: 'person', name: d.head.name, dept: d.id, head: true })}
                />
                <ul className="org-children">
                  {d.agents.map((a) => (
                    <li key={a.name}>
                      <Node
                        title={a.title}
                        sub={a.enabled ? a.duties[0] ?? a.job : 'switched off'}
                        tone={a.enabled ? undefined : 'down'}
                        picked={isPicked(a.name)}
                        counts={counts(a.name)}
                        onPick={() => setPicked({ kind: 'person', name: a.name, dept: d.id, head: false })}
                      />
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </nav>
        <aside className="org-panel ai-card">{panel}</aside>
      </div>
      </div>
    </CardContext.Provider>
  );
}
