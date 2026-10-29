/**
 * The AI page: the agent control room (ADR-085), in tabs.
 *
 * One page for everything the agents do: the inbox of things waiting on the
 * operator, each agent with its switch, budget and brief, the latest market
 * brief, a box to ask the knowledge agent, the data quality grades and the
 * agents' own log. Nothing here places an order or spends a trial: approving
 * an inbox item records a decision, and registering a draft or relocking a
 * deployment are still commands the operator runs.
 */

'use client';

import { useCallback, useEffect, useState } from 'react';

import { agentsApi } from '@/lib/api';
import { DeskTab } from '@/components/terminal/DeskTab';
import type { AgentItem, AgentOutput, AgentsResponse, DatasetGrade } from '@/lib/api';

const VIEWS = [
  ['room', 'Inbox & agents'],
  ['ask', 'Ask'],
  ['research', 'Research'],
  ['desk', 'Trade desk'],
  ['brief', 'Market brief'],
  ['quality', 'Data quality'],
  ['log', 'Agent log'],
] as const;
type View = (typeof VIEWS)[number][0];

type Quality = { grades: DatasetGrade[]; held: { dataset: string; path: string; reason: string; at: string }[] };
type LogView = { verified: boolean; problem: string; entries: { seq: number; at: string; kind: string; agent: string }[] };

