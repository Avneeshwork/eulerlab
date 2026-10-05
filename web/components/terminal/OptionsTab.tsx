/**
 * The option chain, with implied vol and the no-arbitrage findings.
 *
 * None of this is new analysis. `options/chain.py` has parsed F&O bhavcopy
 * into chains, `options/iv.py` has solved Black-76 implied vol and
 * `options/arbitrage.py` has run five no-arbitrage checks since the
 * options-quality sprint. The capability matrix has read "chains parsed, no
 * strategy path" the whole time, and the work was simply unreachable. This
 * screen stops hiding it.
 *
 * Untraded contracts are dimmed rather than removed. Their price is NSE's
 * settlement model output, not a transaction, so a number there means
 * something different from the one beside it — and a screen that renders both
 * identically invites them to be averaged together.
 */

'use client';

import { useEffect, useState } from 'react';

import { api } from '@/lib/api';
import {
  GammaChart,
  MaxPainChart,
  PositioningPanel,
  SmileChart,
} from './OptionsCharts';

type Strike = {
  strike: number;
  call_price: number | null;
  call_oi: number | null;
  call_iv: number | null;
  call_traded: boolean;
  put_price: number | null;
  put_oi: number | null;
  put_iv: number | null;
  put_traded: boolean;
};

type Chain = {
  ok: boolean;
  underlying: string;
  day: string;
  expiry: string;
  expiries: string[];
  days_to_expiry: number;
  forward: number | null;
  forward_source: string;
  discount: number;
  strikes: Strike[];
  atm_strike: number | null;
  max_pain: { strike: number; payout: number; curve: [number, number][] } | null;
  put_call_ratio: {
    by_open_interest: number | null;
    by_volume: number | null;
    call_open_interest: number;
    put_open_interest: number;
    call_volume: number;
    put_volume: number;
  };
  gamma: {
    total: number;
    flip: number | null;
    convention: string;
    points: { strike: number; exposure: number }[];
  };
  smile: { strike: number; moneyness: number; call_iv: number | null; put_iv: number | null }[];
  findings: { check: string; severity: string; detail: string }[];
  findings_note: string;
  error?: string;
  available?: string[];
};

const UNDERLYINGS = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'];

const VIEWS = ['Chain', 'Smile', 'Max pain', 'Gamma', 'Positioning', 'Checks'] as const;
type View = (typeof VIEWS)[number];

/** How many strikes either side of the money to show.
 *
 * A NIFTY board lists 140-odd strikes and the far wings barely trade, so the
 * default opens on the part with the open interest in it rather than making
 * every chart autoscale to a tail nobody is looking at. `0` means all. */
const RANGES = [10, 20, 40, 0] as const;

