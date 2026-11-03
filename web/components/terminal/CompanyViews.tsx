/**
 * The agent company on the AI tab (ADR-123).
 *
 *   Org chart   a family tree of you, the heads and their agents, with tasks
 *               and today's plans (OrgTree.tsx, ADR-124)
 *   Calendar    a week (or one day) of scheduled agent runs from the launchd
 *               job list, each marked ran, partial, due, missed or upcoming,
 *               plus runs started by hand
 *
 * The calendar only reads: changing a launchd job stays `make schedule`.
 */

'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import { agentsApi } from '@/lib/api';
import type { AgentCalendar, CalendarRun, CalendarSlot } from '@/lib/api';

type Tone = 'brand' | 'up' | 'down' | 'caveat' | undefined;

function Badge({ tone, children }: { tone?: Tone; children: React.ReactNode }) {
  return (
    <span className="tbadge" data-tone={tone}>
      {children}
    </span>
  );
}

// ---------------------------------------------------------------- org chart

// The org chart is a family tree with tasks and today's plans (ADR-124).
export { OrgChartView } from './OrgTree';

// ---------------------------------------------------------------- calendar

const SLOT_TONE: Record<CalendarSlot['state'], Tone> = {
  ran: 'up',
  partial: 'caveat',
  due: 'brand',
  missed: 'down',
  upcoming: undefined,
  feed: undefined,
};
const SLOT_WORD: Record<CalendarSlot['state'], string> = {
  ran: 'ran',
  partial: 'some ran',
  due: 'due',
  missed: 'missed',
  upcoming: 'upcoming',
  feed: 'data job',
};
const RUN_TONE: Record<string, Tone> = { ok: 'up', skipped: undefined, over_budget: 'caveat', refused: 'caveat', failed: 'down' };

function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}
function shift(day: string, days: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return isoDay(d);
}
function label(day: string): string {
  const d = new Date(`${day}T00:00:00Z`);
  return d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
}

/** A slot as one row shows it: in a department row only that department's agents. */
function slotFor(slot: CalendarSlot, row: string): CalendarSlot {
  if (row === 'feeds') return slot;
  return { ...slot, agents: slot.agents.filter((a) => a.department === row) };
}

function worstRun(slot: CalendarSlot): Tone {
  const bad = slot.agents.find((a) => a.status && a.status !== 'ok' && a.status !== 'skipped');
  return bad ? RUN_TONE[bad.status] : undefined;
}

function SlotChip({ slot, onPick, picked }: { slot: CalendarSlot; onPick: () => void; picked: boolean }) {
  const tone = slot.state === 'ran' ? worstRun(slot) ?? 'up' : SLOT_TONE[slot.state];
  return (
    <button type="button" className="cal-chip" data-tone={tone} aria-pressed={picked} onClick={onPick}>
      <b>{slot.time}</b> {slot.job}
      <span>{slot.agents.length > 0 ? slot.agents.map((a) => a.name).join(', ') : SLOT_WORD[slot.state]}</span>
    </button>
  );
}

function RunChip({ run }: { run: CalendarRun }) {
  return (
    <span className="cal-chip cal-adhoc" data-tone={RUN_TONE[run.status]} title={run.summary}>
      <b>{run.time}</b> {run.agent}
      <span>run by hand or by another job</span>
    </span>
  );
}

