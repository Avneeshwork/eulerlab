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
import { money } from '@/lib/money';
import type { Constituent, Explain, FullReport } from '@/lib/api';

/** Per-instrument contribution, in the currency of the run it came from.
 *
 * This wrote ₹ unconditionally, so a US strategy's attribution showed dollar
 * figures with a rupee sign — the same defect the report header carried, in the
 * one place a reader compares instruments against each other. */
const contribution = (value: number, market: string) =>
  `${value >= 0 ? '+' : ''}${money(value, market)}`;

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
                {/* The link and the PDF are separate affordances on purpose:
                    the URL always resolves, the PDF only exists once
                    docs/RESEARCH/papers/fetch.sh has run, and offering a
                    download that 404s reads as broken provenance rather than
                    as a file nobody fetched yet. */}
                {(about.paper_url || about.paper_pdf) && (
                  <p className="paperlinks">
                    {about.paper_url && (
                      <a href={about.paper_url} target="_blank" rel="noreferrer">
                        Read the paper ↗
                      </a>
                    )}
                    {about.paper_pdf && (
                      <a href={about.paper_pdf} target="_blank" rel="noreferrer">
                        PDF ↓
                      </a>
                    )}
                  </p>
                )}
                {about.tested_on && (
                  <p>
                    <span>Tested on:</span> {about.tested_on}
                    {about.recommended_class && (
                      <span className="ttag" style={{ marginLeft: 8, textTransform: 'none' }}>
                        {about.recommended_class}
                      </span>
                    )}
                  </p>
                )}
                {about.published && (
                  <p>
                    <span>It reported:</span> {about.published}
                  </p>
                )}
                {about.recommended_class && about.recommended_class !== about.asset_class && (
                  <p className="mismatch">
                    <span>Note</span> the paper studied {about.recommended_class} and this
                    runs on {about.asset_class}. A result here is evidence about{' '}
                    {about.asset_class}, not a replication of the paper.
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

          {/* Placed directly after provenance, before "The idea": if a
              parameter has been moved off the published value, that is the
              second thing a reader needs to know, not a footnote. */}
          {about?.tuning && (
            <section className="explain-block">
              <h3>
                {!about.tuning.adopted
                  ? 'Swept, and left alone'
                  : about.tuning.changed.length > 0
                    ? 'Tuned from the paper'
                    : "Swept, and the paper's values won"}
              </h3>

              {about.tuning.adopted && about.tuning.changed.length > 0 ? (
                <>
                  <p className="tdesc" style={{ fontSize: 17 }}>
                    This strategy no longer runs on its published parameters. A recorded
                    sweep over {about.tuning.candidates} settings found a better one on{' '}
                    {about.tuning.symbol}, and that is what every backtest, paper run and
                    live signal now uses.
                  </p>
                  <table className="ttable tuned">
                    <thead>
                      <tr>
                        <th>Parameter</th>
                        <th className="r">Paper</th>
                        <th className="r">Now</th>
                      </tr>
                    </thead>
                    <tbody>
                      {about.tuning.changed.map((change) => (
                        <tr key={change.name}>
                          <td>{change.name.replace(/_/g, ' ')}</td>
                          <td className="r was">{change.paper}</td>
                          <td className="r now">{change.adopted}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {Object.keys(about.tuning.params).length > about.tuning.changed.length && (
                    <p className="tfine" style={{ marginTop: 8 }}>
                      The other swept parameters landed on the paper&rsquo;s own values and
                      are unchanged — listed as changes they would overstate what the sweep
                      found.
                    </p>
                  )}
                </>
              ) : about.tuning.adopted ? (
                <p className="tdesc" style={{ fontSize: 17 }}>
                  A recorded sweep over {about.tuning.candidates} settings ran on{' '}
                  {about.tuning.symbol}, and the paper&rsquo;s own parameters won it. Nothing
                  changed — but that is a different fact from nothing having been tried.
                  The published values are now the best of {about.tuning.candidates} tested,
                  rather than simply the ones nobody questioned.
                </p>
              ) : (
                <p className="tdesc" style={{ fontSize: 17 }}>
                  A recorded sweep over {about.tuning.candidates} settings ran on{' '}
                  {about.tuning.symbol} and {about.tuning.reason}. The published parameters
                  are still the ones in use.
                </p>
              )}

              <div className="tuned-facts">
                <div>
                  <span>Best</span>
                  <b className={about.tuning.best_pnl < 0 ? 'neg' : 'pos'}>
                    {Math.round(about.tuning.best_pnl).toLocaleString()}
                  </b>
                </div>
                <div>
                  <span>Median setting</span>
                  <b className={about.tuning.median_pnl < 0 ? 'neg' : 'pos'}>
                    {Math.round(about.tuning.median_pnl).toLocaleString()}
                  </b>
                </div>
                <div>
                  <span>Fills</span>
                  <b>{about.tuning.fills}</b>
                </div>
                <div>
                  <span>Sessions</span>
                  <b>{about.tuning.sessions}</b>
                </div>
              </div>

              <p className="tfine" style={{ marginTop: 10 }}>
                {about.tuning.caveat}
              </p>
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

          {about && about.logic.length > 0 && (
            <section className="explain-block">
              <h3>How it is implemented</h3>
              <ol className="logic">
                {about.logic.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
              {/* The steps are written once, in the declaration, and quote the
                  published values. Without this note the dialog contradicts
                  itself: "stop 1.4 → 1.0" two blocks above, "stop at 1.4 x ATR"
                  here. Stated rather than string-substituted into the steps —
                  rewriting prose by pattern match would eventually replace a
                  number that meant something else. */}
              {about.tuning && about.tuning.changed.length > 0 && (
                <p className="tfine" style={{ marginTop: 10 }}>
                  <b>These steps quote the paper&rsquo;s published values.</b> This strategy
                  now runs with{' '}
                  {about.tuning.changed
                    .map((c) => `${c.name.replace(/_/g, ' ')} ${c.adopted} (was ${c.paper})`)
                    .join(', ')}
                  , as set out above.
                </p>
              )}
              <p className="tfine" style={{ marginTop: 10 }}>
                These are the steps as coded, not a description written beside the code.
                {about.emits === 'ConditionalEntry' &&
                  " The exits are this platform's bracket rather than the paper's, which is stated in `intraday/papers.py` and means nothing here is a replication of its tables."}
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
                <Holdings title="Made the most" rows={winners} market={report?.asset_class ?? "equity"} />
                <Holdings title="Cost the most" rows={losers} market={report?.asset_class ?? "equity"} />
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

          {/* Only on the standalone dialog, which the top-bar button opens for
              exactly this. On a strategy panel it was seven paragraphs about
              the engine — identical under all 36 strategies — sitting below
              the part that is actually about the strategy. */}
          {explain && !about && (
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

function Holdings({
  title,
  rows,
  market,
}: {
  title: string;
  rows: Constituent[];
  /** The market these figures are denominated in. Passed rather than assumed:
   *  this component is where a reader compares instruments to each other, so a
   *  wrong symbol here is wrong in the one place it is most load-bearing. */
  market: string;
}) {
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
                <b>{contribution(row.contribution, market)}</b>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
