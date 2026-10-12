'use client';

/**
 * The options tools OpenAlgo has and this screen did not: an OI tracker, a
 * volatility surface, and the at-the-money straddle and its implied vol over
 * time (OpenAlgo's Straddle Chart and Option Greeks history).
 *
 * All three read the same chain endpoint as the rest of the Options page, so a
 * figure here is the figure the chain shows for that day. The history view
 * reads `/api/options/history`, which is that endpoint run once per day.
 */

import { useEffect, useMemo, useState } from 'react';
import { api } from '@/lib/api';
import type { OptionChain, OptionHistoryPoint } from '@/lib/api';

const big = (value: number | null | undefined) =>
  value === null || value === undefined
    ? '—'
    : value.toLocaleString('en-IN', { maximumFractionDigits: 0 });

const signed = (value: number) =>
  `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

const pct = (value: number | null | undefined, digits = 1) =>
  value === null || value === undefined ? '—' : `${(value * 100).toFixed(digits)}%`;

type Row = OptionChain['strikes'][number];

/* ============================ OI tracker ============================ */

/**
 * Call and put open interest by strike, with the change since the previous
 * landed day. The strike with the most put OI is read as support and the one
 * with the most call OI as resistance, which is how OpenAlgo's OI Range labels
 * them; it is a positioning fact, not a forecast.
 */
export function OiTracker({
  chain,
  rows,
  previousDay,
}: {
  chain: OptionChain;
  /** The strikes on screen, already narrowed by the page's range control. */
  rows: Row[];
  /** The landed day before the chain's day, or empty if there is none. */
  previousDay: string;
}) {
  const [previous, setPrevious] = useState<OptionChain | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!previousDay) {
      setPrevious(null);
      return;
    }
    let alive = true;
    setLoading(true);
    api
      .optionChain(chain.underlying, chain.expiry, previousDay)
      .then((c) => alive && setPrevious(c.ok && c.expiry === chain.expiry ? c : null))
      .catch(() => alive && setPrevious(null))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [chain.underlying, chain.expiry, previousDay]);

  const before = useMemo(() => {
    const map = new Map<number, Row>();
    for (const row of previous?.strikes ?? []) map.set(row.strike, row);
    return map;
  }, [previous]);

  const support = chain.strikes.reduce<Row | null>(
    (best, row) => ((row.put_oi ?? 0) > (best?.put_oi ?? 0) ? row : best),
    null
  );
  const resistance = chain.strikes.reduce<Row | null>(
    (best, row) => ((row.call_oi ?? 0) > (best?.call_oi ?? 0) ? row : best),
    null
  );
  const peak = Math.max(1, ...rows.map((r) => Math.max(r.call_oi ?? 0, r.put_oi ?? 0)));
  const change = (row: Row, side: 'call' | 'put') => {
    const earlier = before.get(row.strike);
    if (!earlier) return null;
    const now = side === 'call' ? row.call_oi : row.put_oi;
    const then = side === 'call' ? earlier.call_oi : earlier.put_oi;
    return now === null || then === null ? null : now - then;
  };
  const totalChange = (side: 'call' | 'put') =>
    previous
      ? chain.strikes.reduce((sum, row) => sum + (change(row, side) ?? 0), 0)
      : null;
  const callChange = totalChange('call');
  const putChange = totalChange('put');

  return (
    <>
      <div className="tstats">
        <div className="tstat-card">
          <span>Support (most put OI)</span>
          <b>{big(support?.strike)}</b>
          <i>{big(support?.put_oi)} contracts</i>
        </div>
        <div className="tstat-card">
          <span>Resistance (most call OI)</span>
          <b>{big(resistance?.strike)}</b>
          <i>{big(resistance?.call_oi)} contracts</i>
        </div>
        <div className="tstat-card">
          <span>PCR by OI</span>
          <b>{chain.put_call_ratio.by_open_interest?.toFixed(2) ?? '—'}</b>
          <i>
            {big(chain.put_call_ratio.put_open_interest)} puts ·{' '}
            {big(chain.put_call_ratio.call_open_interest)} calls
          </i>
        </div>
        <div className="tstat-card">
          <span>OI change since {previousDay || 'previous day'}</span>
          <b className="oi-change">
            {callChange === null ? '—' : <span className="neg">{signed(callChange)}</span>}
            {' / '}
            {putChange === null ? '—' : <span className="pos">{signed(putChange)}</span>}
          </b>
          <i>calls / puts{loading ? ' · reading…' : ''}</i>
        </div>
      </div>

      <div className="tpanel" style={{ padding: 16, marginTop: 16 }}>
        <h3>Open interest by strike</h3>
        <p className="tfine" style={{ margin: '0 0 12px' }}>
          Calls to the left, puts to the right; the figure under each bar is the change since{' '}
          {previous ? previousDay : 'the previous day (not landed for this expiry)'}. The
          at-the-money strike is highlighted.
        </p>
        <div className="oi-rows">
          <div className="oi-row oi-head">
            <span>Call OI</span>
            <span>Strike</span>
            <span>Put OI</span>
          </div>
          {rows.map((row) => {
            const c = change(row, 'call');
            const p = change(row, 'put');
            return (
              <div
                key={row.strike}
                className={`oi-row${row.strike === chain.atm_strike ? ' atm' : ''}`}
              >
                <div className="oi-side call">
                  <div className="oi-bar" style={{ width: `${((row.call_oi ?? 0) / peak) * 100}%` }} />
                  <span>
                    {big(row.call_oi)}
                    {c !== null && <em className={c >= 0 ? 'up' : 'dn'}>{signed(c)}</em>}
                  </span>
                </div>
                <b>{big(row.strike)}</b>
                <div className="oi-side put">
                  <div className="oi-bar" style={{ width: `${((row.put_oi ?? 0) / peak) * 100}%` }} />
                  <span>
                    {big(row.put_oi)}
                    {p !== null && <em className={p >= 0 ? 'up' : 'dn'}>{signed(p)}</em>}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

/* ============================ Vol surface ============================ */

const MONEYNESS = [-0.1, -0.075, -0.05, -0.025, 0, 0.025, 0.05, 0.075, 0.1];

/**
 * Implied vol by moneyness and expiry, from the out-of-the-money side: puts
 * below the forward, calls above. Each expiry is its own chain request, read
 * one after another, so a surface over six expiries is six bhavcopy reads.
 */
export function VolSurface({ chain }: { chain: OptionChain }) {
  const [chains, setChains] = useState<OptionChain[]>([]);
  const [loading, setLoading] = useState(true);
  const expiries = chain.expiries.slice(0, 6);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setChains([]);
    (async () => {
      const out: OptionChain[] = [];
      for (const expiry of expiries) {
        try {
          const next =
            expiry === chain.expiry
              ? chain
              : await api.optionChain(chain.underlying, expiry, chain.day);
          if (next.ok) out.push(next);
        } catch {
          // An expiry that fails to load is a missing column, not a zero.
        }
        if (!alive) return;
        setChains([...out]);
      }
      if (alive) setLoading(false);
    })();
    return () => {
      alive = false;
    };
    // Keyed on the underlying and day only: switching the expiry picker on the
    // page should not re-read a surface that already holds every expiry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chain.underlying, chain.day]);

  const cell = (c: OptionChain, m: number): { iv: number | null; strike: number | null } => {
    if (c.forward === null || c.strikes.length === 0) return { iv: null, strike: null };
    const target = c.forward * (1 + m);
    const row = c.strikes.reduce((best, r) =>
      Math.abs(r.strike - target) < Math.abs(best.strike - target) ? r : best
    );
    const iv = row.strike < c.forward ? row.put_iv ?? row.call_iv : row.call_iv ?? row.put_iv;
    return { iv, strike: row.strike };
  };

  const all = chains.flatMap((c) => MONEYNESS.map((m) => cell(c, m).iv)).filter(
    (v): v is number => v !== null
  );
  const low = Math.min(...all, Infinity);
  const high = Math.max(...all, -Infinity);
  const shade = (iv: number | null) => {
    if (iv === null || !Number.isFinite(low) || high <= low) return undefined;
    const t = (iv - low) / (high - low);
    return { background: `color-mix(in srgb, var(--caveat) ${Math.round(8 + t * 45)}%, transparent)` };
  };

  return (
    <div className="tpanel" style={{ padding: 16 }}>
      <h3>Implied volatility surface</h3>
      <p className="tfine" style={{ margin: '0 0 12px' }}>
        Rows are expiries, columns are distance from each expiry&rsquo;s forward. Puts below the
        forward, calls above, so every cell is the out-of-the-money contract. Darker is higher
        vol. A blank cell is a strike the solver could not price, never zero.
        {loading && ` Reading ${chains.length + 1} of ${expiries.length} expiries…`}
      </p>
      <div className="tscroll">
        <table className="ttable heat">
          <thead>
            <tr>
              <th>Expiry</th>
              <th className="r">Days</th>
              {MONEYNESS.map((m) => (
                <th key={m} className="r">
                  {m === 0 ? 'ATM' : `${m > 0 ? '+' : '−'}${Math.abs(m * 100)}%`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {chains.map((c) => (
              <tr key={c.expiry}>
                <td>
                  <b>{c.expiry}</b>
                </td>
                <td className="r">{c.days_to_expiry}</td>
                {MONEYNESS.map((m) => {
                  const { iv, strike } = cell(c, m);
                  return (
                    <td
                      key={m}
                      className="r"
                      style={shade(iv)}
                      title={strike === null ? undefined : `strike ${big(strike)}`}
                    >
                      {iv === null ? '' : pct(iv)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ============================ Straddle and IV history ============================ */

function Line({
  points,
  value,
  format,
  label,
}: {
  points: OptionHistoryPoint[];
  value: (p: OptionHistoryPoint) => number | null;
  format: (v: number) => string;
  label: string;
}) {
  const series = points
    .map((p, i) => ({ i, v: value(p), p }))
    .filter((d): d is { i: number; v: number; p: OptionHistoryPoint } => d.v !== null);
  if (series.length < 2) return <p className="tfine">Not enough days to draw {label}.</p>;
  const W = 720;
  const H = 160;
  const low = Math.min(...series.map((d) => d.v));
  const high = Math.max(...series.map((d) => d.v));
  const span = high - low || 1;
  const x = (i: number) => (i / Math.max(points.length - 1, 1)) * W;
  const y = (v: number) => H - 8 - ((v - low) / span) * (H - 16);
  const path = series.map((d, k) => `${k ? 'L' : 'M'}${x(d.i).toFixed(1)},${y(d.v).toFixed(1)}`).join(' ');
  // A vertical rule where the nearest expiry rolls, because the straddle
  // resets there and an unmarked jump reads as a market move.
  const rolls = points
    .map((p, i) => (i > 0 && p.expiry !== points[i - 1].expiry ? i : -1))
    .filter((i) => i > 0);
  const last = series[series.length - 1];
  return (
    <figure className="eqchart">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label}>
        {rolls.map((i) => (
          <line key={i} x1={x(i)} x2={x(i)} y1={0} y2={H} className="eq-base" />
        ))}
        <path d={path} className="eq-line up" />
      </svg>
      <figcaption>
        <span>
          {points[0].day} → {points[points.length - 1].day}
        </span>
        <span>
          low {format(low)} · high {format(high)} · last <b>{format(last.v)}</b>
        </span>
        {rolls.length > 0 && <span className="tdim">dashed lines mark an expiry roll</span>}
      </figcaption>
    </figure>
  );
}

export function StraddleHistory({ underlying }: { underlying: string }) {
  const [days, setDays] = useState(30);
  const [points, setPoints] = useState<OptionHistoryPoint[] | null>(null);
  const [error, setError] = useState('');
  const [skipped, setSkipped] = useState<string[]>([]);

  useEffect(() => {
    let alive = true;
    setPoints(null);
    setError('');
    api
      .optionHistory(underlying, days)
      .then((h) => {
        if (!alive) return;
        setSkipped(h.skipped ?? []);
        if (h.ok && h.points) setPoints(h.points);
        else setError(h.error ?? 'no history');
      })
      .catch((problem) => alive && setError(problem instanceof Error ? problem.message : String(problem)));
    return () => {
      alive = false;
    };
  }, [underlying, days]);

  return (
    <>
      <div className="ttools" style={{ marginBottom: 12 }}>
        <span className="tfine">Days</span>
        {[10, 30, 60, 120].map((n) => (
          <button
            key={n}
            className="tchip sm"
            type="button"
            aria-pressed={days === n}
            onClick={() => setDays(n)}
          >
            {n}
          </button>
        ))}
      </div>
      {error && <p className="tdesc">{error}</p>}
      {!points && !error && (
        <p className="tdesc">Reading {days} days of chains; each day is one bhavcopy…</p>
      )}
      {points && (
        <>
          <div className="tpanel" style={{ padding: 16, marginBottom: 16 }}>
            <h3>At-the-money straddle premium</h3>
            <p className="tfine" style={{ margin: '0 0 12px' }}>
              Call plus put at the strike nearest the forward, nearest expiry, each day.
            </p>
            <Line
              points={points}
              value={(p) => p.straddle}
              format={(v) => v.toFixed(2)}
              label="straddle premium"
            />
          </div>
          <div className="tpanel" style={{ padding: 16, marginBottom: 16 }}>
            <h3>At-the-money implied volatility</h3>
            <p className="tfine" style={{ margin: '0 0 12px' }}>
              Mean of the call and put IV at that strike, Black-76 on the fitted forward.
            </p>
            <Line points={points} value={(p) => p.atm_iv} format={(v) => pct(v)} label="ATM IV" />
          </div>
          <div className="tpanel" style={{ padding: 16 }}>
            <h3>Day by day</h3>
            <div className="tscroll" style={{ maxHeight: '50vh' }}>
              <table className="ttable">
                <thead>
                  <tr>
                    <th>Day</th>
                    <th>Expiry</th>
                    <th className="r">Days left</th>
                    <th className="r">Forward</th>
                    <th className="r">ATM strike</th>
                    <th className="r">Call</th>
                    <th className="r">Put</th>
                    <th className="r">Straddle</th>
                    <th className="r">ATM IV</th>
                    <th className="r">PCR (OI)</th>
                    <th className="r">Max pain</th>
                  </tr>
                </thead>
                <tbody>
                  {[...points].reverse().map((p) => (
                    <tr key={p.day} className={p.traded ? undefined : 'untraded'}>
                      <td>{p.day}</td>
                      <td>{p.expiry}</td>
                      <td className="r">{p.days_to_expiry}</td>
                      <td className="r">{big(p.forward)}</td>
                      <td className="r">{big(p.atm_strike)}</td>
                      <td className="r">{p.call.toFixed(2)}</td>
                      <td className="r">{p.put.toFixed(2)}</td>
                      <td className="r">
                        <b>{p.straddle.toFixed(2)}</b>
                      </td>
                      <td className="r">{pct(p.atm_iv)}</td>
                      <td className="r">{p.pcr_oi?.toFixed(2) ?? '—'}</td>
                      <td className="r">{big(p.max_pain)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="tfine" style={{ marginTop: 10 }}>
              Dimmed rows had an untraded leg, so that day&rsquo;s price is NSE&rsquo;s settlement
              model rather than a transaction.
              {skipped.length > 0 &&
                ` ${skipped.length} day${skipped.length === 1 ? '' : 's'} had no priced at-the-money pair and are left out: ${skipped.slice(0, 5).join(', ')}${skipped.length > 5 ? '…' : ''}.`}
            </p>
          </div>
        </>
      )}
    </>
  );
}
