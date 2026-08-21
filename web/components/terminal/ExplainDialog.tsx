'use client';

/**
 * The (i) button.
 *
 * Two questions it answers: what does a backtest here actually do, and what is
 * this particular strategy. Both come from the server rather than being written
 * into the page, because a UI that explains a procedure the engine does not
 * perform is worse than no explanation — it is a confident description of the
 * wrong thing. The starting cash and rebalance cadence shown are the values the
 * batch runner uses, read from the same constants.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Explain } from '@/lib/api';

export function ExplainDialog({
  strategy,
  onClose,
}: {
  strategy: string;
  onClose: () => void;
}) {
  const [explain, setExplain] = useState<Explain | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .explain(strategy)
      .then(setExplain)
      .catch((problem) => setError(problem instanceof Error ? problem.message : String(problem)));
  }, [strategy]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const about = explain?.strategy;

  return (
    <div className="pal-scrim" role="dialog" aria-modal="true" aria-label="What this means" onClick={onClose}>
      <div className="dlg wide" onClick={(event) => event.stopPropagation()}>
        <header className="dlg-head">
          <div>
            <div className="theyebrow">What this means</div>
            <h2>{about ? about.title : 'How a backtest works here'}</h2>
          </div>
          <button className="ticon" type="button" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="dlg-body">
          {error && <div className="tnote bad">{error}</div>}
          {!explain && !error && <div className="tempty">Reading…</div>}

          {about && (
            <section className="explain-block">
              <h3>What it does</h3>
              <p className="tdesc" style={{ fontSize: 16 }}>
                {about.summary}
              </p>
              <p className="tdesc" style={{ fontSize: 16, marginTop: 10 }}>
                {about.how_it_decides}
              </p>
              <div className="tfacts" style={{ marginTop: 16 }}>
                <div className="tfact">
                  <span>Kind</span>
                  <b>{about.kind}</b>
                </div>
                <div className="tfact">
                  <span>Shape</span>
                  <b>{about.shape}</b>
                </div>
                <div className="tfact">
                  <span>Asset class</span>
                  <b>{about.asset_class}</b>
                </div>
                <div className="tfact">
                  <span>Timeframe</span>
                  <b>{about.timeframe}</b>
                </div>
                <div className="tfact">
                  <span>Emits</span>
                  <b>{about.emits}</b>
                </div>
                <div className="tfact">
                  <span>Lookback</span>
                  <b>{about.lookback}d</b>
                </div>
              </div>
              {!about.is_strategy_subclass && (
                <div className="tnote bad" style={{ marginTop: 16 }}>
                  <span className="mk">▲</span>
                  <div>
                    This cannot run through the daily engine at all. Its shape — an
                    intraday entry with a bracket exit — cannot be expressed as target
                    weights over a daily panel (ADR-037), and running it there would
                    produce a number for something that never happened.
                  </div>
                </div>
              )}
            </section>
          )}

          {about && (
            <section className="explain-block">
              <h3>What has been run here</h3>
              <div className="tfacts">
                <div className="tfact">
                  <span>Latest Sharpe</span>
                  <b className={about.clears_bar ? '' : 'dim'}>
                    {about.latest_sharpe === null ? 'not measured' : about.latest_sharpe.toFixed(2)}
                  </b>
                </div>
                <div className="tfact">
                  <span>Best of them</span>
                  <b className="dim">
                    {about.best_sharpe === null ? '—' : about.best_sharpe.toFixed(2)}
                  </b>
                </div>
                <div className="tfact">
                  <span>Noise bar</span>
                  <b>{about.bar.toFixed(2)}</b>
                </div>
                <div className="tfact">
                  <span>Configurations tried</span>
                  <b>{about.runs_here}</b>
                </div>
                <div className="tfact">
                  <span>Window</span>
                  <b>{about.best_window_days ? `${about.best_window_days}d` : '—'}</b>
                </div>
                <div className="tfact">
                  <span>Universe</span>
                  <b>{about.best_universe || '—'}</b>
                </div>
              </div>
              <p className="tfine" style={{ marginTop: 12 }}>
                {about.best_period_note}{' '}
                {about.runs_here > 1 &&
                  `${about.runs_here} configurations have been tried. The headline is the most recent of them, not the best — a maximum over several attempts is the score of the luckiest draw rather than of the strategy.`}
              </p>
              <p className="tfine" style={{ marginTop: 10 }}>
                A lookback of {about.lookback} days means any backtest window shorter than
                that will hold nothing. The run refuses rather than reporting a Sharpe of
                zero, because zero is a measurement and this would be an absence. The
                window you pick is also not the period traded: the first quarter of it, up
                to 253 days, is warmup.
              </p>
            </section>
          )}

          {explain && (
            <section className="explain-block">
              <h3>What a backtest does</h3>
              {explain.procedure.map((step) => (
                <div className="explain-step" key={step.title}>
                  <b>{step.title}</b>
                  <p>{step.body}</p>
                </div>
              ))}
            </section>
          )}

          {explain && (
            <section className="explain-block">
              <h3>Where this can run, and what data exists</h3>
              <table className="ttable">
                <thead>
                  <tr>
                    <th>Asset class</th>
                    <th>Timeframe</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {explain.asset_classes.map((cell) => (
                    <tr key={`${cell.asset_class}-${cell.timeframe}`}>
                      <td>
                        <b>{cell.asset_class}</b>
                      </td>
                      <td>
                        <span className="ttag">{cell.timeframe}</span>
                      </td>
                      <td>
                        <span className="tpill" data-stage={cell.supported ? 'live' : 'retired'}>
                          {cell.supported ? 'ready' : 'no data'}
                        </span>
                        <p className="tfine" style={{ margin: '4px 0 0' }}>
                          {cell.detail}
                        </p>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
