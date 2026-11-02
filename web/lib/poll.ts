/**
 * How often a screen asks the server again (T-4373).
 *
 * The AI tab asked for agent activity every 2.5 s, and the agent strip on
 * every other page asked for activity and the inbox every 3 s, for as long
 * as an agent ran. The idea lab runs for 90 minutes, so one open window sent
 * about 3,900 requests a run, and kept sending them from a hidden tab. A
 * progress line that moves every few seconds does not need a faster answer
 * than this, and a tab nobody is looking at needs none.
 */
export type PollRates = { busyMs: number; idleMs: number };

/** The live AI tab: the run being watched. */
export const AGENTS_TAB: PollRates = { busyMs: 5_000, idleMs: 30_000 };

/** The strip on other pages: a glance, not a watch. */
export const AGENT_STRIP: PollRates = { busyMs: 15_000, idleMs: 60_000 };

/** The delay before the next ask, or null for "do not ask": the page is hidden. */
export function pollDelay(rates: PollRates, busy: boolean, hidden: boolean): number | null {
  if (hidden) return null;
  return busy ? rates.busyMs : rates.idleMs;
}
