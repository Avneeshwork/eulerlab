'use client';

/**
 * FII/DII cash flows: what foreign and domestic institutions bought and sold
 * in the cash market, from NSE's provisional evening figures (ADR-098).
 *
 * Self-contained on purpose: it fetches its own route (`/api/fii-dii`), owns
 * its stylesheet (`fiidii.css`), and takes every colour from the `--fd-*`
 * tokens declared there, so it can be moved or restyled without touching the
 * other dashboard bands. Numbers and pictures only; words live behind the
 * info button (ADR-082). Context, not a signal: nothing here passed the gate.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { FiiDiiFlows as Flows, FiiDiiGroup, FiiDiiMonth } from '@/lib/api';
import { Info } from './ui';
import './fiidii.css';

/** ₹ crore with a sign, Indian grouping: +2,535 Cr. */
export const crore = (value: number | null | undefined, digits = 0) => {
  if (value === null || value === undefined) return '—';
  const size = Math.abs(value).toLocaleString('en-IN', { maximumFractionDigits: digits });
  if (Number(Math.abs(value).toFixed(digits)) === 0) return `${size} Cr`;
  return `${value > 0 ? '+' : '−'}${size} Cr`;
};

const tone = (value: number | null | undefined) =>
  value === null || value === undefined || value === 0 ? '' : value > 0 ? 'fd-buy' : 'fd-sell';

/** Bought or sold, said in words beside the colour: colour is never the only signal. */
const verb = (value: number) => (value > 0 ? 'bought' : value < 0 ? 'sold' : 'flat');

