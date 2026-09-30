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
import type { FleetStrategy, Preflight } from '@/lib/api';

export function DeployDialog({
  strategy,
  workspace,
  onClose,
}: {
  strategy: FleetStrategy;
  workspace: string;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<'paper' | 'live'>('paper');
  const [report, setReport] = useState<Preflight | null>(null);
  const [error, setError] = useState('');

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
          {report && (
            <>
              <ul className="checks">
                {report.checks.map((check) => (
                  <li key={check.name} data-passed={check.passed}>
                    <span className="ck" aria-hidden="true">
                      {check.passed ? '✓' : '✕'}
                    </span>
                    <div>
                      <b>{check.name}</b>
                      <p>{check.detail}</p>
                    </div>
                  </li>
                ))}
              </ul>

              <div className="dlg-foot">
                <div className="verdict" data-ok={report.ok}>
                  {report.ok
                    ? `All checks pass. ${mode === 'live' ? 'This would trade real money.' : 'Paper only.'}`
                    : `${report.blockers} ${report.blockers === 1 ? 'condition' : 'conditions'} not met.`}
                </div>
                <button className="tbtn ghost-line" type="button" onClick={onClose}>
                  Close
                </button>
                <button
                  className="tbtn go"
                  type="button"
                  disabled={!report.ok}
                  title={
                    report.ok
                      ? 'Arm this strategy.'
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
