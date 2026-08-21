/**
 * The terminal's shared pieces, rebuilt on the Robinhood reference
 * (docs/RESEARCH/018).
 *
 * One rule runs through all of them and is the reason this file is worth
 * reading: **the accent is spent on evidence, never on magnitude.** Robinhood
 * turns the portfolio green when the portfolio is up, which is the most
 * effective thing in their interface and the exact reflex this platform exists
 * to interrupt. Here green means the figure cleared the noise bar. A Sharpe of
 * 2.19 pulled from forty unrecorded runs renders in plain ink.
 */

const STAGE_LABEL: Record<string, string> = {
  registered: 'Screened',
  backtested: 'Backtested',
  forward_testing: 'Validated',
  live: 'Live',
  retired: 'Retired',
};

const STAGE_TITLE: Record<string, string> = {
  registered: 'Declared and screenable. No recorded trial, so no evidence.',
  backtested: 'Backtested with at least one trial recorded in the ledger.',
  forward_testing: 'Passed the gate and is being forward-tested on unseen data.',
  live: 'Trading real capital.',
  retired: 'Withdrawn. Kept because the trial it spent is permanent.',
};

export function EvidenceBadge({ stage }: { stage: string }) {
  return (
    <span className="tpill" data-stage={stage} title={STAGE_TITLE[stage] ?? ''}>
      {STAGE_LABEL[stage] ?? stage}
    </span>
  );
}

export function Tag({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <span className="ttag" title={title}>
      {children}
    </span>
  );
}

/**
 * The headline number, the bar it is measured against, and how many
 * configurations have been tried — one component, because they are one fact.
 *
 * The figure is the **most recent** run, not the best. A maximum over N
 * configurations is a biased estimate of any one of them; the latest run is a
 * measurement. The count still travels with it because how much searching
 * happened is context the number needs either way, and it sits under the figure
 * at every breakpoint, including the narrow one where the Runs column is
 * hidden.
 */
export function SharpeCell({
  sharpe,
  bar,
  runs,
}: {
  sharpe: number | null;
  bar: number;
  runs: number;
}) {
  if (sharpe === null) {
    // Never zero. Null means nobody looked; zero is a measurement meaning no
    // edge, and collapsing the two is how an untested strategy comes to look
    // like a tested failure.
    return (
      <div className="tnum">
        <span className="big none">not measured</span>
        <div className="foot tdim">{runs > 0 ? `${runs} runs, none tradeable` : 'never run'}</div>
      </div>
    );
  }

  const clears = sharpe >= bar;
  const span = Math.max(bar * 1.6, sharpe * 1.15, 0.5);
  const fill = Math.max(0, Math.min(100, (sharpe / span) * 100));
  const tick = Math.max(0, Math.min(100, (bar / span) * 100));
  const delta = sharpe - bar;

  return (
    <div className="tnum">
      <span className={`big${clears ? ' clear' : ''}`}>{sharpe.toFixed(2)}</span>
      <div className="tmeter" aria-hidden="true">
        <i className={clears ? 'clear' : ''} style={{ width: `${fill}%` }} />
        <u style={{ left: `${tick}%` }} />
      </div>
      <div className="foot">
        {runs > 1 ? `latest of ${runs} · ` : ''}
        {delta >= 0 ? '+' : '−'}
        {Math.abs(delta).toFixed(2)} {delta >= 0 ? 'over' : 'under'} bar
      </div>
    </div>
  );
}
