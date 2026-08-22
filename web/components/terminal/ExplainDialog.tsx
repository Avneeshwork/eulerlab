'use client';

/**
 * The (i) button: what this strategy is, in terms someone can act on.
 *
 * Four things, in the order a person actually needs them — what the rule is,
 * the rule run once so the mechanic is visible, what it really held last time,
 * and what its number means against the bar. The procedure of a backtest comes
 * last, because it is the same for every strategy and is not what the reader
 * clicked for.
 *
 * Everything factual comes from the server: the rule's parameters are read off
 * the built strategy and the holdings come from the stored report of a real
 * run. The only invented numbers are in the worked example, which is labelled
 * as an illustration wherever it appears — a diagram of a rule is not evidence,
 * and must never be mistaken for it.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Constituent, Explain, FullReport } from '@/lib/api';

const money = (value: number) =>
  `${value < 0 ? '−' : '+'}₹${Math.abs(value).toLocaleString('en-IN', {
    maximumFractionDigits: 0,
  })}`;

export function ExplainDialog({ strategy, onClose }: { strategy: string; onClose: () => void }) {
  const [explain, setExplain] = useState<Explain | null>(null);
  const [report, setReport] = useState<FullReport | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .explain(strategy)
      .then(setExplain)
      .catch((problem) => setError(problem instanceof Error ? problem.message : String(problem)));
  }, [strategy]);

  useEffect(() => {
    if (!strategy) return;
    let live = true;
    api
      .report(strategy)
      .then((response) => live && setReport(response.report ?? null))
      .catch(() => live && setReport(null));
    return () => {
      live = false;
    };
  }, [strategy]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const about = explain?.strategy;
  const example = about?.example;
  const winners = (report?.constituents ?? []).filter((c) => c.contribution > 0).slice(0, 3);
  const losers = [...(report?.constituents ?? [])]
    .filter((c) => c.contribution < 0)
    .slice(-3)
    .reverse();

  return (
    <div className="pal-scrim" role="dialog" aria-modal="true" aria-label="What this means" onClick={onClose}>
      <div className="dlg wide tall" onClick={(event) => event.stopPropagation()}>
        <header className="dlg-head">
          <div>
            <div className="theyebrow">{about ? 'Strategy' : 'How a backtest works here'}</div>
            <h2>{about ? about.title : 'How a backtest works here'}</h2>
            {about && (
              <div className="tfine" style={{ marginTop: 4 }}>
                {about.kind} · {about.asset_class} · {about.timeframe} · needs {about.lookback} days
                of history
              </div>
            )}
          </div>
          <button className="ticon" type="button" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="dlg-body">
          {error && <div className="tnote bad">{error}</div>}
          {!explain && !error && <div className="tempty">Reading…</div>}

          {about?.source && (
            <section className="explain-block">
              <h3>Where this comes from</h3>
              <div className="paper">
                <b>{about.source}</b>
                {about.published && (
                  <p>
                    <span>The paper reported:</span> {about.published}
                  </p>
                )}
                <p className="tfine" style={{ marginTop: 8 }}>
                  This is not a strategy someone here invented and then measured. It was
                  published first, and what it scored in its own paper is stated above so
                  a result on our data can never be read without the prior it is arguing
                  against — which matters most when that prior is a published failure.
                </p>
              </div>
            </section>
          )}

          {about && (
            <section className="explain-block">
              <h3>The idea</h3>
              <p className="tdesc" style={{ fontSize: 17 }}>
                {about.summary}
              </p>
              <p className="tdesc" style={{ fontSize: 17, marginTop: 10 }}>
                {about.how_it_decides}
              </p>
            </section>
          )}

          {example && (
            <section className="explain-block">
              <h3>The rule, run once</h3>
              <p className="tfine" style={{ marginBottom: 12 }}>{example.headline}</p>
              <table className="ttable example">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th className="r">Score</th>
                    <th className="r">Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {example.rows.map((row, index) => (
                    <tr key={row.symbol} data-held={row.held} data-cut={index === example.held_count}>
                      <td>
                        <b>{row.symbol}</b>
                      </td>
                      <td className="r">{row.score > 0 ? '+' : ''}{(row.score * 100).toFixed(0)}%</td>
                      <td className="r">
                        {row.held ? (
                          <b>{example.weight_pct}%</b>
                        ) : (
                          <span className="tdim">nothing</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="tfine" style={{ marginTop: 12 }}>{example.footer}</p>
              <p className="tfine" style={{ marginTop: 8, fontStyle: 'italic' }}>
                {example.real_note}
              </p>
            </section>
          )}

          {report && winners.length > 0 && (
            <section className="explain-block">
              <h3>What it actually held</h3>
              <p className="tfine" style={{ marginBottom: 12 }}>
                From its most recent run: {report.universe}
                {report.instruments.length > 0 && ` (${report.instruments.length} chosen)`}, tier{' '}
                {report.tier}, {report.period[0]} to {report.period[1]}. These are real
                positions, not an illustration.
              </p>
              <div className="tgrid">
                <Holdings title="Made the most" rows={winners} />
                <Holdings title="Cost the most" rows={losers} />
              </div>
            </section>
          )}

          {about && (
            <section className="explain-block">
              <h3>What its number means</h3>
              <div className="tfacts">
                <div className="tfact">
                  <span>Latest Sharpe</span>
                  <b className={about.clears_bar ? '' : 'dim'}>
                    {about.latest_sharpe === null ? 'not measured' : about.latest_sharpe.toFixed(2)}
                  </b>
                </div>
                <div className="tfact">
                  <span>Has to beat</span>
                  <b>{about.bar.toFixed(2)}</b>
                </div>
                <div className="tfact">
                  <span>Best ever here</span>
                  <b className="dim">
                    {about.best_sharpe === null ? '—' : about.best_sharpe.toFixed(2)}
                  </b>
                </div>
                <div className="tfact">
                  <span>Configurations tried</span>
                  <b>{about.runs_here}</b>
                </div>
              </div>
              <p className="tfine" style={{ marginTop: 12 }}>
                A Sharpe is return divided by how much the return bounced around, so bigger
                is steadier rather than simply larger.{' '}
                {about.latest_sharpe === null
                  ? 'This one has never been measured here.'
                  : about.clears_bar
                    ? `${about.latest_sharpe.toFixed(2)} clears the ${about.bar.toFixed(2)} bar.`
                    : `${about.latest_sharpe.toFixed(2)} is below the ${about.bar.toFixed(2)} bar, which means it is not distinguishable from luck.`}{' '}
                The bar is not zero: it is the Sharpe the luckiest worthless strategy would be
                expected to reach given how many things have been tried here, so it rises as
                you search.
              </p>
              <p className="tfine" style={{ marginTop: 8 }}>
                {about.best_period_note}{' '}
                {about.runs_here > 1 &&
                  'The headline is the most recent of those, not the best — a maximum over several attempts is the score of the luckiest draw rather than of the strategy.'}
              </p>
            </section>
          )}

          {explain && (
            <section className="explain-block">
              <h3>How a backtest runs here</h3>
              {explain.procedure.map((step) => (
                <div className="explain-step" key={step.title}>
                  <b>{step.title}</b>
                  <p>{step.body}</p>
                </div>
              ))}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function Holdings({ title, rows }: { title: string; rows: Constituent[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="tpanel" style={{ padding: 16 }}>
      <h3>{title}</h3>
      <table className="ttable">
        <tbody>
          {rows.map((row) => (
            <tr key={row.symbol}>
              <td>
                <b>{row.symbol}</b>
                <div className="tfine">{row.fills} fills · last {row.last_day}</div>
              </td>
              <td className={`r${row.contribution < 0 ? ' neg' : ''}`}>
                <b>{money(row.contribution)}</b>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
