'use client';

/**
 * A recorded parameter sweep for one strategy: what was tried, what was chosen
 * on the in-sample years, and what the choice earned on the holdout.
 *
 * Read-only. Sweeps are run from `make tune-sharpe-momentum` (research 067).
 *
 * The verdict leads, then the before-and-after table, then the heatmap. The
 * heatmap is the evidence that matters most: a broad region that stays good on
 * the holdout is an effect, a lone bright cell is a draw from 64.
 */

import { useEffect, useMemo, useState } from 'react';

import { api, type Tuning, type TuningSide, type TuningStats } from '@/lib/api';

const pct = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined || !Number.isFinite(value)
    ? '—'
    : `${value < 0 ? '−' : ''}${Math.abs(value * 100).toFixed(digits)}%`;

const sh = (value: number | null | undefined) =>
  value === null || value === undefined || !Number.isFinite(value) ? '—' : value.toFixed(2);

const WINDOW_LABEL: Record<number, string> = { 63: '3m', 126: '6m', 189: '9m', 252: '12m' };
const REBALANCE_LABEL: Record<number, string> = {
  5: 'weekly',
  10: 'every 2 weeks',
  21: 'monthly',
  42: 'every 2 months',
  63: 'quarterly',
};

function settingLabel(params: number[] | undefined): string {
  if (!params) return '—';
  const [window, top, rebalance] = params;
  return `${WINDOW_LABEL[window] ?? `${window}d`} · ${top} names · ${REBALANCE_LABEL[rebalance] ?? `every ${rebalance}d`}`;
}

/**
 * Adopt the tuned setting only when choosing this way demonstrably works:
 * re-tuning year by year beat leaving the paper's setting alone, and PBO is
 * inside the mandate's 0.25. Otherwise the paper's setting stays.
 */
function decision(data: Tuning): { adopt: boolean; label: string } {
  const wf = data.walk_forward;
  const sameAsPaper = data.paper && data.chosen.setting === data.paper.setting;
  if (sameAsPaper) return { adopt: false, label: "Paper's setting is the best region" };
  const beatsPaper =
    wf.paper_same_years !== null && wf.stitched.sharpe > wf.paper_same_years.sharpe;
  const adopt = beatsPaper && data.pbo.value <= 0.25;
  return { adopt, label: adopt ? 'Tuned setting adopted' : 'Kept the original setting' };
}

export function TuningPanel({ strategyId }: { strategyId: string }) {
  const [data, setData] = useState<Tuning | null>(null);
  useEffect(() => {
    let live = true;
    api
      .tuning(strategyId)
      .then((found) => live && setData(found.ran ? found : null))
      .catch(() => live && setData(null));
    return () => {
      live = false;
    };
  }, [strategyId]);
  return data ? <TuningView data={data} /> : null;
}