function SlotDetail({ slot, runs }: { slot: CalendarSlot; runs: CalendarRun[] }) {
  const byId = new Map(runs.map((r) => [r.run_id, r]));
  return (
    <div className="tpanel cal-detail">
      <h3>
        {label(slot.day)} {slot.time} IST · {slot.job}{' '}
        <Badge tone={SLOT_TONE[slot.state]}>{SLOT_WORD[slot.state]}</Badge>
      </h3>
      <p className="tfine">{slot.what}</p>
      {slot.agents.length === 0 ? (
        <p className="tfine">A data job with no agent; its result is on the Data page, not here.</p>
      ) : (
        <table className="ttable">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Result</th>
              <th>What it said</th>
            </tr>
          </thead>
          <tbody>
            {slot.agents.map((a) => {
              const run = byId.get(a.run_id);
              return (
                <tr key={a.name}>
                  <td>{a.name}</td>
                  <td>
                    {run ? (
                      <Badge tone={RUN_TONE[run.status]}>
                        {run.status} at {run.time}
                      </Badge>
                    ) : (
                      <span className="tfine">{slot.state === 'upcoming' ? 'not yet' : 'no run'}</span>
                    )}
                  </td>
                  <td className="tfine">{run?.summary ?? ''}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function CalendarView() {
  const [start, setStart] = useState('');
  const [span, setSpan] = useState<7 | 1>(7);
  const [cal, setCal] = useState<AgentCalendar | null>(null);
  const [error, setError] = useState('');
  const [picked, setPicked] = useState('');

  const read = useCallback(() => {
    agentsApi
      .calendar(start, span)
      .then((r) => {
        if (r.ok) {
          setCal(r);
          setError('');
        } else setError(r.error ?? 'unknown error');
      })
      .catch((e: unknown) => setError(String(e)));
  }, [start, span]);
  useEffect(() => {
    read();
    const timer = window.setInterval(read, 60000);
    return () => window.clearInterval(timer);
  }, [read]);

  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const s of cal?.slots ?? []) out[s.state] = (out[s.state] ?? 0) + 1;
    return out;
  }, [cal]);

  if (error) return <p className="tnote bad">The calendar could not be read: {error}</p>;
  if (!cal) return <div className="tempty">Reading the calendar…</div>;

  const step = span;
  const pickedSlot = cal.slots.find((s) => `${s.day} ${s.time} ${s.job}` === picked);
  const inRow = (row: string, day: string) =>
    cal.slots
      .filter((s) => s.day === day && (row === 'feeds' ? s.agents.length === 0 : s.departments.includes(row)))
      .map((s) => slotFor(s, row));
  const adhoc = (row: string, day: string) =>
    row === 'feeds' ? [] : cal.runs.filter((r) => !r.scheduled && r.day === day && r.department === row);

  return (
    <div className="cal">
      <div className="cal-bar">
        <div className="tseg" role="tablist" aria-label="Range">
          <button type="button" role="tab" aria-selected={span === 7} onClick={() => setSpan(7)}>
            Week
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={span === 1}
            onClick={() => {
              setSpan(1);
              setStart(cal.today);
            }}
          >
            Day
          </button>
        </div>
        <button type="button" className="tbtn" onClick={() => setStart(shift(cal.start, -step))}>
          ← Earlier
        </button>
        <button type="button" className="tbtn" onClick={() => setStart('')}>
          This week
        </button>
        <button type="button" className="tbtn" onClick={() => setStart(shift(cal.start, step))}>
          Later →
        </button>
        <span className="tfine">
          {label(cal.days[0])}
          {cal.days.length > 1 ? ` to ${label(cal.days[cal.days.length - 1])}` : ''} · IST · now {cal.now} ·{' '}
          {counts.ran ?? 0} ran, {counts.partial ?? 0} partly, {counts.missed ?? 0} missed, {counts.upcoming ?? 0}{' '}
          to come
        </span>
      </div>
      <div className="cal-scroll">
        <table className="cal-grid" style={{ ['--cal-days' as string]: cal.days.length }}>
          <thead>
            <tr>
              <th />
              {cal.days.map((d) => (
                <th key={d} data-today={d === cal.today}>
                  <button
                    type="button"
                    className="cal-day"
                    onClick={() => {
                      setSpan(1);
                      setStart(d);
                    }}
                  >
                    {label(d)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cal.rows.map((row) => (
              <tr key={row.id}>
                <th scope="row">{row.title}</th>
                {cal.days.map((d) => (
                  <td key={d} data-today={d === cal.today}>
                    {inRow(row.id, d).map((s) => {
                      const key = `${s.day} ${s.time} ${s.job}`;
                      return (
                        <SlotChip
                          key={key}
                          slot={s}
                          picked={picked === key}
                          onPick={() => setPicked(picked === key ? '' : key)}
                        />
                      );
                    })}
                    {adhoc(row.id, d).map((r) => (
                      <RunChip key={r.run_id} run={r} />
                    ))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pickedSlot && <SlotDetail slot={pickedSlot} runs={cal.runs} />}
      <p className="tfine">
        Read from the launchd job list and each agent&apos;s saved runs. A run counts for a slot until the
        agent&apos;s next slot that day, because launchd runs a job on wake if the Mac slept through it. A
        slot with no run is due for three hours, then missed. To change a schedule, use <code>make schedule</code>.
      </p>
    </div>
  );
}
