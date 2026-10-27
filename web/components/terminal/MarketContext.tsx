'use client';

/**
 * The context a trader reads before the open (research 120).
 *
 * StockEdge, Finviz and Sensibull all put the same few things on their first
 * screen: where the indices stand over a week to a year, how many stocks are
 * taking part (above their averages, at new highs or lows), which sectors lead,
 * and who holds the index futures. EulerLab lands every input already; this
 * draws them.
 *
 * Every band carries its definition, and the ones their own inventors call weak
 * (PCR, max pain) say so. None of it is a signal: nothing here has passed the
 * gate.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { BreadthName, Horizon, MarketContext } from '@/lib/api';
import './marketcontext.css';

const signed = (fraction: number | null | undefined, digits = 1) =>
  fraction === null || fraction === undefined
    ? '—'
    : `${fraction >= 0 ? '+' : '−'}${Math.abs(fraction * 100).toFixed(digits)}%`;

const points = (fraction: number | null | undefined, digits = 1) =>
  fraction === null || fraction === undefined
    ? '—'
    : `${fraction >= 0 ? '+' : '−'}${Math.abs(fraction * 100).toFixed(digits)} pts`;

const tone = (value: number | null | undefined) =>
  value === null || value === undefined ? '' : value >= 0 ? 'up' : 'dn';

const lakh = (contracts: number) => {
  const sign = contracts >= 0 ? '+' : '−';
  const size = Math.abs(contracts);
  return size >= 1e5 ? `${sign}${(size / 1e5).toFixed(2)}L` : `${sign}${size.toLocaleString('en-IN')}`;
};

/** Fetches once, then again every 5 s while a section is still filling (the
 *  panel loading after a restart, or participant history arriving from the
 *  bucket), at most 24 times. */
export function useMarketContext(): { data: MarketContext | null; error: string } {
  const [data, setData] = useState<MarketContext | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    let tries = 0;
    let timer = 0;
    const read = () => {
      api
        .marketContext()
        .then((next) => {
          if (!alive) return;
          setData(next);
          setError('');
          const pending =
            !next.breadth.available ||
            ('filling' in next.positioning && Boolean(next.positioning.filling));
          if (pending && tries++ < 24) timer = window.setTimeout(read, 5000);
        })
        .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    };
    read();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, []);
  return { data, error };
}

function Missing({ title, reason }: { title: string; reason: string }) {
  return (
    <section>
      <h3 className="report-h">{title}</h3>
      <p className="tfine">Not available: {reason}.</p>
    </section>
  );
}

/** A 0-100 line chart with guides. Small and dependency-free: the series are
 *  a year of daily shares, and a chart library would cost more than it draws.
 *
 *  Drawn in a stretched 0-1000 by 0-100 box at a fixed pixel height, with
 *  strokes that do not scale, and the labels in HTML: in a fixed viewBox the
 *  axis text grew with the panel and read at 20 px on a wide screen. */
