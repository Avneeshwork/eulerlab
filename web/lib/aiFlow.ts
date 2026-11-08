/**
 * Pure helpers for the AI tab (ADR-151): which view an old link opens, which
 * results a filter shows, and what ran today. Kept apart from the component so
 * `npm test` can pin them.
 */

export type AiView = 'overview' | 'results' | 'team';
export type TeamView = 'cards' | 'org' | 'schedule' | 'health';
export type ResultFilter = 'research' | 'verdicts' | 'checks' | 'brief' | 'all';

/**
 * The AI tab had ten views; links and bookmarks still name them
 * (`#agents/inbox`, the market brief card's `#agents/brief`). Each old name
 * opens the view that now holds it.
 */
export function openView(name: string): { view: AiView; team?: TeamView; filter?: ResultFilter } {
  switch (name) {
    case 'overview':
    case 'live':
    case 'inbox':
      return { view: 'overview' };
    case 'results':
    case 'research-results':
      return { view: 'results' };
    case 'brief':
      return { view: 'results', filter: 'brief' };
    // Questions moved to the floating assistant; starting a run is on Agents.
    case 'ask':
    case 'research':
    case 'team':
    case 'agents':
      return { view: 'team', team: 'cards' };
    case 'org':
      return { view: 'team', team: 'org' };
    case 'calendar':
      return { view: 'team', team: 'schedule' };
    case 'quality':
    case 'log':
      return { view: 'team', team: 'health' };
    default:
      return { view: 'overview' };
  }
}

type Filterable = { kind: string; pipeline: boolean };

export function filterResults<T extends Filterable>(results: T[], filter: ResultFilter): T[] {
  switch (filter) {
    case 'research':
      return results.filter((r) => r.pipeline);
    case 'verdicts':
      return results.filter((r) => r.kind === 'verdict' || r.kind === 'paper');
    case 'checks':
      return results.filter((r) => !r.pipeline && r.kind !== 'brief');
    case 'brief':
      return results.filter((r) => r.kind === 'brief');
    default:
      return results;
  }
}

/** The IST calendar day of an ISO time, `YYYY-MM-DD`; empty for a bad time. */
export function istDay(at: string): string {
  const t = new Date(at).getTime();
  if (!at || Number.isNaN(t)) return '';
  return new Date(t + 330 * 60_000).toISOString().slice(0, 10);
}

type Run = { state: string; started: string };

/** Agents working now first, then those that ran today (IST), newest first. */
export function todaysRuns<T extends Run>(agents: T[], now: number): T[] {
  const today = istDay(new Date(now).toISOString());
  return agents
    .filter((a) => a.state === 'running' || (a.started && istDay(a.started) === today))
    .sort((a, b) => Number(b.state === 'running') - Number(a.state === 'running') || b.started.localeCompare(a.started));
}

/** "12 s ago", "4 min ago", "3 h ago", "2 d ago". */
export function ago(at: string, now: number): string {
  const t = new Date(at).getTime();
  if (!at || Number.isNaN(t)) return '';
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
