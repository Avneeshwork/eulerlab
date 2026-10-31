'use client';

/**
 * The agents that work for the page you are on (ADR-094).
 *
 * The AI tab put nine agents in one place, and a trader could not tell which
 * one helps with what. Each page now shows its own agents at the top: what the
 * agent does here, what it last found and when, what is waiting on you, and a
 * button to run it now. The icon moves while the agent works.
 *
 * Reads `/api/agents/activity` and `/api/agents/inbox`; writes nothing but a
 * run request. Nothing an agent does places a trade.
 */

import { useCallback, useEffect, useState } from 'react';
import { agentsApi } from '@/lib/api';
import type { AgentActivity, AgentFinding, AgentItem, MarketBrief, SkepticTarget } from '@/lib/api';
import { BriefCard } from './MarketBriefView';

const GRADE_KEY =
  'Grades: A every check passed. B passed with a warning. C one check failed, still usable. D missing or not usable. Backtests and the trade desk need C or better.';

/** Why an agent runs from the terminal and not from the page, in a trader's words. */
const CLI_WHY: Record<string, string> = {
  lab: 'It loads the whole price panel, and running it from this page would hold a second copy in the server’s memory.',
};

export type PageAgent = {
  name: string;
  /** What the agent does on this page, in a trader's words. */
  role: string;
  /** What to do with its note. */
  next: string;
  /** How to read its numbers, when they need a key. */
  key?: string;
};

/** Which agents show on which page. Engineering stays on the AI tab: it reviews code, not trades. */
export const PAGE_AGENTS: Record<string, PageAgent[]> = {
  dashboard: [
    {
      name: 'market_brief',
      role: 'Writes the pre-open brief at 08:45 and the after-close brief once the day’s data is in.',
      next: 'Read it before the open.',
    },
  ],
  strategies: [
    {
      name: 'lab',
      role: 'Backtests the research agent’s ideas inside the weekly trial allowance and sends you the survivors.',
      next: 'Approve or drop survivors in the AI inbox.',
    },
    {
      name: 'skeptic',
      role: 'Attacks a stored result before the gate sees it: a lucky year, a few lucky days, costs, Indian stress windows.',
      next: 'Pick a strategy for its full review, or check all of them and start with the worst.',
    },
    {
      name: 'portfolio',
      role: 'Suggests sizes for strategies that passed the gate.',
      next: 'Use its size, not a round number.',
    },
  ],
  live: [
    {
      name: 'operations',
      role: 'Checks every scheduled step ran on time and measures each paper book’s gap to its backtest.',
      next: 'A late step means today’s numbers may be stale.',
    },
    {
      name: 'portfolio',
      role: 'Flags a paper book that has drifted outside what its backtest showed.',
      next: 'A drifting book is a reason to reduce, not to add.',
    },
  ],
  data: [
    {
      name: 'data',
      role: 'Grades every dataset against the quality rules and says what is behind, failed or changed format.',
      next: 'Trust a backtest only on data graded C or better.',
      key: GRADE_KEY,
    },
  ],
  instruments: [
    {
      name: 'data',
      role: 'Grades the price panel and the instrument master each morning and evening.',
      next: 'A grade below C blocks the trade desk.',
      key: GRADE_KEY,
    },
  ],
  research: [
    {
      name: 'research',
      role: 'Reads papers on the week’s topic, drafts idea cards and drops repeats of ideas already tried.',
      next: 'New cards arrive Sunday morning.',
    },
    {
      name: 'knowledge',
      role: 'Answers questions about your papers, results and data, and names the source of each number.',
      next: 'Ask it in the AI tab before you trust a claim.',
    },
  ],
};

const WORD: Record<AgentActivity['state'], string> = {
  idle: 'Not run yet',
  running: 'Working',
  stopped: 'Stopped',
  ok: 'Done',
  skipped: 'Skipped',
  over_budget: 'Out of requests',
  refused: 'Refused',
  failed: 'Failed',
};

const TONE: Partial<Record<AgentActivity['state'], string>> = {
  running: 'brand',
  ok: 'up',
  failed: 'down',
  stopped: 'down',
  refused: 'down',
  over_budget: 'caveat',
  skipped: 'caveat',
};