function when(at: string): string {
  if (!at) return '—';
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? at : d.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}

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
    <div className="tpanel" style={{ padding: 16 }}>
      <h3>Inbox ({items.length})</h3>
      <p className="tfine">
        Approving records your decision and nothing else. A draft still needs{' '}
        <code>make paper-agent-approve</code>; a rerun or a relock is still your command.
      </p>
      {error && <p className="tnote bad">{error}</p>}
      {items.length === 0 ? (
        <div className="tempty">Nothing waiting on you.</div>
      ) : (
        <table className="ttable">
          <thead>
            <tr>
              <th>Agent</th>
              <th>What</th>
              <th>Detail</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>
                  {item.agent}
                  <div className="tfine">{when(item.at)}</div>
                </td>
                <td>
                  <span className="tchip">{item.severity}</span> <b>{item.title}</b>
                  <div className="tfine">{item.kind}</div>
                </td>
                <td className="tfine" style={{ whiteSpace: 'pre-wrap', maxWidth: 520 }}>
                  {item.body || '—'}
                </td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button type="button" className="tbtn sm go" onClick={() => decide(item.id, 'approved')}>
                    Approve
                  </button>{' '}
                  <button type="button" className="tbtn sm" onClick={() => decide(item.id, 'dismissed')}>
                    Dismiss
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function BriefBox({ name, initial, label }: { name: string; initial: string; label: string }) {
  const [text, setText] = useState(initial);
  const [saved, setSaved] = useState('');
  useEffect(() => setText(initial), [initial]);
  const save = () => {
    agentsApi
      .brief(name, text)
      .then((r) => setSaved(r.ok ? 'saved' : r.error ?? 'not saved'))
      .catch((e: unknown) => setSaved(String(e)));
  };
  return (
    <div style={{ marginTop: 8 }}>
      <label className="tfine" htmlFor={`brief-${name}`}>
        {label}
      </label>
      <textarea
        id={`brief-${name}`}
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        style={{ width: '100%', font: 'inherit' }}
      />
      <button type="button" className="tbtn sm" onClick={save}>
        Save brief
      </button>{' '}
      <span className="tfine">{saved}</span>
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
    <div className="tpanel" style={{ padding: 16 }}>
      <h3>Agents</h3>
      {error && <p className="tnote bad">{error}</p>}
      <BriefBox name="all" initial={data.brief_all} label="Brief for every agent" />
      <table className="ttable" style={{ marginTop: 12 }}>
        <thead>
          <tr>
            <th>Agent</th>
            <th>Last run</th>
            <th style={{ textAlign: 'right' }}>Requests today</th>
            <th>Run</th>
          </tr>
        </thead>
        <tbody>
          {data.agents.map((a) => (
            <tr key={a.name}>
              <td style={{ maxWidth: 380 }}>
                <b>{a.title}</b> <span className="tfine">({a.name})</span>
                <div className="tfine">{a.job}</div>
                <div className="tfine">
                  {a.schedule || 'on demand'} · never: {a.never.join('; ') || '—'}
                </div>
                <label className="tfine">
                  <input type="checkbox" checked={a.enabled} onChange={(e) => toggle(a.name, e.target.checked)} />{' '}
                  {a.enabled ? 'on' : 'off'} (set by {a.switched})
                </label>
                <BriefBox name={a.name} initial={a.brief} label="Brief" />
              </td>
              <td className="tfine" style={{ maxWidth: 320 }}>
                {a.running ? (
                  <b>running…</b>
                ) : a.latest ? (
                  <>
                    <span className="tchip">{a.latest.status}</span> {when(a.latest.started)}
                    <div>{a.latest.summary}</div>
                    <div>
                      {a.latest.items} items{a.latest.model ? ` · ${a.latest.model}` : ''}
                    </div>
                  </>
                ) : (
                  'never run'
                )}
              </td>
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                {a.uses_model ? `${a.used_today} / ${a.daily_requests}` : 'no model'}
              </td>
              <td>
                <input
                  aria-label={`arguments for ${a.name}`}
                  placeholder="key=value"
                  value={args[a.name] ?? ''}
                  onChange={(e) => setArgs({ ...args, [a.name]: e.target.value })}
                  style={{ width: 140, font: 'inherit' }}
                />{' '}
                <button
                  type="button"
                  className="tbtn sm go"
                  disabled={!a.enabled || a.running}
                  onClick={() => run(a.name)}
                >
                  Run
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MarketBrief() {
  const [brief, setBrief] = useState<{ text?: string; at?: string; error?: string } | null>(null);
  useEffect(() => {
    agentsApi.marketBrief().then(setBrief).catch((e: unknown) => setBrief({ error: String(e) }));
  }, []);
  return (
    <div className="tpanel" style={{ padding: 16 }}>
      <h3>Market brief</h3>
      {!brief ? null : brief.text ? (
        <>
          <p className="tfine">{when(brief.at ?? '')}</p>
          <pre style={{ whiteSpace: 'pre-wrap', font: 'inherit' }}>{brief.text}</pre>
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
    <div className="tpanel" style={{ padding: 16 }}>
      <h3>Ask the knowledge agent</h3>
      <p className="tfine">It answers from the papers, cards, decisions and data grades on disk, and names what it read.</p>
      <textarea
        aria-label="question"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        rows={2}
        style={{ width: '100%', font: 'inherit' }}
      />
      <button type="button" className="tbtn sm go" disabled={busy} onClick={ask}>
        {busy ? 'Asking…' : 'Ask'}
      </button>
      {answer && <pre style={{ whiteSpace: 'pre-wrap', font: 'inherit', marginTop: 8 }}>{answer}</pre>}
    </div>
  );
}

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
    <div className="tpanel" style={{ padding: 16 }}>
      <h3>Data quality</h3>
      <p className="tfine">
        Every dataset graded against one contract: registered, provenance, fingerprint, sense checks,
        quarantine. Freshness is shown apart; a backtest refuses a panel below its grade.
      </p>
      {error && <p className="tnote bad">{error}</p>}
      {quality && (
        <>
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
                    {g.name}
                    {g.critical && <span className="tfine"> · critical</span>}
                    {!g.point_in_time && <span className="tfine"> · not point-in-time</span>}
                  </td>
                  <td>
                    <span className="tchip">{g.grade}</span>
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
          <p className="tfine" style={{ marginTop: 8 }}>
            Held in quarantine: {quality.held.length === 0 ? 'none' : quality.held.map((h) => `${h.path} (${h.reason})`).join('; ')}
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
    <div className="tpanel" style={{ padding: 16 }}>
      <h3>Agent log</h3>
      <p className={view.verified ? 'tfine' : 'tnote bad'}>
        {view.verified ? 'The hash chain verifies.' : `The chain does not verify: ${view.problem}`}
      </p>
      <table className="ttable">
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
    </div>
  );
}

/** Start a research or skeptic run and read what came back: drafts, Quantpedia leads, attacks. */
function Research() {
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
      .then((r) => setNote(r.ok ? `${name} started; this page refreshes every 15 seconds.` : r.error ?? 'not started'))
      .catch((e: unknown) => setNote(String(e)));
  return (
    <>
      <div className="tpanel" style={{ padding: 16 }}>
        <h3>Find and draft ideas</h3>
        <p className="tfine">
          The research agent searches arXiv and OpenAlex, reads Quantpedia&rsquo;s catalogue if synced
          (<code>make quantpedia-sync</code>), drafts cards and checks them against ideas already tried. It stops
          at drafts: nothing is registered or backtested, and no trial is spent.
        </p>
        <input
          aria-label="research topic"
          placeholder="topic, e.g. delivery percentage and next-day returns"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          style={{ width: '60%', font: 'inherit' }}
        />{' '}
        <button type="button" className="tbtn sm go" disabled={!topic.trim()} onClick={() => start('research', { topic })}>
          Research
        </button>
      </div>
      <div className="tpanel" style={{ padding: 16 }}>
        <h3>Try to break a result</h3>
        <p className="tfine">
          The skeptic reads a stored backtest and attacks it: without its best year, its best days, Indian stress
          windows, the t-statistic and twice the costs.
        </p>
        <input
          aria-label="strategy id"
          placeholder="strategy id"
          value={strategy}
          onChange={(e) => setStrategy(e.target.value)}
          style={{ width: 240, font: 'inherit' }}
        />{' '}
        <button type="button" className="tbtn sm go" disabled={!strategy.trim()} onClick={() => start('skeptic', { strategy })}>
          Attack
        </button>
      </div>
      {note && <p className="tfine">{note}</p>}
      {(['research', 'skeptic'] as const).map((name) => {
        const out = latest[name];
        if (!out) return null;
        return (
          <div key={name} className="tpanel" style={{ padding: 16 }}>
            <h3>
              Latest {name} run <span className="tchip">{out.status}</span>
            </h3>
            <p className="tfine">
              {when(out.started)} · {out.summary}
            </p>
            <table className="ttable">
              <tbody>
                {out.items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <span className="tchip">{item.kind}</span>
                    </td>
                    <td>
                      <b>{item.title}</b>
                      <div className="tfine" style={{ whiteSpace: 'pre-wrap' }}>
                        {item.body}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </>
  );
}

export function AgentsTab() {
  const [view, setView] = useState<View>('room');
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
  if (!data) return <section className="tsection" />;
  return (
    <>
      <div className="tseg" role="tablist" aria-label="AI">
        {VIEWS.map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={view === id} onClick={() => setView(id)}>
            {id === 'room' && items.length ? `${label} (${items.length})` : label}
          </button>
        ))}
      </div>
      <section className="tsection" style={{ display: 'grid', gap: 16 }}>
        {!data.log_ok && <p className="tnote bad">The agent log does not verify: {data.log_problem}</p>}
        {view === 'room' && (
          <>
            <Inbox items={items} onDone={read} />
            <Agents data={data} onChange={read} />
          </>
        )}
        {view === 'ask' && <Ask />}
        {view === 'research' && <Research />}
        {view === 'brief' && <MarketBrief />}
        {view === 'quality' && <QualityTable />}
        {view === 'log' && <Log />}
      </section>
      {view === 'desk' && <DeskTab />}
    </>
  );
}