function ShareChart({
  days,
  lines,
  guides = [30, 50, 70],
  max = 100,
  height = 150,
}: {
  days: string[];
  lines: { label: string; values: (number | null)[]; role: string }[];
  guides?: number[];
  max?: number;
  height?: number;
}) {
  const n = Math.max(days.length - 1, 1);
  const x = (i: number) => (i / n) * 1000;
  const y = (v: number) => (1 - v / max) * 100;
  const path = (values: (number | null)[]) => {
    let d = '';
    let open = false;
    values.forEach((v, i) => {
      if (v === null || Number.isNaN(v)) {
        open = false;
        return;
      }
      d += `${open ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(2)}`;
      open = true;
    });
    return d;
  };
  const ticks = [0, Math.floor(n / 2), n].filter((i, k, all) => all.indexOf(i) === k);
  return (
    <figure className="mc-chart">
      <div className="mc-plot" style={{ height }}>
        <svg
          viewBox="0 0 1000 100"
          preserveAspectRatio="none"
          role="img"
          aria-label={lines.map((l) => l.label).join(', ')}
        >
          {guides.map((g) => (
            <line key={g} className="mc-guide" x1={0} x2={1000} y1={y(g)} y2={y(g)} />
          ))}
          {lines.map((line) => (
            <path key={line.label} className={`mc-line ${line.role}`} d={path(line.values)} />
          ))}
        </svg>
        {guides.map((g) => (
          <span key={g} className="mc-axis mc-y" style={{ top: `${y(g)}%` }}>
            {g}
          </span>
        ))}
      </div>
      <div className="mc-x">
        {ticks.map((i) => (
          <span key={i} className="mc-axis">
            {days[i]}
          </span>
        ))}
      </div>
      <figcaption>
        {lines.map((line) => (
          <span key={line.label} className="mc-key">
            <i className={line.role} />
            {line.label}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

const HORIZONS: Horizon[] = ['1d', '1w', '1m', '3m', '1y'];

/** Index trend, valuation against history, and VIX. */
export function IndexContext({ ctx }: { ctx: MarketContext }) {
  const strip = ctx.strip;
  const valuation = ctx.valuation;
  if (!strip.available) return <Missing title="Indices" reason={strip.reason} />;
  return (
    <section>
      <h3 className="report-h">
        Indices
        <span className="tfine mc-sub">end of day, to {strip.indices[0]?.as_of}</span>
      </h3>
      <div className="tgrid mc-two">
        <div className="tpanel">
          <h3>Trend</h3>
          <table className="ttable mc-num">
            <thead>
              <tr>
                <th>Index</th>
                <th>Close</th>
                {HORIZONS.map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {strip.indices.map((row) => (
                <tr key={row.name}>
                  <td title={row.name.includes('G-Sec') ? strip.gsec_note : undefined}>{row.name}</td>
                  <td>{row.close.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                  {HORIZONS.map((h) => (
                    <td key={h} className={row.name === 'India VIX' ? '' : tone(row.change[h]) === 'up' ? 'pos' : tone(row.change[h]) === 'dn' ? 'neg' : ''}>
                      {signed(row.change[h])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {strip.vix && (
            <p className="tfine mc-foot" title={strip.vix.note}>
              India VIX {strip.vix.level.toFixed(2)}: higher than{' '}
              {strip.vix.percentile_1y === null ? '—' : `${strip.vix.percentile_1y.toFixed(0)}%`} of
              the past year&apos;s closes (median {strip.vix.median_1y.toFixed(2)}).{' '}
              <abbr className="whyq">?</abbr>
            </p>
          )}
        </div>
        {valuation.available ? (
          <div className="tpanel">
            <h3>Valuation against its own history</h3>
            <table className="ttable mc-num">
              <thead>
                <tr>
                  <th>Index</th>
                  <th>PE</th>
                  <th>PB</th>
                  <th>Div. yield</th>
                </tr>
              </thead>
              <tbody>
                {valuation.indices.map((row) => (
                  <tr key={row.name}>
                    <td>{row.name}</td>
                    {(['pe', 'pb', 'dy'] as const).map((field) => {
                      const cell = row[field];
                      return (
                        <td key={field} title={cell ? `median ${cell.median} since ${cell.since}` : undefined}>
                          {cell ? (
                            <>
                              {cell.value.toFixed(2)}
                              <Rank value={cell.percentile} />
                            </>
                          ) : (
                            '—'
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="tfine mc-foot">
              The bar is the share of past days with a lower value: short is cheap for PE and PB,
              long is cheap for yield. <abbr className="whyq" title={valuation.note}>?</abbr>
            </p>
          </div>
        ) : (
          <div className="tpanel">
            <h3>Valuation</h3>
            <p className="tfine">Not available: {valuation.reason}.</p>
          </div>
        )}
      </div>
    </section>
  );
}

function Rank({ value }: { value: number | null }) {
  if (value === null) return null;
  return (
    <span className="mc-rank" title={`higher than ${value.toFixed(0)}% of past days`}>
      <b>
        <i style={{ width: `${Math.max(2, value)}%` }} />
      </b>
      <em>{value.toFixed(0)}</em>
    </span>
  );
}

const zone = (share: number | null) =>
  share === null ? '' : share >= 70 ? 'mc-hot' : share <= 30 ? 'mc-cold' : '';

/** Participation: averages, new highs and lows, and the lists behind them. */
export function BreadthContext({ ctx }: { ctx: MarketContext }) {
  const b = ctx.breadth;
  if (!b.available) return <Missing title="Breadth" reason={b.reason} />;
  const l = b.latest;
  return (
    <section>
      <h3 className="report-h">
        Breadth
        <span className="tfine mc-sub">
          {b.stocks.toLocaleString('en-IN')} NSE stocks, to {b.as_of}
        </span>
        <abbr className="whyq" title={b.note}>
          ?
        </abbr>
      </h3>
      <div className="tpanel">
        <div className="tfacts mc-facts">
          {(
            [
              ['Above 20-day', l.above_20],
              ['Above 50-day', l.above_50],
              ['Above 200-day', l.above_200],
            ] as const
          ).map(([label, value]) => (
            <div className="tfact" key={label}>
              <span>{label}</span>
              <b className={zone(value)}>{value === null ? '—' : `${value.toFixed(0)}%`}</b>
            </div>
          ))}
          <div className="tfact">
            <span>New highs / lows</span>
            <b>
              <span className="up">{l.new_highs}</span> / <span className="dn">{l.new_lows}</span>
            </b>
          </div>
          <div className="tfact">
            <span>High-Low Index</span>
            <b className={zone(l.high_low_index)}>
              {l.high_low_index === null ? '—' : l.high_low_index.toFixed(0)}
            </b>
          </div>
        </div>
        <ShareChart
          days={b.series.days}
          lines={[
            { label: '% above 50-day', values: b.series.above_50, role: 'mc-a' },
            { label: '% above 200-day', values: b.series.above_200, role: 'mc-b' },
            { label: 'High-Low Index', values: b.series.high_low_index, role: 'mc-c' },
          ]}
        />
        <p className="tfine mc-foot">
          Above 70 is stretched and below 30 washed out (StockCharts); the 200-day line crossing 50
          is the trend bias. A falling line under a rising index means fewer stocks carry it.
        </p>
      </div>
      <div className="tgrid mc-two">
        <NameList title="New 52-week highs" rows={b.new_high_names} found={l.new_highs} />
        <NameList title="New 52-week lows" rows={b.new_low_names} found={l.new_lows} />
      </div>
    </section>
  );
}

function NameList({ title, rows, found }: { title: string; rows: BreadthName[]; found: number }) {
  return (
    <div className="tpanel">
      <h3>
        {title}
        <span className="tfine mc-sub">
          {rows.length} of {found} trade ₹10 Cr a day
        </span>
      </h3>
      {rows.length ? (
        <table className="ttable mc-num">
          <tbody>
            {rows.map((row) => (
              <tr key={row.symbol}>
                <td>{row.symbol}</td>
                <td>{row.close.toLocaleString('en-IN')}</td>
                <td className={tone(row.change_1d) === 'up' ? 'pos' : 'neg'}>{signed(row.change_1d)}</td>
                <td className="mc-quiet">₹{row.turnover_cr} Cr</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="tfine">None among liquid names today.</p>
      )}
    </div>
  );
}

const PHASE: Record<string, string> = {
  leading: 'Leading',
  weakening: 'Weakening',
  lagging: 'Lagging',
  improving: 'Improving',
};

/** Sector indices against Nifty 50. */
export function SectorContext({ ctx }: { ctx: MarketContext }) {
  const s = ctx.sectors;
  if (!s.available) return <Missing title="Sector strength" reason={s.reason} />;
  return (
    <section>
      <h3 className="report-h">
        Sector strength against {s.benchmark}
        <abbr className="whyq" title={s.note}>
          ?
        </abbr>
      </h3>
      <div className="tpanel">
        <table className="ttable mc-num">
          <thead>
            <tr>
              <th>Sector</th>
              <th>Today</th>
              <th>vs Nifty 1w</th>
              <th>1m</th>
              <th>3m</th>
              <th>Phase</th>
            </tr>
          </thead>
          <tbody>
            {s.sectors.map((row) => (
              <tr key={row.name}>
                <td>{row.name.replace(/^Nifty /, '')}</td>
                <td className={tone(row.change_1d) === 'up' ? 'pos' : 'neg'}>{signed(row.change_1d)}</td>
                {(['1w', '1m', '3m'] as const).map((h) => (
                  <td key={h} className={tone(row.relative[h]) === 'up' ? 'pos' : 'neg'}>
                    {signed(row.relative[h])}
                  </td>
                ))}
                <td>
                  {row.phase && (
                    <span className={`mc-phase ${row.phase}`}>
                      {row.rising ? '↗' : '↘'} {PHASE[row.phase]}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="tfine mc-foot">
          Leading: ahead of Nifty over 3 months and gaining over the last week. Weakening: ahead but
          slipping. Improving: behind but gaining. Lagging: behind and slipping. Our own stated rule,
          not a Relative Rotation Graph.
        </p>
      </div>
    </section>
  );
}

/** Who holds index futures, and the option chain's summary numbers. */
export function PositioningContext({ ctx }: { ctx: MarketContext }) {
  const p = ctx.positioning;
  const o = ctx.options;
  return (
    <section>
      <h3 className="report-h">F&amp;O positioning</h3>
      <div className="tgrid mc-two">
        {p.available ? (
          <div className="tpanel">
            <h3>
              Index futures held long
              <span className="tfine mc-sub">
                to {p.as_of}
                {p.filling ? ' · reading history' : ''}
              </span>
              <abbr className="whyq" title={p.note}>
                ?
              </abbr>
            </h3>
            <table className="ttable mc-num">
              <thead>
                <tr>
                  <th>Who</th>
                  <th>Long share</th>
                  <th>1 day</th>
                  <th>5 days</th>
                  <th>vs 1 year</th>
                  <th>Calls net</th>
                  <th>Puts net</th>
                </tr>
              </thead>
              <tbody>
                {p.participants.map((row) => (
                  <tr key={row.participant}>
                    <td>{row.participant}</td>
                    <td>{row.index_futures_long_share === null ? '—' : `${(row.index_futures_long_share * 100).toFixed(1)}%`}</td>
                    <td className={tone(row.change_1d) === 'up' ? 'pos' : 'neg'}>{points(row.change_1d)}</td>
                    <td className={tone(row.change_5d) === 'up' ? 'pos' : 'neg'}>{points(row.change_5d)}</td>
                    <td title={`ranked against ${row.history_days} earlier days`}>
                      <Rank value={row.percentile} />
                    </td>
                    <td>{lakh(row.index_calls_net)}</td>
                    <td>{lakh(row.index_puts_net)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ShareChart
              days={p.series.days}
              height={120}
              guides={[25, 50, 75]}
              lines={[
                { label: 'FII', values: p.series.FII.map((v) => (v === null ? null : v * 100)), role: 'mc-a' },
                { label: 'Client', values: p.series.Client.map((v) => (v === null ? null : v * 100)), role: 'mc-b' },
                { label: 'Pro', values: p.series.Pro.map((v) => (v === null ? null : v * 100)), role: 'mc-c' },
              ]}
            />
          </div>
        ) : (
          <div className="tpanel">
            <h3>Index futures held long</h3>
            <p className="tfine">Not available: {p.reason}.</p>
          </div>
        )}
        {o.available ? (
          <div className="tpanel">
            <h3>
              Nifty options
              <span className="tfine mc-sub">
                expiry {o.expiry}
                {o.days_to_expiry !== null ? `, ${o.days_to_expiry} days out` : ''}
              </span>
              <abbr className="whyq" title={o.note}>
                ?
              </abbr>
            </h3>
            <div className="tfacts mc-facts">
              <div className="tfact">
                <span>Put-call ratio (OI)</span>
                <b>{o.pcr_oi?.toFixed(2) ?? '—'}</b>
                <i>{o.pcr_oi_before !== null ? `${o.pcr_oi_before.toFixed(2)} on ${o.since}` : ''}</i>
              </div>
              <div className="tfact">
                <span>ATM implied vol</span>
                <b>{o.atm_iv !== null ? `${(o.atm_iv * 100).toFixed(1)}%` : '—'}</b>
                <i>{o.atm_iv_before !== null ? `${(o.atm_iv_before * 100).toFixed(1)}% on ${o.since}` : ''}</i>
              </div>
              <div className="tfact">
                <span>ATM straddle</span>
                <b>{o.straddle?.toFixed(1) ?? '—'}</b>
                <i>
                  {o.straddle !== null && o.spot_forward
                    ? `±${((o.straddle / o.spot_forward) * 100).toFixed(1)}% priced move`
                    : ''}
                </i>
              </div>
              <div className="tfact">
                <span>Max pain</span>
                <b>{o.max_pain?.toLocaleString('en-IN') ?? '—'}</b>
                <i>{o.spot_forward ? `forward ${o.spot_forward.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : ''}</i>
              </div>
            </div>
            <p className="tfine mc-foot">
              Sensibull, which popularised PCR and max pain, says they &ldquo;do not have high
              predictive power&rdquo;. Read them as where the open interest sits, not where the
              index goes.
            </p>
          </div>
        ) : (
          <div className="tpanel">
            <h3>Nifty options</h3>
            <p className="tfine">Not available: {o.reason}.</p>
          </div>
        )}
      </div>
    </section>
  );
}

/** Stocks delivered far above their habit today. */
export function DeliveryContext({ ctx }: { ctx: MarketContext }) {
  const d = ctx.delivery;
  if (!d.available) return <Missing title="Delivery spikes" reason={d.reason} />;
  return (
    <section>
      <h3 className="report-h">
        Delivery spikes
        <span className="tfine mc-sub">
          {d.found} names, to {d.as_of}
        </span>
        <abbr className="whyq" title={d.note}>
          ?
        </abbr>
      </h3>
      <div className="tpanel">
        {d.stocks.length ? (
          <table className="ttable mc-num">
            <thead>
              <tr>
                <th>Stock</th>
                <th>Delivered</th>
                <th>Usual</th>
                <th>Times usual</th>
                <th>Today</th>
                <th>Turnover</th>
              </tr>
            </thead>
            <tbody>
              {d.stocks.map((row) => (
                <tr key={row.symbol}>
                  <td>{row.symbol}</td>
                  <td>{row.delivery_pct.toFixed(1)}%</td>
                  <td className="mc-quiet">{row.usual_pct.toFixed(1)}%</td>
                  <td>{row.ratio.toFixed(2)}×</td>
                  <td className={tone(row.change_1d) === 'up' ? 'pos' : 'neg'}>{signed(row.change_1d)}</td>
                  <td className="mc-quiet">₹{row.turnover_cr} Cr</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="tfine">No liquid stock was delivered at 1.5× its usual share today.</p>
        )}
        <p className="tfine mc-foot">
          More shares changed hands to be held rather than squared off the same day. It does not say
          which side was buying.
        </p>
      </div>
    </section>
  );
}