function ago(iso: string): string {
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return '';
  const minutes = Math.round((Date.now() - at) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

/** The animated icon: an orb that spins while the agent works and breathes when it is done. */
export function AgentOrb({ state }: { state: AgentActivity['state'] }) {
  return (
    <span className="agent-orb" data-state={state} aria-hidden="true">
      <svg viewBox="0 0 32 32" width="32" height="32">
        <circle className="agent-orb-ring" cx="16" cy="16" r="14" />
        <circle className="agent-orb-core" cx="16" cy="16" r="7" />
        <path className="agent-orb-spark" d="M16 9.5l1.6 4.9 4.9 1.6-4.9 1.6-1.6 4.9-1.6-4.9-4.9-1.6 4.9-1.6z" />
      </svg>
    </span>
  );
}

const SHOWN = 3;

/** What the agent's last run found, worst first, each with what to do about it. */
function Findings({ list, total }: { list: AgentFinding[]; total: number }) {
  const [all, setAll] = useState(false);
  if (!list.length) return null;
  const shown = all ? list : list.slice(0, SHOWN);
  return (
    <div className="agent-findings">
      <ul>
        {shown.map((f, i) => (
          <li key={`${f.title}-${i}`} data-severity={f.severity}>
            <span className="agent-sev" data-severity={f.severity}>
              {f.kind === 'alert' ? 'Alert' : f.severity === 'critical' ? 'Critical' : f.severity === 'warn' ? 'Warning' : 'Note'}
            </span>
            <div>
              <b>{f.title}</b>
              {f.body &&
                (f.ref.startsWith('strategy=') ? (
                  <ul className="agent-reasons">
                    {f.body.split('; ').map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                ) : (
                  <p>{f.body}</p>
                ))}
              {f.ref && f.ref.startsWith('make ') && (
                <p className="agent-fix">
                  To fix or recheck, run <code>{f.ref}</code>
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>
      {list.length > SHOWN && (
        <button type="button" className="agent-link" onClick={() => setAll(!all)}>
          {all
            ? 'Show fewer'
            : total > list.length
              ? `Show the ${list.length} worst of ${total}`
              : `Show all ${list.length}`}
        </button>
      )}
    </div>
  );
}

function CopyCommand({ command }: { command: string }) {
  const [done, setDone] = useState(false);
  return (
    <span className="agent-cmd">
      <code>{command}</code>
      <button
        type="button"
        className="agent-link"
        onClick={() => {
          void navigator.clipboard?.writeText(command).then(() => setDone(true));
        }}
      >
        {done ? 'Copied' : 'Copy'}
      </button>
    </span>
  );
}

export default function AgentStrip({ page, onOpenAI }: { page: string; onOpenAI: () => void }) {
  const wanted = PAGE_AGENTS[page];
  const [agents, setAgents] = useState<AgentActivity[]>([]);
  const [items, setItems] = useState<AgentItem[]>([]);
  const [brief, setBrief] = useState('');
  const [briefData, setBriefData] = useState<MarketBrief | null>(null);
  const [open, setOpen] = useState(false);
  const [asked, setAsked] = useState('');
  const [problem, setProblem] = useState('');
  const [targets, setTargets] = useState<SkepticTarget[]>([]);
  const [target, setTarget] = useState('all');

  const load = useCallback(async () => {
    try {
      const [activity, inbox] = await Promise.all([agentsApi.activity(1), agentsApi.inbox()]);
      setAgents(activity.agents ?? []);
      setItems(inbox.items ?? []);
    } catch {
      setAgents([]);
    }
  }, []);

  const busy = agents.some((a) => a.state === 'running' && wanted?.some((w) => w.name === a.name));

  useEffect(() => {
    if (!wanted) return undefined;
    void load();
    // Quick while one of this page's agents works, slow otherwise.
    const timer = window.setInterval(() => void load(), busy ? 3000 : 30000);
    return () => window.clearInterval(timer);
  }, [wanted, load, busy]);

  useEffect(() => {
    if (!wanted?.some((w) => w.name === 'market_brief')) return;
    agentsApi
      .marketBrief()
      .then((r) => {
        setBrief(r.ok && r.text ? r.text.trim() : '');
        setBriefData(r.ok && r.brief ? r.brief : null);
      })
      .catch(() => {
        setBrief('');
        setBriefData(null);
      });
  }, [wanted]);

  useEffect(() => {
    if (!wanted?.some((w) => w.name === 'skeptic')) return;
    agentsApi
      .skepticTargets()
      .then((r) => setTargets(r.targets ?? []))
      .catch(() => setTargets([]));
  }, [wanted]);

  if (!wanted) return null;

  const run = async (name: string) => {
    setProblem('');
    setAsked(name);
    try {
      const result = await agentsApi.run(name, name === 'skeptic' ? { strategy: target } : {});
      if (!result.ok) setProblem(result.error ?? 'The agent did not start.');
      await load();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error));
    } finally {
      setAsked('');
    }
  };

  return (
    <section className="agent-strip" aria-label="Agents for this page">
      {wanted.map((w) => {
        const a = agents.find((x) => x.name === w.name);
        const state = a?.state ?? 'idle';
        const waiting = items.filter((i) => i.agent === w.name).length;
        const said = state === 'running' ? a?.now : a?.summary;
        return (
          <article key={w.name} className="agent-chip" data-state={state}>
            <AgentOrb state={state} />
            <div className="agent-chip-body">
              <header>
                <b>{a?.title ?? w.name}</b>
                <span className="tbadge" data-tone={TONE[state]}>
                  {WORD[state]}
                </span>
                {a?.started && state !== 'running' && <span className="tfine">{ago(a.started)}</span>}
              </header>
              <p className="agent-chip-role">{w.role}</p>
              {w.name === 'market_brief' && briefData ? (
                <BriefCard brief={briefData} onOpen={onOpenAI} />
              ) : w.name === 'market_brief' && brief ? (
                <div className="agent-brief" data-open={open}>
                  <p>{brief}</p>
                  <button type="button" className="agent-link" onClick={() => setOpen(!open)}>
                    {open ? 'Show less' : 'Read the whole brief'}
                  </button>
                </div>
              ) : (
                said && (
                  <p className="agent-chip-said">
                    <span>{state === 'running' ? 'Now' : state === 'refused' ? 'Why' : 'Found'}</span> {said}
                  </p>
                )
              )}
              {state !== 'running' && (
                <Findings
                  // The brief itself is shown above; its item would repeat it.
                  list={(a?.findings ?? []).filter((f) => !(w.name === 'market_brief' && f.kind === 'brief'))}
                  total={a?.findings_total ?? 0}
                />
              )}
              {w.key && <p className="agent-key">{w.key}</p>}
              {a?.cli_only && (
                <div className="agent-cli">
                  <p>
                    <b>Runs from your terminal, not this page.</b> {CLI_WHY[w.name] ?? ''}
                    {a.schedule ? ` It runs on its own: ${a.schedule}.` : ''} To run it now, open a terminal in
                    your EulerLab folder and type:
                  </p>
                  <CopyCommand command={`make agent NAME=${w.name}`} />
                </div>
              )}
              <footer>
                <span className="agent-next">{w.next}</span>
                {waiting > 0 && (
                  <button type="button" className="agent-link" onClick={onOpenAI}>
                    {waiting} waiting on you
                  </button>
                )}
                {w.name === 'skeptic' && (
                  <select
                    className="tinput agent-pick"
                    aria-label="Result to attack"
                    value={target}
                    onChange={(e) => setTarget(e.target.value)}
                  >
                    <option value="all">All {targets.length || ''} stored results, worst first</option>
                    {targets.map((t) => (
                      <option key={t.strategy} value={t.strategy}>
                        {t.strategy}
                      </option>
                    ))}
                  </select>
                )}
                {!a?.cli_only && (
                  <button
                    type="button"
                    className="tbtn"
                    disabled={state === 'running' || asked === w.name || a?.enabled === false}
                    onClick={() => void run(w.name)}
                  >
                    {state === 'running' ? 'Working…' : 'Run now'}
                  </button>
                )}
              </footer>
            </div>
          </article>
        );
      })}
      {problem && <p className="tnote bad">{problem}</p>}
    </section>
  );
}