export function TuningView({ data }: { data: Tuning }) {
  const [period, setPeriod] = useState<'in_sample' | 'holdout'>('holdout');
  const verdict = decision(data);
  const wf = data.walk_forward;
  const holdoutYear = data.holdout_from.slice(0, 4);
  const inSampleYears = `${data.in_sample[0].slice(0, 4)}–${data.in_sample[1].slice(2, 4)}`;

  return (
    <section className="tune" aria-label="Optimisation">
      <div className="walk-head">
        <h4>Optimisation</h4>
        <span className="walk-where">
          {data.settings_run} settings · chosen on {inSampleYears} · tested from {holdoutYear}
        </span>
        <span className={`verdict ${verdict.adopt ? 'verdict-ok' : 'verdict-flat'}`}>{verdict.label}</span>
      </div>

      <ul className="tune-read">
        <li>
          The best region before {holdoutYear} was <b>{settingLabel(data.chosen.params)}</b>: Sharpe{' '}
          {sh(data.chosen.in_sample.sharpe)} in-sample, {sh(data.chosen.holdout.sharpe)} on the holdout.
          {data.paper && (
            <>
              {' '}The paper&apos;s setting made {sh(data.paper.in_sample.sharpe)} and {sh(data.paper.holdout.sharpe)}.
            </>
          )}
        </li>
        <li>
          Re-tuning every year from {wf.folds[0]?.year} to {wf.folds[wf.folds.length - 1]?.year} earned
          Sharpe <b>{sh(wf.stitched.sharpe)}</b>
          {wf.paper_same_years && <>; keeping the paper&apos;s setting earned <b>{sh(wf.paper_same_years.sharpe)}</b></>}.
        </li>
        <li>
          Overfitting (PBO) is <b>{data.pbo.value.toFixed(2)}</b>: {data.pbo.verdict}. The mandate&apos;s ceiling is 0.25.
        </li>
        <li>
          Settings that ranked well before {holdoutYear} ranked only{' '}
          {data.rank_correlation_in_sample_vs_holdout < 0.5 ? 'weakly' : 'fairly'} well after it (rank correlation{' '}
          {data.rank_correlation_in_sample_vs_holdout.toFixed(2)}).
        </li>
      </ul>

      <CompareTable data={data} inSampleYears={inSampleYears} holdoutYear={holdoutYear} />

      <div className="tune-sub">
        <h5>Sharpe for every setting</h5>
        <div className="tune-toggle" role="tablist" aria-label="Period">
          <button type="button" role="tab" aria-selected={period === 'in_sample'} onClick={() => setPeriod('in_sample')}>
            {inSampleYears} (chosen on)
          </button>
          <button type="button" role="tab" aria-selected={period === 'holdout'} onClick={() => setPeriod('holdout')}>
            {holdoutYear} on (holdout)
          </button>
        </div>
      </div>
      <Heatmaps data={data} period={period} />

      {data.curves.chosen && (
        <>
          <div className="tune-sub">
            <h5>Growth of ₹1, after costs</h5>
          </div>
          <Curves data={data} />
        </>
      )}

      <p className="walk-fine">
        Every setting ran once over the whole panel, Tier B, after Indian costs, on the 250 most-traded stocks at
        each date. The choice is the setting whose mean in-sample Sharpe, with its neighbours on the grid, is
        highest, so a broad good region beats a single bright cell. The holdout years had already been seen by
        an earlier screening run of the paper&apos;s setting; only paper trading is truly unseen. Research 067.
      </p>
    </section>
  );
}