function Tile({ name, role, g }: { name: string; role: 'fd-fii' | 'fd-dii'; g: FiiDiiGroup }) {
  const total = g.buy + g.sell || 1;
  const days = Math.abs(g.streak);
  return (
    <div className={`fd-tile ${role}`}>
      <div className="fd-tile-head">
        <i className="fd-dot" aria-hidden="true" />
        <span>{name}</span>
        <span className={`fd-verb ${tone(g.net)}`}>{verb(g.net)}</span>
      </div>
      <b className={`fd-big ${tone(g.net)}`}>{crore(g.net)}</b>
      <div className="fd-split" role="img" aria-label={`bought ${crore(g.buy)}, sold ${crore(g.sell)}`}>
        <span className="fd-split-buy" style={{ width: `${(g.buy / total) * 100}%` }} />
        <span className="fd-split-sell" />
      </div>
      <dl className="fd-facts">
        <div>
          <dt>Bought</dt>
          <dd>{g.buy.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</dd>
        </div>
        <div>
          <dt>Sold</dt>
          <dd>{g.sell.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</dd>
        </div>
        <div>
          <dt>5 days</dt>
          <dd className={tone(g.net_5d)}>{crore(g.net_5d)}</dd>
        </div>
        <div>
          <dt>Month</dt>
          <dd className={tone(g.net_month)}>{crore(g.net_month)}</dd>
        </div>
        <div>
          <dt>Run</dt>
          <dd className={tone(g.streak)}>
            {days ? `${days} day${days > 1 ? 's' : ''} ${g.streak > 0 ? 'buying' : 'selling'}` : '—'}
          </dd>
        </div>
      </dl>
    </div>
  );
}

/** Each session's net as a bar from zero, FII and DII side by side. */
function DailyBars({ days, fii, dii }: { days: string[]; fii: number[]; dii: number[] }) {
  const top = Math.max(1, ...fii.map(Math.abs), ...dii.map(Math.abs));
  const n = days.length;
  const slot = 1000 / Math.max(n, 1);
  const width = Math.max(slot * 0.38, 1);
  const y = (v: number) => 50 - (v / top) * 48;
  const bar = (v: number, i: number, k: number, role: string) => (
    <rect
      key={`${role}${i}`}
      className={role}
      x={i * slot + slot * 0.1 + k * width}
      width={width}
      y={Math.min(y(v), 50)}
      height={Math.max(Math.abs(y(v) - 50), 0.4)}
    >
      <title>{`${days[i]} ${role === 'fd-fii' ? 'FII' : 'DII'} ${crore(v)}`}</title>
    </rect>
  );
  return (
    <figure className="fd-chart">
      <svg viewBox="0 0 1000 100" preserveAspectRatio="none" role="img" aria-label="Daily net, FII and DII">
        <line className="fd-zero" x1={0} x2={1000} y1={50} y2={50} />
        {fii.map((v, i) => bar(v, i, 0, 'fd-fii'))}
        {dii.map((v, i) => bar(v, i, 1, 'fd-dii'))}
      </svg>
      <div className="fd-axis">
        <span>{days[0]}</span>
        <span>±{top.toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr</span>
        <span>{days[n - 1]}</span>
      </div>
    </figure>
  );
}

function Months({ rows }: { rows: FiiDiiMonth[] }) {
  const top = Math.max(1, ...rows.flatMap((r) => [Math.abs(r.fii), Math.abs(r.dii)]));
  const half = (v: number) => `${(Math.abs(v) / top) * 50}%`;
  return (
    <table className="fd-months">
      <thead>
        <tr>
          <th>Month</th>
          <th>FII</th>
          <th>DII</th>
          <th className="fd-num">Days</th>
        </tr>
      </thead>
      <tbody>
        {[...rows].reverse().map((r) => (
          <tr key={r.month}>
            <td>{r.month}</td>
            {(
              [
                ['fd-fii', r.fii],
                ['fd-dii', r.dii],
              ] as const
            ).map(([role, v]) => (
              <td key={role}>
                <span className="fd-mbar">
                  <span
                    className={role}
                    style={{ width: half(v), left: v >= 0 ? '50%' : `calc(50% - ${half(v)})` }}
                  />
                </span>
                <span className={`fd-mval ${tone(v)}`}>{crore(v)}</span>
              </td>
            ))}
            <td className="fd-num">{r.days}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function FiiDiiFlows() {
  const [data, setData] = useState<Flows | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    api
      .fiiDii()
      .then((next) => alive && setData(next))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, []);

  const info = (
    <>
      What foreign (FII, including FPI) and domestic institutions (DII: Indian mutual funds, banks,
      insurers, pension funds) bought and sold in the NSE, BSE and MSEI cash market, in ₹ crore.
      These are NSE&apos;s provisional figures, published each evening for that day only; NSDL
      revises the FPI number later. Green is net buying, red net selling. Run is how many sessions
      in a row the group has stayed on the same side. The chart shows each day&apos;s net; the table
      sums each month from the days held here, so a month that started before capture began is
      partial (see Days). Context, not a signal: nothing built on these has passed the gate.
      {data?.available ? ` Held: ${data.days_held} day(s) since ${data.first_day}. ${data.note}` : ''}
    </>
  );

  return (
    <section className="fd">
      <h3 className="report-h fd-h">
        FII / DII cash
        {data?.available && <span className="tfine fd-sub">{data.as_of}</span>}
        <Info>{data && !data.available ? `Not available: ${data.reason}.` : info}</Info>
      </h3>
      {error ? (
        <div className="tpanel fd-empty">Could not read the flows: {error}</div>
      ) : !data ? (
        <div className="tpanel fd-empty">Reading flows…</div>
      ) : !data.available ? (
        <div className="tpanel fd-empty">No day captured yet</div>
      ) : (
        <div className="tpanel fd-body">
          <div className="fd-tiles">
            <Tile name="FII" role="fd-fii" g={data.fii} />
            <Tile name="DII" role="fd-dii" g={data.dii} />
          </div>
          {data.series.days.length > 1 && (
            <DailyBars days={data.series.days} fii={data.series.fii} dii={data.series.dii} />
          )}
          <div className="fd-key">
            <span>
              <i className="fd-dot fd-fii" aria-hidden="true" />
              FII
            </span>
            <span>
              <i className="fd-dot fd-dii" aria-hidden="true" />
              DII
            </span>
          </div>
          <Months rows={data.months} />
        </div>
      )}
    </section>
  );
}
