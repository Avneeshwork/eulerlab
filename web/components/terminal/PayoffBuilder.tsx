/**
 * Multi-leg payoff at expiry.
 *
 * Expiry payoff only, and deliberately so. A "current P&L" curve would need a
 * vol surface forward in time and a view on how it moves, and the honest
 * version of that is a model with assumptions in it. Intrinsic value at expiry
 * has none: it is arithmetic on the strike and the premium paid, and it is the
 * one curve that is true regardless of what vol does between now and then.
 *
 * Premiums come from the chain on screen, so the payoff is priced off the same
 * day the rest of the tab is showing. Changing the day or the expiry reprices
 * every leg, which is the point — a spread that works on today's board is a
 * different trade on last month's.
 */

'use client';

import { useMemo, useState } from 'react';

export type Leg = {
  id: number;
  strike: number;
  right: 'CE' | 'PE';
  side: 'buy' | 'sell';
  lots: number;
};

type StrikeRow = {
  strike: number;
  call_price: number | null;
  put_price: number | null;
  call_traded: boolean;
  put_traded: boolean;
  lot_size?: number | null;
};

/** Intrinsic value of one option at a settlement price. */
function intrinsic(right: 'CE' | 'PE', strike: number, settle: number): number {
  return right === 'CE' ? Math.max(settle - strike, 0) : Math.max(strike - settle, 0);
}

/** Net payoff per unit of underlying, across every leg. */
export function payoffAt(legs: Leg[], rows: StrikeRow[], settle: number): number {
  let total = 0;
  for (const leg of legs) {
    const row = rows.find((r) => r.strike === leg.strike);
    const premium = row ? (leg.right === 'CE' ? row.call_price : row.put_price) : null;
    if (premium === null || premium === undefined) continue;
    const value = intrinsic(leg.right, leg.strike, settle);
    const perUnit = leg.side === 'buy' ? value - premium : premium - value;
    total += perUnit * leg.lots;
  }
  return total;
}

const W = 720;
const H = 220;