function CompareTable({
  data,
  inSampleYears,
  holdoutYear,
}: {
  data: Tuning;
  inSampleYears: string;
  holdoutYear: string;
}) {
  const rows: { name: string; side: TuningSide }[] = [
    { name: 'Chosen (best region)', side: data.chosen },
    ...(data.paper ? [{ name: 'Paper', side: data.paper }] : []),
    ...(data.best_single_point.setting !== data.chosen.setting
      ? [{ name: 'Best single cell', side: data.best_single_point }]
      : []),
  ];
  const cells = (s: TuningStats) => (
    <>
      <td className="num">{sh(s.sharpe)}</td>
      <td className={`num ${s.cagr >= 0 ? 'pos' : 'neg'}`}>{pct(s.cagr, 1)}</td>
      <td className="num neg">{pct(s.max_drawdown)}</td>
    </>
  );
  return (
    <div className="tune-scroll">
      <table className="tune-table">
        <thead>
          <tr>
            <th rowSpan={2}>Setting</th>
            <th colSpan={3}>{inSampleYears}</th>
            <th colSpan={3}>{holdoutYear} on</th>
            <th rowSpan={2}>Holdout Sharpe at 2× costs</th>
            <th rowSpan={2}>Trades</th>
          </tr>
          <tr>
            <th>Sharpe</th>
            <th>CAGR</th>
            <th>Max DD</th>
            <th>Sharpe</th>
            <th>CAGR</th>
            <th>Max DD</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ name, side }) => (
            <tr key={name}>
              <td>
                <b>{name}</b>
                <span>{settingLabel(side.params)}</span>
              </td>
              {cells(side.in_sample)}
              {cells(side.holdout)}
              <td className="num">{sh(side.at_2x_costs?.holdout.sharpe)}</td>
              <td className="num">{side.fills.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Heatmaps({ data, period }: { data: Tuning; period: 'in_sample' | 'holdout' }) {
  const grid = data.grid;
  const value = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of data.table) {
      map.set(row.params.join('-'), period === 'in_sample' ? row.in_sample_sharpe : row.holdout_sharpe);
    }
    return map;
  }, [data.table, period]);
  const all = [...value.values()];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const chosen = data.chosen.params.join('-');
  const paper = data.paper?.params.join('-');

  return (
    <div className="tune-heat">
      {grid.rebalance.map((rebalance) => (
        <div key={rebalance} className="tune-heat-one">
          <h6>Rebalanced {REBALANCE_LABEL[rebalance] ?? `every ${rebalance}d`}</h6>
          <table>
            <thead>
              <tr>
                <th aria-label="Lookback" />
                {grid.top.map((top) => (
                  <th key={top}>{top}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grid.window.map((window) => (
                <tr key={window}>
                  <th>{WINDOW_LABEL[window] ?? window}</th>
                  {grid.top.map((top) => {
                    const key = `${window}-${top}-${rebalance}`;
                    const v = value.get(key);
                    const share = v === undefined || hi === lo ? 0 : (v - lo) / (hi - lo);
                    const marks = [key === chosen ? 'chosen' : '', key === paper ? 'paper' : '']
                      .filter(Boolean)
                      .join(' ');
                    return (
                      <td
                        key={key}
                        className={marks ? `mark ${marks}` : undefined}
                        style={{ background: `color-mix(in srgb, var(--up) ${Math.round(8 + share * 72)}%, var(--surface))` }}
                        title={`${settingLabel([window, top, rebalance])}: Sharpe ${sh(v)}${marks ? ` (${marks})` : ''}`}
                      >
                        {sh(v)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <p className="tune-legend">
        Rows: lookback. Columns: names held. Darker is a higher Sharpe ({sh(lo)} to {sh(hi)}).{' '}
        <span className="mark chosen">Chosen</span> <span className="mark paper">Paper</span>
      </p>
    </div>
  );
}

const W = 720;
const H = 220;

function Curves({ data }: { data: Tuning }) {
  const lines: { key: 'chosen' | 'paper' | 'nifty'; label: string; cls: string }[] = [
    { key: 'chosen', label: `Chosen (${settingLabel(data.chosen.params)})`, cls: 'c-chosen' },
    { key: 'paper', label: "Paper's setting", cls: 'c-paper' },
    { key: 'nifty', label: 'Nifty 50 (NIFTYBEES, before costs)', cls: 'c-nifty' },
  ];
  const base = data.curves.chosen ?? [];
  const days = base.map(([d]) => d);
  const n = days.length;
  const values = lines.flatMap((l) => (data.curves[l.key] ?? []).map(([, v]) => v));
  const logLo = Math.log(Math.min(...values, 1));
  const logHi = Math.log(Math.max(...values, 1));
  const x = (i: number) => (n <= 1 ? 0 : (i / (n - 1)) * W);
  const y = (v: number) => H - 8 - ((Math.log(v) - logLo) / (logHi - logLo || 1)) * (H - 16);
  const holdoutIndex = days.findIndex((d) => d >= data.holdout_from);
  const ticks = [1, 2, 5, 10, 20, 50].filter((t) => Math.log(t) >= logLo && Math.log(t) <= logHi);
  const years = days
    .map((d, i) => [d, i] as const)
    .filter(([d], i) => i === 0 || d.slice(0, 4) !== days[i - 1].slice(0, 4))
    .filter(([d]) => Number(d.slice(0, 4)) % 2 === 0);

  return (
    <div className="tune-curves">
      <svg viewBox={`0 0 ${W} ${H + 18}`} role="img" aria-label="Growth of one rupee for the chosen setting, the paper's setting and the Nifty">
        {holdoutIndex > 0 && (
          <>
            <rect className="holdout" x={x(holdoutIndex)} y={0} width={W - x(holdoutIndex)} height={H} />
            <text className="holdout-label" x={x(holdoutIndex) + 6} y={14}>holdout</text>
          </>
        )}
        {ticks.map((t) => (
          <g key={t}>
            <line className="grid" x1={0} x2={W} y1={y(t)} y2={y(t)} />
            <text className="axis" x={2} y={y(t) - 3}>₹{t}</text>
          </g>
        ))}
        {years.map(([d, i]) => (
          <text key={d} className="axis" x={x(i)} y={H + 14}>{d.slice(0, 4)}</text>
        ))}
        {lines.map((l) => {
          const pts = data.curves[l.key];
          if (!pts || pts.length < 2) return null;
          const path = pts.map(([, v], i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('');
          return <path key={l.key} className={`line ${l.cls}`} d={path} />;
        })}
      </svg>
      <div className="tune-keys">
        {lines
          .filter((l) => data.curves[l.key])
          .map((l) => {
            const pts = data.curves[l.key] ?? [];
            const last = pts[pts.length - 1]?.[1];
            return (
              <span key={l.key} className={l.cls}>
                <i /> {l.label} <b>₹{last?.toFixed(1)}</b>
              </span>
            );
          })}
      </div>
    </div>
  );
}