function pct(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function num(value: number | null): string {
  return value === null ? '—' : value.toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

export function OptionsTab() {
  const [underlying, setUnderlying] = useState('NIFTY');
  const [expiry, setExpiry] = useState('');
  const [chain, setChain] = useState<Chain | null>(null);
  const [busy, setBusy] = useState(true);
  const [view, setView] = useState<View>('Chain');
  const [day, setDay] = useState('');
  const [days, setDays] = useState<string[]>([]);
  const [range, setRange] = useState<number>(20);

  useEffect(() => {
    api
      .optionDays()
      .then((d) => d.ok && setDays(d.days))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    let alive = true;
    setBusy(true);
    api
      .optionChain(underlying, expiry, day)
      .then((c) => {
        if (!alive) return;
        setChain(c);
        setBusy(false);
      })
      .catch(() => alive && setBusy(false));
    return () => {
      alive = false;
    };
  }, [underlying, expiry, day]);

  // The strike nearest the forward, so the table can open where the money is
  // rather than at the lowest strike listed.
  const atm =
    chain?.ok && chain.forward !== null
      ? chain.strikes.reduce(
          (best, row) =>
            Math.abs(row.strike - chain.forward!) < Math.abs(best - chain.forward!)
              ? row.strike
              : best,
          chain.strikes[0]?.strike ?? 0
        )
      : null;

  // Applied once, here, so every view narrows together. Filtering inside each
  // chart would let the smile and the gamma profile disagree about which
  // strikes are on screen, which is the kind of mismatch nobody notices and
  // everybody misreads.
  const near = <T extends { strike: number }>(rows: T[]): T[] => {
    if (!range || !chain?.ok || chain.atm_strike === null) return rows;
    const sorted = [...rows].sort(
      (a, b) => Math.abs(a.strike - chain.atm_strike!) - Math.abs(b.strike - chain.atm_strike!)
    );
    return sorted.slice(0, range * 2 + 1).sort((a, b) => a.strike - b.strike);
  };

  return (
    <section className="tsection">
      <div className="theyebrow">Options</div>
      <h2 className="thero">
        {chain?.ok ? chain.underlying : underlying} <i>chain</i>
      </h2>

      <div className="ttools" style={{ marginTop: 20, marginBottom: 20 }}>
        {UNDERLYINGS.map((name) => (
          <button
            key={name}
            className="tchip"
            type="button"
            aria-pressed={underlying === name}
            onClick={() => {
              setUnderlying(name);
              setExpiry('');
            }}
          >
            {name}
          </button>
        ))}
        {chain?.ok && chain.expiries.length > 0 && (
          <label className="tsort">
            Expiry
            <select value={chain.expiry} onChange={(event) => setExpiry(event.target.value)}>
              {chain.expiries.map((date) => (
                <option key={date} value={date}>
                  {date}
                </option>
              ))}
            </select>
          </label>
        )}
        {/* 678 bhavcopy days are landed and the screen only ever showed the
            newest. Stepping through them is the difference between a chart of
            today and a tool you can ask a question with. */}
        {days.length > 0 && (
          <label className="tsort">
            Day
            <select
              value={day || days[0]}
              onChange={(event) => {
                setDay(event.target.value);
                setExpiry('');
              }}
            >
              {days.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {chain?.ok && (
        <div className="ttools" style={{ marginBottom: 20 }}>
          {VIEWS.map((name) => (
            <button
              key={name}
              className="tchip"
              type="button"
              aria-pressed={view === name}
              onClick={() => setView(name)}
            >
              {name}
            </button>
          ))}
          <div className="ttools-actions">
            <span className="tfine" style={{ marginRight: 6 }}>
              strikes
            </span>
            {RANGES.map((n) => (
              <button
                key={n}
                className="tchip sm"
                type="button"
                aria-pressed={range === n}
                onClick={() => setRange(n)}
              >
                {n === 0 ? 'all' : `±${n}`}
              </button>
            ))}
          </div>
        </div>
      )}

      {busy && <p className="tdesc">Reading the chain…</p>}

      {!busy && chain && !chain.ok && (
        <>
          <p className="tdesc">{chain.error}</p>
          {chain.available && chain.available.length > 0 && (
            <p className="tfine">Underlyings in this file: {chain.available.join(', ')}</p>
          )}
        </>
      )}

      {!busy && chain?.ok && (
        <>
          <div className="period" style={{ marginBottom: 24 }}>
            <div>
              <span>Forward</span>
              <b>{num(chain.forward)}</b>
              <i className="tfine">{chain.forward_source}</i>
            </div>
            <div>
              <span>Discount factor</span>
              <b>{chain.discount.toFixed(4)}</b>
              <i className="tfine">fitted, not assumed</i>
            </div>
            <div>
              <span>Expiry</span>
              <b>{chain.expiry}</b>
              <i className="tfine">
                {chain.days_to_expiry}d away · chain as of {chain.day}
              </i>
            </div>
          </div>

          {view === 'Smile' && (
            <div className="tpanel" style={{ padding: 16, marginBottom: 20 }}>
              <h3>Implied volatility by strike</h3>
              <SmileChart smile={near(chain.smile)} atm={chain.atm_strike} />
            </div>
          )}

          {view === 'Max pain' && (
            <div className="tpanel" style={{ padding: 16, marginBottom: 20 }}>
              <h3>Writer payout by settlement</h3>
              <MaxPainChart pain={chain.max_pain} forward={chain.forward} />
            </div>
          )}

          {view === 'Gamma' && (
            <div className="tpanel" style={{ padding: 16, marginBottom: 20 }}>
              <h3>Gamma exposure by strike</h3>
              <GammaChart
                gamma={{ ...chain.gamma, points: near(chain.gamma.points) }}
                atm={chain.atm_strike}
              />
            </div>
          )}

          {view === 'Positioning' && (
            <div className="tpanel" style={{ padding: 16, marginBottom: 20 }}>
              <h3>Put-call ratio</h3>
              <PositioningPanel ratio={chain.put_call_ratio} />
            </div>
          )}

          {view === 'Checks' && (
          <div className="tpanel" style={{ padding: 16, marginBottom: 20 }}>
            <h3>No-arbitrage checks</h3>
            {chain.findings.length === 0 ? (
              <p className="tfine">
                Nothing violated: parity, strike monotonicity, butterfly convexity, intrinsic
                bounds and calendar monotonicity all hold on the traded contracts.
              </p>
            ) : (
              <table className="ttable">
                <thead>
                  <tr>
                    <th>Check</th>
                    <th>Severity</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {chain.findings.map((finding, index) => (
                    <tr key={`${finding.check}-${index}`}>
                      <td>{finding.check}</td>
                      <td>{finding.severity}</td>
                      <td className="tfine">{finding.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="tfine" style={{ marginTop: 10 }}>
              {chain.findings_note}
            </p>
          </div>
          )}

          {view === 'Chain' && (
          <div className="tpanel" style={{ padding: 16, overflowX: 'auto' }}>
            <h3>
              {near(chain.strikes).length} strikes
              {range > 0 && <span className="tfine"> of {chain.strikes.length}</span>}
            </h3>
            <table className="ttable chain">
              <thead>
                <tr>
                  <th colSpan={3} style={{ textAlign: 'center' }}>
                    Calls
                  </th>
                  <th style={{ textAlign: 'center' }}>Strike</th>
                  <th colSpan={3} style={{ textAlign: 'center' }}>
                    Puts
                  </th>
                </tr>
                <tr>
                  <th style={{ textAlign: 'right' }}>OI</th>
                  <th style={{ textAlign: 'right' }}>IV</th>
                  <th style={{ textAlign: 'right' }}>Price</th>
                  <th />
                  <th style={{ textAlign: 'right' }}>Price</th>
                  <th style={{ textAlign: 'right' }}>IV</th>
                  <th style={{ textAlign: 'right' }}>OI</th>
                </tr>
              </thead>
              <tbody>
                {near(chain.strikes).map((row) => (
                  <tr key={row.strike} className={row.strike === atm ? 'atm' : undefined}>
                    <td className={`r ${row.call_traded ? '' : 'untraded'}`}>{num(row.call_oi)}</td>
                    <td className={`r ${row.call_traded ? '' : 'untraded'}`}>{pct(row.call_iv)}</td>
                    <td className={`r ${row.call_traded ? '' : 'untraded'}`}>
                      {num(row.call_price)}
                    </td>
                    <td className="r strike">{num(row.strike)}</td>
                    <td className={`r ${row.put_traded ? '' : 'untraded'}`}>
                      {num(row.put_price)}
                    </td>
                    <td className={`r ${row.put_traded ? '' : 'untraded'}`}>{pct(row.put_iv)}</td>
                    <td className={`r ${row.put_traded ? '' : 'untraded'}`}>{num(row.put_oi)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="tfine" style={{ marginTop: 10 }}>
              Dimmed cells never traded today. Their price is NSE&rsquo;s settlement model
              output rather than a transaction, so it means something different from the
              number beside it.
            </p>
          </div>
          )}
        </>
      )}
    </section>
  );
}