export function PayoffBuilder({
  rows,
  forward,
  atm,
  lotSize,
}: {
  rows: StrikeRow[];
  forward: number | null;
  atm: number | null;
  lotSize: number;
}) {
  const [legs, setLegs] = useState<Leg[]>([]);
  const [nextId, setNextId] = useState(1);
  const [at, setAt] = useState<{ settle: number; pnl: number } | null>(null);

  const add = (right: 'CE' | 'PE', side: 'buy' | 'sell') => {
    const strike = atm ?? rows[Math.floor(rows.length / 2)]?.strike;
    if (strike === undefined) return;
    setLegs((current) => [...current, { id: nextId, strike, right, side, lots: 1 }]);
    setNextId((n) => n + 1);
  };

  const update = (id: number, patch: Partial<Leg>) =>
    setLegs((current) => current.map((l) => (l.id === id ? { ...l, ...patch } : l)));

  const curve = useMemo(() => {
    if (legs.length === 0 || rows.length === 0) return [];
    // Swept across the listed board rather than a fixed percentage band, so
    // the x-axis covers exactly the settlements the market has priced.
    const lo = rows[0].strike;
    const hi = rows[rows.length - 1].strike;
    const steps = 160;
    return Array.from({ length: steps + 1 }, (_, i) => {
      const settle = lo + ((hi - lo) * i) / steps;
      return { settle, pnl: payoffAt(legs, rows, settle) * lotSize };
    });
  }, [legs, rows, lotSize]);

  const stats = useMemo(() => {
    if (curve.length === 0) return null;
    const pnls = curve.map((p) => p.pnl);
    const best = Math.max(...pnls);
    const worst = Math.min(...pnls);

    // Unbounded is reported as unbounded. A naked short call loses without
    // limit, and the largest loss inside the listed strike range is a number
    // about the chart's edge rather than about the position.
    const edgeLow = curve[0].pnl;
    const edgeHigh = curve[curve.length - 1].pnl;
    const risingAtTop = edgeHigh > curve[curve.length - 10]?.pnl;
    const fallingAtTop = edgeHigh < curve[curve.length - 10]?.pnl;
    const risingAtBottom = edgeLow > curve[10]?.pnl;
    const fallingAtBottom = edgeLow < curve[10]?.pnl;

    const breakevens: number[] = [];
    for (let i = 1; i < curve.length; i += 1) {
      const a = curve[i - 1];
      const b = curve[i];
      if ((a.pnl <= 0 && b.pnl > 0) || (a.pnl >= 0 && b.pnl < 0)) {
        const t = Math.abs(a.pnl) / (Math.abs(a.pnl) + Math.abs(b.pnl) || 1);
        breakevens.push(a.settle + (b.settle - a.settle) * t);
      }
    }

    return {
      best,
      worst,
      breakevens,
      profitUnbounded: risingAtTop || risingAtBottom,
      lossUnbounded: fallingAtTop || fallingAtBottom,
    };
  }, [curve]);

  const money = (v: number) =>
    `${v < 0 ? '−' : ''}₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

  const lo = curve.length ? curve[0].settle : 0;
  const hi = curve.length ? curve[curve.length - 1].settle : 1;
  const span = hi - lo || 1;
  const peak = curve.length ? Math.max(...curve.map((p) => Math.abs(p.pnl))) || 1 : 1;
  const mid = H / 2;
  const x = (settle: number) => 6 + ((settle - lo) / span) * (W - 12);
  const y = (pnl: number) => mid - (pnl / peak) * (mid - 12);

  return (
    <>
      <div className="ttools" style={{ marginBottom: 14 }}>
        <button className="tchip" type="button" onClick={() => add('CE', 'buy')}>
          + buy call
        </button>
        <button className="tchip" type="button" onClick={() => add('CE', 'sell')}>
          + sell call
        </button>
        <button className="tchip" type="button" onClick={() => add('PE', 'buy')}>
          + buy put
        </button>
        <button className="tchip" type="button" onClick={() => add('PE', 'sell')}>
          + sell put
        </button>
        {legs.length > 0 && (
          <div className="ttools-actions">
            <button className="tchip sm" type="button" onClick={() => setLegs([])}>
              clear
            </button>
          </div>
        )}
      </div>

      {legs.length === 0 ? (
        <p className="tfine">
          Add legs to price a spread. Premiums are taken from the chain on screen, so the
          payoff is priced on the day and expiry selected above — a spread that works on
          today&rsquo;s board is a different trade on last month&rsquo;s.
        </p>
      ) : (
        <>
          <table className="ttable" style={{ marginBottom: 16 }}>
            <thead>
              <tr>
                <th>Side</th>
                <th>Right</th>
                <th>Strike</th>
                <th style={{ textAlign: 'right' }}>Premium</th>
                <th style={{ textAlign: 'right' }}>Lots</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {legs.map((leg) => {
                const row = rows.find((r) => r.strike === leg.strike);
                const premium = leg.right === 'CE' ? row?.call_price : row?.put_price;
                const traded = leg.right === 'CE' ? row?.call_traded : row?.put_traded;
                return (
                  <tr key={leg.id}>
                    <td>
                      <select
                        value={leg.side}
                        onChange={(e) => update(leg.id, { side: e.target.value as 'buy' | 'sell' })}
                      >
                        <option value="buy">buy</option>
                        <option value="sell">sell</option>
                      </select>
                    </td>
                    <td>
                      <select
                        value={leg.right}
                        onChange={(e) => update(leg.id, { right: e.target.value as 'CE' | 'PE' })}
                      >
                        <option value="CE">call</option>
                        <option value="PE">put</option>
                      </select>
                    </td>
                    <td>
                      <select
                        value={leg.strike}
                        onChange={(e) => update(leg.id, { strike: Number(e.target.value) })}
                      >
                        {rows.map((r) => (
                          <option key={r.strike} value={r.strike}>
                            {r.strike.toLocaleString('en-IN')}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td
                      className="r"
                      style={{ textAlign: 'right', color: traded ? undefined : 'var(--ink-4)' }}
                      title={traded ? '' : 'never traded today — this is a settlement mark'}
                    >
                      {premium === null || premium === undefined ? '—' : premium.toFixed(2)}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <input
                        type="number"
                        min={1}
                        value={leg.lots}
                        onChange={(e) =>
                          update(leg.id, { lots: Math.max(1, Number(e.target.value) || 1) })
                        }
                        style={{ width: 64, textAlign: 'right' }}
                      />
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        className="tchip sm"
                        type="button"
                        onClick={() => setLegs((c) => c.filter((l) => l.id !== leg.id))}
                      >
                        remove
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <div style={{ overflowX: 'auto' }}>
            <svg
              viewBox={`0 0 ${W} ${H}`}
              style={{ width: '100%', minWidth: 520, height: H, cursor: 'crosshair' }}
              onMouseMove={(event) => {
                const box = event.currentTarget.getBoundingClientRect();
                const frac = (event.clientX - box.left - 6) / Math.max(box.width - 12, 1);
                const settle = lo + Math.min(Math.max(frac, 0), 1) * span;
                setAt({ settle, pnl: payoffAt(legs, rows, settle) * lotSize });
              }}
              onMouseLeave={() => setAt(null)}
            >
              <line x1={0} y1={mid} x2={W} y2={mid} stroke="var(--rule-2)" strokeWidth="1" />
              {forward !== null && forward >= lo && forward <= hi && (
                <line
                  x1={x(forward)}
                  y1={0}
                  x2={x(forward)}
                  y2={H}
                  stroke="var(--ink-4)"
                  strokeWidth="1"
                  strokeDasharray="3 3"
                />
              )}
              <path
                d={curve
                  .map((p, i) => `${i === 0 ? 'M' : 'L'}${x(p.settle).toFixed(1)},${y(p.pnl).toFixed(1)}`)
                  .join(' ')}
                fill="none"
                stroke="var(--neon)"
                strokeWidth="1.5"
              />
              {stats?.breakevens.map((b) => (
                <circle key={b} cx={x(b)} cy={mid} r={3} fill="var(--caveat)" />
              ))}
              {at && <line x1={x(at.settle)} y1={0} x2={x(at.settle)} y2={H} stroke="var(--ink-4)" strokeWidth="1" />}
            </svg>
            <div className="readout">
              {at ? (
                <>
                  <b>{at.settle.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</b>
                  <span style={{ color: at.pnl >= 0 ? 'var(--neon)' : 'var(--caveat)' }}>
                    {money(at.pnl)}
                  </span>
                </>
              ) : (
                <span className="tfine">
                  Hover to read the payoff at a settlement. Dashed line is the forward; dots are
                  breakevens.
                </span>
              )}
            </div>
          </div>

          {stats && (
            <div className="period" style={{ marginTop: 16 }}>
              <div>
                <span>Max profit</span>
                <b>{stats.profitUnbounded ? 'unbounded' : money(stats.best)}</b>
                <i className="tfine">
                  {stats.profitUnbounded ? 'still rising at the edge of the board' : 'at expiry'}
                </i>
              </div>
              <div>
                <span>Max loss</span>
                <b>{stats.lossUnbounded ? 'unbounded' : money(stats.worst)}</b>
                <i className="tfine">
                  {stats.lossUnbounded
                    ? 'still falling at the edge of the board'
                    : 'at expiry'}
                </i>
              </div>
              <div>
                <span>Breakeven</span>
                <b>
                  {stats.breakevens.length === 0
                    ? '—'
                    : stats.breakevens
                        .map((b) => b.toLocaleString('en-IN', { maximumFractionDigits: 0 }))
                        .join('  ·  ')}
                </b>
                <i className="tfine">{lotSize} per lot</i>
              </div>
            </div>
          )}

          <p className="tfine" style={{ marginTop: 12 }}>
            Payoff at <b>expiry</b>, which is arithmetic on the strike and the premium and
            needs no view on volatility. It is not a current-value curve: that would need a
            vol surface forward in time and a model for how it moves, and would be a set of
            assumptions wearing the same shape. Costs are not applied — brokerage, STT and
            the bid-ask spread all land against this, and the spread alone can be several
            percent on a contract whose settlement price looks tradable.
          </p>
        </>
      )}
    </>
  );
}
