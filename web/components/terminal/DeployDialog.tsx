'use client';

/**
 * The deploy gate.
 *
 * This is not a confirmation dialog. It is the answer to "why can this not go
 * live", listed, with each line a real check the server performed against the
 * registry, the ledger, the result store, the filesystem or the environment.
 *
 * Nothing passes the evidence check today, and that is the check working rather
 * than failing: `mandate.yaml` holds that a strategy is dead until it clears the
 * gate, no mechanism promotes a strategy to forward-testing because that stage
 * is not built (T-3311), and a screened-only strategy has no business sending
 * orders. The button is real; what it refuses is also real.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { belowPaperFloor } from '@/lib/paperFloor';
import type { DeployPreview, FleetStrategy, Preflight, RiskWhatIf } from '@/lib/api';

const rupees = (value: number) => `₹${Math.round(value).toLocaleString('en-IN')}`;

export function DeployDialog({
  strategy,
  workspace,
  onClose,
  onDeployed,
}: {
  strategy: FleetStrategy;
  workspace: string;
  onClose: () => void;
  /** Called after a paper deployment starts, e.g. to open Live & Risk. */
  onDeployed?: () => void;
}) {
  const [mode, setMode] = useState<'paper' | 'live'>('paper');
  const [report, setReport] = useState<Preflight | null>(null);
  const [error, setError] = useState('');
  const [capital, setCapital] = useState(100_000);
  const [preview, setPreview] = useState<DeployPreview | null>(null);
  // What adding this strategy would do to the risk of the book already deployed.
  const [whatIf, setWhatIf] = useState<RiskWhatIf | null>(null);
  const [starting, setStarting] = useState(false);
  const [started, setStarted] = useState('');

  // How many of the strategy's names this much money buys, at the last close.
  useEffect(() => {
    if (mode !== 'paper' || !(capital > 0)) return;
    setPreview(null);
    setWhatIf(null);
    const timer = window.setTimeout(() => {
      api
        .deployPreview(strategy.id, capital)
        .then(setPreview)
        .catch(() => setPreview(null));
      api
        .riskWhatIf(strategy.id, capital)
        .then(setWhatIf)
        .catch(() => setWhatIf(null));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [strategy.id, capital, mode]);

  const start = () => {
    setStarting(true);
    setError('');
    api
      .deploy(strategy.id, mode, capital)
      .then((answer) => {
        if (!answer.ok) setError(answer.error ?? 'could not deploy');
        else setStarted(answer.deployment?.id ?? 'started');
      })
      .catch((problem) => setError(problem instanceof Error ? problem.message : String(problem)))
      .finally(() => setStarting(false));
  };

  useEffect(() => {
    setReport(null);
    setError('');
    api
      .preflight(strategy.id, mode, workspace)
      .then(setReport)
      .catch((problem) => setError(problem instanceof Error ? problem.message : String(problem)));
  }, [strategy.id, mode, workspace]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="pal-scrim" role="dialog" aria-modal="true" aria-label="Deploy" onClick={onClose}>
      <div className="dlg" onClick={(event) => event.stopPropagation()}>
        <header className="dlg-head">
          <div>
            <div className="theyebrow">Deploy</div>
            <h2>{strategy.title}</h2>
          </div>
          <button className="ticon" type="button" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="dlg-modes">
          <button
            className="tchip"
            type="button"
            aria-pressed={mode === 'paper'}
            onClick={() => setMode('paper')}
          >
            Paper
          </button>
          <button
            className="tchip"
            type="button"
            aria-pressed={mode === 'live'}
            onClick={() => setMode('live')}
          >
            Live — real money
          </button>
        </div>

        <div className="dlg-body">
          {error && <div className="tnote bad">{error}</div>}
          {!report && !error && <div className="tempty">Checking…</div>}
          {mode === 'paper' && (
            <div className="dlg-capital">
              <label>
                <span>Capital for this strategy</span>
                <input
                  type="number"
                  min={1000}
                  step={1000}
                  value={capital}
                  onChange={(event) => setCapital(Number(event.target.value))}
                />
              </label>
              <p className="tfine">
                {preview?.ok && preview.wanted !== undefined
                  ? preview.affordable === preview.wanted
                    ? `${rupees(capital)} buys all ${preview.wanted} names it would hold today.`
                    : `${rupees(capital)} buys the top ${preview.affordable} of the ${preview.wanted} names it would hold today; the ${(preview.wanted ?? 0) - (preview.affordable ?? 0)} lowest-ranked are left out.`
                  : preview?.error
                    ? preview.error
                    : 'Checking what this buys…'}{' '}
                Paper: simulated fills at the next session&apos;s close, 5 bps worse, Indian
                costs charged. Runs after each day&apos;s data lands, and catches up missed days.
              </p>
              {whatIf?.ok && whatIf.enough_history && whatIf.var_after !== undefined && (
                <p className="tfine">
                  <b>Risk if you add it.</b>{' '}
                  {whatIf.deployments > 0
                    ? `The book's one-day 95% VaR goes from ${rupees(whatIf.var_before ?? 0)} to ${rupees(whatIf.var_after)} (${(whatIf.var_added ?? 0) >= 0 ? '+' : '−'}${rupees(Math.abs(whatIf.var_added ?? 0))}).`
                    : `Its one-day 95% VaR would be ${rupees(whatIf.var_after)}.`}{' '}
                  On its own it would be {rupees(whatIf.var_own ?? 0)}.
                  {whatIf.most_alike && whatIf.most_alike.correlation >= 0.8
                    ? ` It moves almost as one with "${whatIf.most_alike.title}" (${whatIf.most_alike.correlation.toFixed(2)}): adding it is closer to resizing that than to a new bet.`
                    : whatIf.correlation_with_book !== null && whatIf.correlation_with_book !== undefined
                      ? ` It moves ${whatIf.correlation_with_book.toFixed(2)} with the book already deployed.`
                      : ''}
                  {whatIf.gap && whatIf.gap.notional > 0 && whatIf.gap.enough
                    ? ` On a night it holds the future, a 1-in-20 gap costs ${rupees(whatIf.gap.var95_when_held)}.`
                    : ''}
                  {whatIf.gap && whatIf.gap.notional === 0 ? ' This much money does not buy one lot, so it would never trade.' : ''}{' '}
                  From today&apos;s names in equal amounts over {whatIf.history_days} days; an estimate, not a limit.
                </p>
              )}
            </div>
          )}
          {started && (
            <div className="tnote ok">
              Paper deployment started. Its first decisions use the latest close; see Live &amp;
              Risk for positions and P&amp;L.{' '}
              {onDeployed && (
                <button className="tbtn sm" type="button" onClick={onDeployed}>
                  Open Live &amp; Risk
                </button>
              )}
            </div>
          )}
          {report && (
            <>
              <ul className="checks">
                {report.checks.map((check) => (
                  <li key={check.name} data-passed={check.passed} data-advisory={!check.blocking}>
                    <span className="ck" aria-hidden="true">
                      {check.passed ? '✓' : check.blocking ? '✕' : '!'}
                    </span>
                    <div>
                      <b>{check.name}</b>
                      <p>{check.detail}</p>
                    </div>
                  </li>
                ))}
              </ul>

              {mode === 'paper' && belowPaperFloor(strategy) && (
                <div className="tnote bad">{belowPaperFloor(strategy)}</div>
              )}
              <div className="dlg-foot">
                <div className="verdict" data-ok={report.ok}>
                  {report.ok
                    ? mode === 'live'
                      ? 'All checks pass. This would trade real money.'
                      : 'Paper only. Advisory (!) items are shown, not required.'
                    : `${report.blockers} ${report.blockers === 1 ? 'condition' : 'conditions'} not met.`}
                </div>
                <button className="tbtn ghost-line" type="button" onClick={onClose}>
                  Close
                </button>
                <button
                  className="tbtn go"
                  type="button"
                  disabled={
                    !report.ok || starting || !!started || mode === 'live' || capital < 1000 || !!belowPaperFloor(strategy)
                  }
                  onClick={start}
                  title={
                    mode === 'live'
                      ? 'Live trading is not enabled yet.'
                      : belowPaperFloor(strategy)
                        ? belowPaperFloor(strategy)
                        : report.ok
                        ? 'Start paper trading with this capital.'
                        : 'Blocked by the conditions listed above. Each one is a real check, not a placeholder.'
                  }
                >
                  {mode === 'live' ? 'Go live' : 'Start paper'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
