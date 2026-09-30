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

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { FleetStrategy, Preflight } from '@/lib/api';

export function LiveTab({
  fleet,
  workspace,
  onDeploy,
}: {
  fleet: FleetStrategy[];
  workspace: string;
  onDeploy: (strategy: FleetStrategy) => void;
}) {
  const [reports, setReports] = useState<Record<string, Preflight>>({});
  const live = fleet.filter((s) => s.stage === 'live');
  const forward = fleet.filter((s) => s.stage === 'forward_testing');
  const candidates = fleet.filter((s) => s.clears_bar && s.runnable);

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
      <section className="thero">
        <div>
          <div className="theyebrow">Trading now</div>
          <div className="thnum">
            <b>{live.length}</b>
            <span className="unit">live · {forward.length} forward-testing</span>
          </div>
          <p className="thsub">
            Nothing can reach either stage yet, and that is the gate working rather than
            failing. Stage is derived from the trial ledger; the forward-test stage is not
            built (T-3311); and a strategy that has only been screened has no evidence
            behind it, so it has no business sending orders.
          </p>
        </div>
        <div className="thstats">
          <div className="thstat">
            <span>Clearing the bar</span>
            <b className={candidates.length ? 'on' : ''}>{candidates.length}</b>
          </div>
        </div>
      </section>

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
        <h3>Order-path safety</h3>
        <p className="tfine" style={{ marginBottom: 12 }}>
          What is built, and what is not. Each line is a claim about this repository, not
          about what a live system generally ought to have.
        </p>
        <ul className="checks">
          <li data-passed="true">
            <span className="ck">✓</span>
            <div>
              <b>Deterministic client order IDs</b>
              <p>hash(strategy_id, signal_time, instrument_id, seq) — a retry cannot double-send.</p>
            </div>
          </li>
          <li data-passed="true">
            <span className="ck">✓</span>
            <div>
              <b>UNKNOWN is a real order state</b>
              <p>Resolved by querying the broker, never by assuming.</p>
            </div>
          </li>
          <li data-passed="true">
            <span className="ck">✓</span>
            <div>
              <b>Kill switch in a separate process</b>
              <p>Separate credentials from the strategies. Checked per workspace and globally.</p>
            </div>
          </li>
          <li data-passed="false">
            <span className="ck">✕</span>
            <div>
              <b>Broker adapter proven against the live API</b>
              <p>
                KiteBroker is covered by tests against a fake client only (T-3336). The
                first real order would also be the first real exercise of that code.
              </p>
            </div>
          </li>
          <li data-passed="false">
            <span className="ck">✕</span>
            <div>
              <b>Forward-test stage</b>
              <p>Not built (T-3311). Without it nothing can legitimately reach live.</p>
            </div>
          </li>
        </ul>
      </div>
    </>
  );
}
