/**
 * What a running agent's card says it is doing, and since when (T-4374).
 *
 * The card printed the newest step as "Now" with the *run's* start beside it,
 * "started 57 min ago", and listed the same step again under it, "2 min ago".
 * Read together it said one card had been under test for 57 minutes and was
 * then tested again. It was one step: the lab began it 2 minutes earlier, in
 * a run that began 57 minutes earlier. Now the step carries its own time, the
 * run's start is labelled as the run's, and the list below holds only the
 * steps before it.
 */
export type Step = { at: string; kind: string; text: string };

export type NowLine = {
  /** The newest step's text, or '' when the run has reported none. */
  text: string;
  /** When that step began, or '' when there is none. */
  since: string;
  /** The earlier steps, oldest first: the newest is the line above, not repeated. */
  before: Step[];
};

export function nowLine(steps: Step[], running: boolean): NowLine {
  if (!running || steps.length === 0) return { text: '', since: '', before: steps };
  const last = steps[steps.length - 1];
  return { text: last.text, since: last.at, before: steps.slice(0, -1) };
}
