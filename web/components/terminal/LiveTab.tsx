'use client';

/**
 * Live.
 *
 * There is nothing live, and this screen says so with the specific reason
 * rather than showing an empty table. The reason is structural: stage is
 * derived from the trial ledger, no mechanism promotes a strategy to
 * forward-testing because that stage is not built (T-3311), and `mandate.yaml`
 * holds that a strategy is dead until it clears the gate.
 *
 * The preflight for each strategy is run for real against the server, so the
 * list below is a live report on this machine — not a description of what
 * would happen somewhere else.
 */

import { Info } from '@/components/terminal/ui';
import { useEffect, useState } from 'react';
import { LiveMoney } from '@/components/terminal/LiveMoney';
import { PaperDeployments } from '@/components/terminal/PaperDeployments';
import { api } from '@/lib/api';
import type { FleetStrategy, Preflight } from '@/lib/api';

export function LiveTab({
  fleet,
  workspace,
  onDeploy,
  onReport,
  onStrategyReport,
}: {
  fleet: FleetStrategy[];
  workspace: string;
  onDeploy: (strategy: FleetStrategy) => void;
  onReport?: (deploymentId: string) => void;
  /** Open a strategy's backtest report. */
  onStrategyReport?: (strategyId: string) => void;
}) {
  const [reports, setReports] = useState<Record<string, Preflight>>({});
  const live = fleet.filter((s) => s.stage === 'live');
  const forward = fleet.filter(
    (s) => s.stage === 'forward_testing' || s.stage === 'paper_evaluation'
  );
  const [showAll, setShowAll] = useState(false);
  // A row is real when it has a stored backtest report (the report's period is
  // set) and paper trading can run it. The rest are hidden until they do: a
  // strategy waiting on its rebacktest shows up by itself once its report lands.
  const hasReport = (s: FleetStrategy) => !!s.table?.period?.[0];
  // The Sharpe at fills an order could get when the server has it (ADR-205),
  // else the stored one. TODO(T-4645): use `headlineSharpe` from lib/api once
  // agent-realistic-sharpe is merged.
  const sharpeOf = (s: FleetStrategy) =>
    (s as FleetStrategy & { realistic?: { sharpe: number } | null }).realistic?.sharpe ?? s.sharpe;
  const bySharpe = (a: FleetStrategy, b: FleetStrategy) => (sharpeOf(b) ?? -99) - (sharpeOf(a) ?? -99);
  // Passed the gate (PROMOTE or PAPER, ADR-141) and not yet paper-traded.
  const gatedAll = fleet
    .filter((s) => s.stage === 'promoted' || s.stage === 'paper_candidate')
    .sort(bySharpe);
  const ready = gatedAll.filter((s) => hasReport(s) && !s.deploy_blocker);
  const noReport = gatedAll.filter((s) => !hasReport(s)).length;
  const blocked = gatedAll.filter((s) => hasReport(s) && s.deploy_blocker).length;
  const TOP = 15;
  const short = (text: string) => (text.length > 80 ? `${text.slice(0, 79)}…` : text);
  const yearly = (v: number | null | undefined) =>
    v === null || v === undefined ? '—' : `${v < 0 ? '−' : '+'}${Math.abs(v * 100).toFixed(1)}%`;
  const gated = showAll ? gatedAll : ready.slice(0, TOP);
  const candidates = fleet.filter((s) => s.clears_bar && s.runnable && hasReport(s));

  useEffect(() => {
    let alive = true;
    Promise.all(
      candidates.map((strategy) =>
        api
          .preflight(strategy.id, 'live', workspace)
          .then((report) => [strategy.id, report] as const)
          .catch(() => null)
      )
    ).then((pairs) => {
      if (!alive) return;
      setReports(Object.fromEntries(pairs.filter((p): p is readonly [string, Preflight] => !!p)));
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fleet, workspace]);

  return (
    <>
      <LiveMoney onReport={onStrategyReport} />
      <PaperDeployments fleet={fleet} onReport={onReport} onBacktest={onStrategyReport} />
      <section className="thero">
        <div>
          <div className="theyebrow">Trading now</div>
          <div className="thnum">
            <b>{live.length}</b>
            <span className="unit">
              live · {forward.length} forward-testing
              <Info>
                Nothing can reach either stage yet, and that is the gate working rather than
                failing. Stage is derived from the trial ledger; the forward-test stage is not
                built (T-3311); and a strategy that has only been screened has no evidence
                behind it, so it has no business sending orders.
              </Info>
            </span>
          </div>
        </div>
        <div className="thstats">
          <div className="thstat">
            <span>Clearing the bar</span>
            <b className={candidates.length ? 'on' : ''}>{candidates.length}</b>
          </div>
        </div>
      </section>

      <div className="tpanel">
        <h3>
          Passed the gate: start a paper book{' '}
          <span className="tfine">
            {ready.length} ready{ready.length > TOP && !showAll ? `, best ${TOP} shown` : ''}
            {noReport + blocked > 0 && ` · hidden: ${noReport} without a report, ${blocked} paper can't run`}
          </span>
        </h3>
        {gated.length === 0 ? (
          <div className="tempty">Nothing is waiting.</div>
        ) : (
          <table className="ttable">
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Verdict</th>
                <th className="r">Sharpe</th>
                <th className="r">Per year</th>
                <th className="r">Trades</th>
                <th>Tested</th>
                <th>Bars</th>
                <th className="r" />
              </tr>
            </thead>
            <tbody>
              {gated.map((strategy) => (
                <tr key={strategy.id}>
                  <td title={strategy.summary}>
                    {hasReport(strategy) && onStrategyReport ? (
                      <button className="paper-bt" type="button" onClick={() => onStrategyReport(strategy.id)}>
                        <b>{short(strategy.title)}</b>
                      </button>
                    ) : (
                      <b>{short(strategy.title)}</b>
                    )}
                  </td>
                  <td title={strategy.gate_verdict === 'PAPER' ? 'paper only, never live' : 'paper, then live'}>
                    {strategy.gate_verdict || '—'}
                  </td>
                  <td className="r">{sharpeOf(strategy)?.toFixed(2) ?? '—'}</td>
                  <td className="r">{yearly(strategy.table?.annual_return)}</td>
                  <td className="r">{strategy.table?.trades?.toLocaleString('en-IN') ?? '—'}</td>
                  <td className="tfine">
                    {strategy.table?.period?.[0]
                      ? `${strategy.table.period[0].slice(0, 4)}–${(strategy.table.period[1] ?? '').slice(0, 4)}`
                      : '—'}
                  </td>
                  <td className="tfine">{strategy.timeframe === '1m' ? 'minute' : 'daily'}</td>
                  <td className="r">
                    {!hasReport(strategy) ? (
                      <span className="tfine">no report yet</span>
                    ) : strategy.deploy_blocker ? (
                      <span className="tfine" title={strategy.deploy_blocker}>
                        blocked
                      </span>
                    ) : (
                      <span className="tbtn-pair">
                        {onStrategyReport && (
                          <button className="tbtn sm" type="button" onClick={() => onStrategyReport(strategy.id)}>
                            Report
                          </button>
                        )}
                        <button className="tbtn sm" type="button" onClick={() => onDeploy(strategy)}>
                          Paper trade
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {gatedAll.length > gated.length || showAll ? (
          <button className="tbtn sm ghost-line" type="button" onClick={() => setShowAll((v) => !v)}>
            {showAll ? `Show the best ${TOP} ready` : `Show all ${gatedAll.length}`}
          </button>
        ) : null}
      </div>

      <div className="tpanel">
        <h3>Closest to deployable</h3>
        {candidates.length === 0 ? (
          <div className="tempty">
            Nothing clears the noise bar yet. Backtest something first.
          </div>
        ) : (
          <table className="ttable">
            <thead>
              <tr>
                <th>Strategy</th>
                <th className="r">Sharpe</th>
                <th className="r">Blocking</th>
                <th>First thing in the way</th>
                <th className="r" />
              </tr>
            </thead>
            <tbody>
              {candidates.map((strategy) => {
                const report = reports[strategy.id];
                const first = report?.checks.find((check) => !check.passed);
                return (
                  <tr key={strategy.id}>
                    <td>
                      <b>{strategy.title}</b>
                      <div className="tfine">{strategy.asset_class} · {strategy.timeframe}</div>
                    </td>
                    <td className="r">{strategy.sharpe?.toFixed(2) ?? '—'}</td>
                    <td className="r">
                      {report ? (
                        <b className={report.blockers ? 'neg' : ''}>{report.blockers}</b>
                      ) : (
                        <span className="tdim">…</span>
                      )}
                    </td>
                    <td className="tfine">{first ? first.name : report ? 'nothing' : 'checking…'}</td>
                    <td className="r">
                      <button className="tbtn sm" type="button" onClick={() => onDeploy(strategy)}>
                        Review
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="tpanel">
        <h3 className="ui-heading">
          Order-path safety
          <Info>
            What is built, and what is not. Each line is a claim about this repository, not
            about what a live system generally ought to have.
          </Info>
        </h3>
        <ul className="checks">
          <li data-passed="true">
            <span className="ck">✓</span>
            <div>
              <b>Deterministic client order IDs<Info>hash(strategy_id, signal_time, instrument_id, seq) — a retry cannot double-send.</Info></b>
            </div>
          </li>
          <li data-passed="true">
            <span className="ck">✓</span>
            <div>
              <b>UNKNOWN is a real order state<Info>Resolved by querying the broker, never by assuming.</Info></b>
            </div>
          </li>
          <li data-passed="true">
            <span className="ck">✓</span>
            <div>
              <b>Kill switch in a separate process<Info>Separate credentials from the strategies. Checked per workspace and globally.</Info></b>
            </div>
          </li>
          <li data-passed="false">
            <span className="ck">✕</span>
            <div>
              <b>Broker adapter proven against the live API<Info>KiteBroker is covered by tests against a fake client only (T-3336). The
                first real order would also be the first real exercise of that code.</Info></b>
            </div>
          </li>
          <li data-passed="false">
            <span className="ck">✕</span>
            <div>
              <b>Forward-test stage<Info>Not built (T-3311). Without it nothing can legitimately reach live.</Info></b>
            </div>
          </li>
        </ul>
      </div>
    </>
  );
}
