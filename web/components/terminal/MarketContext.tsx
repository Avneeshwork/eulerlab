'use client';

/**
 * The India dashboard's context, written to be read at a glance (research 120
 * and 121).
 *
 * Retail platforms lead with a word (Tickertape opens with "The market is in
 * Fear zone"), explain each figure where it stands, put an arrow beside every
 * colour, and never show a fall without something to compare it to. So each
 * band here opens with a plain sentence and keeps the table behind a
 * "details" fold.
 *
 * Every word comes from a rule printed beside it (`market_pulse.py`). None of
 * it has passed the gate: it is context, not a signal.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { BreadthName, Horizon, MarketContext, PulseCard } from '@/lib/api';
import './marketcontext.css';

const signed = (fraction: number | null | undefined, digits = 1) => {
  if (fraction === null || fraction === undefined) return '—';
  const size = Math.abs(fraction * 100).toFixed(digits);
  // A move that rounds to nothing has no sign: "−0.0%" read as a fall.
  if (Number(size) === 0) return `${size}%`;
  return `${fraction >= 0 ? '+' : '−'}${size}%`;
};

const points = (fraction: number | null | undefined, digits = 1) =>
  fraction === null || fraction === undefined
    ? '—'
    : `${fraction >= 0 ? '+' : '−'}${Math.abs(fraction * 100).toFixed(digits)} pts`;

/** Colour class and arrow together: colour is never the only signal. */
const move = (value: number | null | undefined, flat = 0.0005) =>
  value === null || value === undefined
    ? { cls: '', arrow: '' }
    : value > flat
      ? { cls: 'pos', arrow: '↑' }
      : value < -flat
        ? { cls: 'neg', arrow: '↓' }
        : { cls: '', arrow: '→' };

function Move({ value, digits = 1 }: { value: number | null | undefined; digits?: number }) {
  const m = move(value);
  return (
    <span className={`mc-move ${m.cls}`}>
      {m.arrow && <i aria-hidden="true">{m.arrow}</i>}
      {signed(value, digits)}
    </span>
  );
}

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

/** A tap-to-open explanation. Native <details>, so it works on a phone, where
 *  a hover tooltip cannot be reached. */
function Explain({
  label = 'How is this worked out?',
  children,
}: {
  label?: string;
  children: React.ReactNode;
}) {
  return (
    <details className="mc-explain">
      <summary>{label}</summary>
      <div className="tfine">{children}</div>
    </details>
  );
}

// --- Overview ------------------------------------------------------------------

const ARROW: Record<PulseCard['direction'], string> = { up: '↑', down: '↓', flat: '→' };

/** Four verdicts, each a word, an arrow, a colour and one sentence. */
export function PulseCards({ ctx }: { ctx: MarketContext }) {
  const p = ctx.pulse;
  if (!p.available) return <Missing title="Market pulse" reason={p.reason} />;
  return (
    <section>
      <h3 className="report-h">Market pulse</h3>
      <div className="mc-pulse">
        {p.cards.map((card) => (
          <article key={card.key} className={`mc-card ${card.tone}`}>
            <span className="mc-card-title">{card.title}</span>
            <b className="mc-card-word">
              <i aria-hidden="true">{ARROW[card.direction]}</i> {card.word}
            </b>
            <p>{card.sentence}</p>
            <Explain label="Rule">{card.rule}</Explain>
          </article>
        ))}
      </div>
      <p className="tfine mc-foot">{p.note}</p>
    </section>
  );
}

/** "What happened today", a few sentences each from one figure. */
export function TodaySummary({ ctx }: { ctx: MarketContext }) {
  if (!ctx.summary.length) return null;
  return (
    <section>
      <h3 className="report-h">What happened today</h3>
      <div className="tpanel mc-summary">
        <ul>
          {ctx.summary.map((line) => (
            <li key={line.topic}>{line.text}</li>
          ))}
        </ul>
        <p className="tfine">Written from the figures on this page by fixed templates, not by an AI.</p>
      </div>
    </section>
  );
}

const HORIZONS: [Horizon, string][] = [
  ['1d', 'Today'],
  ['1w', '1 week'],
  ['1m', '1 month'],
  ['3m', '3 months'],
  ['1y', '1 year'],
];

const PLAIN_NAME: Record<string, string> = {
  'Nifty 50': 'Nifty 50 (large companies)',
  'Nifty Midcap 150': 'Midcap 150 (mid-sized)',
  'Nifty Smallcap 250': 'Smallcap 250 (small)',
  'Nifty 500': 'Nifty 500 (broad market)',
  'Nifty Bank': 'Bank Nifty',
  'India VIX': 'India VIX (fear gauge)',
  'Nifty 10 yr Benchmark G-Sec': '10-year govt bond (price)',
};

/** The indices over a day to a year, and their valuation behind a fold. */
export function IndexContext({ ctx }: { ctx: MarketContext }) {
  const strip = ctx.strip;
  const valuation = ctx.valuation;
  if (!strip.available) return <Missing title="Indices" reason={strip.reason} />;
  return (
    <section>
      <h3 className="report-h">
        Indices
        <span className="tfine mc-sub">closing levels, to {strip.indices[0]?.as_of}</span>
      </h3>
      <div className="tpanel">
        <div className="mc-scroll">
          <table className="ttable mc-num">
            <thead>
              <tr>
                <th>Index</th>
                <th>Close</th>
                {HORIZONS.map(([h, label]) => (
                  <th key={h}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {strip.indices.map((row) => (
                <tr key={row.name}>
                  <td>{PLAIN_NAME[row.name] ?? row.name}</td>
                  <td>{row.close.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                  {HORIZONS.map(([h]) => (
                    <td key={h}>
                      {row.name === 'India VIX' ? signed(row.change[h]) : <Move value={row.change[h]} />}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Explain label="Notes">
          VIX rises when traders pay more for protection, so it is shown without green or red.{' '}
          {strip.gsec_note}
        </Explain>
        {valuation.available && (
          <details className="mc-explain">
            <summary>Valuation: is the market cheap or dear against its own past?</summary>
            <div className="mc-scroll">
              <table className="ttable mc-num">
                <thead>
                  <tr>
                    <th>Index</th>
                    <th>PE</th>
                    <th>PB</th>
                    <th>Dividend yield</th>
                  </tr>
                </thead>
                <tbody>
                  {valuation.indices.map((row) => (
                    <tr key={row.name}>
                      <td>{PLAIN_NAME[row.name] ?? row.name}</td>
                      {(['pe', 'pb', 'dy'] as const).map((field) => {
                        const cell = row[field];
                        return (
                          <td
                            key={field}
                            title={cell ? `median ${cell.median} since ${cell.since}` : undefined}
                          >
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
            </div>
            <p className="tfine">
              The bar shows the share of past days with a lower value. For PE and PB a short bar means
              cheaper than usual; for dividend yield a long bar does. {valuation.note}
            </p>
          </details>
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

// --- Sectors -------------------------------------------------------------------

const PHASE: Record<string, [string, string]> = {
  leading: ['Leading', 'ahead of Nifty and gaining'],
  weakening: ['Weakening', 'ahead of Nifty but slipping'],
  improving: ['Improving', 'behind Nifty but gaining'],
  lagging: ['Lagging', 'behind Nifty and slipping'],
};

type Span = '1w' | '1m' | '3m';
const SPANS: [Span, string][] = [
  ['1w', '1 week'],
  ['1m', '1 month'],
  ['3m', '3 months'],
];

/** Sector indices against Nifty 50, as bars either side of zero. */
export function SectorContext({ ctx }: { ctx: MarketContext }) {
  const [span, setSpan] = useState<Span>('1m');
  const s = ctx.sectors;
  if (!s.available) return <Missing title="Sectors against Nifty" reason={s.reason} />;
  const rows = [...s.sectors].sort((a, b) => (b.relative[span] ?? -9) - (a.relative[span] ?? -9));
  const widest = Math.max(0.01, ...rows.map((r) => Math.abs(r.relative[span] ?? 0)));
  const label = SPANS.find(([key]) => key === span)?.[1] ?? '';
  return (
    <section>
      <h3 className="report-h">Which sectors are beating Nifty</h3>
      <div className="tpanel">
        <div className="mc-seg" role="tablist" aria-label="Period">
          {SPANS.map(([key, text]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={span === key}
              className={span === key ? 'on' : ''}
              onClick={() => setSpan(key)}
            >
              {text}
            </button>
          ))}
        </div>
        <p className="tfine">
          Bars to the right did better than Nifty 50 over {label}; bars to the left did worse.
        </p>
        <ul className="mc-bars">
          {rows.map((row) => {
            const value = row.relative[span];
            const width = value === null ? 0 : (Math.abs(value) / widest) * 50;
            const phase = row.phase ? PHASE[row.phase] : null;
            return (
              <li key={row.name}>
                <span className="mc-bar-name">{row.name.replace(/^Nifty /, '')}</span>
                <span className="mc-bar-track" aria-hidden="true">
                  <i
                    className={value !== null && value >= 0 ? 'pos' : 'neg'}
                    style={
                      value !== null && value >= 0
                        ? { left: '50%', width: `${width}%` }
                        : { right: '50%', width: `${width}%` }
                    }
                  />
                </span>
                <span className="mc-bar-value">
                  <Move value={value} />
                </span>
                <span className="mc-bar-phase">
                  {phase && (
                    <span className={`mc-phase ${row.phase}`} title={phase[1]}>
                      {row.rising ? '↗' : '↘'} {phase[0]}
                    </span>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
        <Explain label="What do Leading, Weakening, Improving and Lagging mean?">
          Leading: ahead of Nifty over 3 months and gaining over the last week. Weakening: ahead but
          slipping. Improving: behind but gaining. Lagging: behind and slipping. Our own stated rule,
          not a Relative Rotation Graph. {s.note}
        </Explain>
      </div>
    </section>
  );
}

// --- Big money -----------------------------------------------------------------

const WHO: Record<string, [string, string]> = {
  FII: ['Foreign institutions (FII)', 'Funds, banks and insurers based outside India.'],
  DII: [
    'Domestic institutions (DII)',
    'Indian mutual funds, banks and insurers. Their shorts are often hedges.',
  ],
  Pro: ['Brokers trading their own money (Pro)', 'Proprietary desks of brokers.'],
  Client: ['Everyone else (Client)', 'Retail traders, wealthy individuals and companies.'],
};

/** A 0-100 line chart with guides, drawn at a fixed pixel height with labels
 *  in HTML so the text stays the same size at any width. */
function ShareChart({
  days,
  lines,
  guides = [25, 50, 75],
  max = 100,
  height = 140,
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

/** Who holds index futures, in words, and what options price. */
export function PositioningContext({ ctx }: { ctx: MarketContext }) {
  const p = ctx.positioning;
  const o = ctx.options;
  return (
    <>
      <section>
        <h3 className="report-h">
          Who is betting on a rise
          {p.available && (
            <span className="tfine mc-sub">
              index futures, to {p.as_of}
              {p.filling ? ' · still reading history' : ''}
            </span>
          )}
        </h3>
        {p.available ? (
          <div className="tpanel">
            <p className="tfine">
              Of every 100 Nifty and Bank Nifty futures contracts each group holds, how many are bets
              that the index will rise. The rest are bets that it will fall.
            </p>
            <ul className="mc-who">
              {p.participants.map((row) => {
                const share = row.index_futures_long_share;
                const long = share === null ? 0 : share * 100;
                const [name, about] = WHO[row.participant] ?? [row.participant, ''];
                return (
                  <li key={row.participant}>
                    <div className="mc-who-head">
                      <b>{name}</b>
                      <span className="tfine">{about}</span>
                    </div>
                    <div
                      className="mc-split"
                      aria-label={`${long.toFixed(0)} bets on a rise, ${(100 - long).toFixed(0)} on a fall`}
                    >
                      <i className="long" style={{ width: `${long}%` }}>
                        {long >= 14 ? `${long.toFixed(0)} rise` : long >= 5 ? long.toFixed(0) : ''}
                      </i>
                      <i className="short" style={{ width: `${100 - long}%` }}>
                        {100 - long >= 14
                          ? `${(100 - long).toFixed(0)} fall`
                          : 100 - long >= 5
                            ? (100 - long).toFixed(0)
                            : ''}
                      </i>
                    </div>
                    <div className="mc-who-facts tfine">
                      <span>
                        1 day <b className={move(row.change_1d).cls}>{points(row.change_1d)}</b>
                      </span>
                      <span>
                        5 days <b className={move(row.change_5d).cls}>{points(row.change_5d)}</b>
                      </span>
                      <span title={`ranked against ${row.history_days} earlier days`}>
                        vs past year <Rank value={row.percentile} />
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
            <ShareChart
              days={p.series.days}
              lines={[
                {
                  label: 'Foreign institutions',
                  values: p.series.FII.map((v) => (v === null ? null : v * 100)),
                  role: 'mc-a',
                },
                {
                  label: 'Everyone else',
                  values: p.series.Client.map((v) => (v === null ? null : v * 100)),
                  role: 'mc-b',
                },
                {
                  label: 'Brokers (Pro)',
                  values: p.series.Pro.map((v) => (v === null ? null : v * 100)),
                  role: 'mc-c',
                },
              ]}
            />
            <Explain>
              Long share = long contracts / (long + short) in index futures, from NSE&apos;s end-of-day
              participant-wise open interest file. The bar after &ldquo;vs past year&rdquo; shows where
              today sits among that group&apos;s own readings (0 lowest, 100 highest). Index options as
              net contracts (long minus short):{' '}
              {p.participants
                .map(
                  (r) =>
                    `${r.participant} calls ${lakh(r.index_calls_net)}, puts ${lakh(r.index_puts_net)}`,
                )
                .join('; ')}
              . {p.note}
            </Explain>
          </div>
        ) : (
          <div className="tpanel">
            <p className="tfine">Not available: {p.reason}.</p>
          </div>
        )}
      </section>

      <section>
        <h3 className="report-h">What Nifty options are pricing</h3>
        {o.available ? (
          <div className="tpanel">
            {o.expected_move && (
              <p className="mc-lead">
                A move of about <b>±{(o.expected_move.share * 100).toFixed(1)}%</b> (±
                {o.expected_move.points.toLocaleString('en-IN', { maximumFractionDigits: 0 })} points)
                by the {o.expiry} expiry
                {o.days_to_expiry !== null ? `, ${o.days_to_expiry} days away` : ''}.
              </p>
            )}
            <div className="tfacts mc-facts">
              <div className="tfact">
                <span>Put-call ratio</span>
                <b>{o.pcr_oi?.toFixed(2) ?? '—'}</b>
                <i>{o.pcr_oi_before !== null ? `was ${o.pcr_oi_before.toFixed(2)} on ${o.since}` : ''}</i>
              </div>
              <div className="tfact">
                <span>Implied volatility</span>
                <b>{o.atm_iv !== null ? `${(o.atm_iv * 100).toFixed(1)}%` : '—'}</b>
                <i>
                  {o.atm_iv_before !== null
                    ? `was ${(o.atm_iv_before * 100).toFixed(1)}% on ${o.since}`
                    : ''}
                </i>
              </div>
              <div className="tfact">
                <span>Max pain</span>
                <b>{o.max_pain?.toLocaleString('en-IN') ?? '—'}</b>
                <i>
                  {o.spot_forward
                    ? `Nifty ${o.spot_forward.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
                    : ''}
                </i>
              </div>
            </div>
            <Explain label="What do these mean, and how much do they matter?">
              Expected move: the price of the at-the-money call plus put, as a share of Nifty. Put-call
              ratio: open put contracts per open call contract. Implied volatility: the yearly swing the
              option prices assume. Max pain: the strike where option buyers as a group would lose most
              at expiry. Sensibull, which popularised PCR and max pain, says they &ldquo;do not have high
              predictive power&rdquo;: read them as where the open interest sits, not where the index
              goes.
            </Explain>
          </div>
        ) : (
          <div className="tpanel">
            <p className="tfine">Not available: {o.reason}.</p>
          </div>
        )}
      </section>
    </>
  );
}

// --- Stocks to watch ------------------------------------------------------------

function NameList({
  title,
  hint,
  rows,
  found,
  tag,
}: {
  title: string;
  hint: string;
  rows: BreadthName[];
  found: number;
  tag: string;
}) {
  return (
    <div className="tpanel">
      <h3>
        {title}
        <span className="tfine mc-sub">
          {rows.length} of {found}
        </span>
      </h3>
      <p className="tfine">{hint}</p>
      {rows.length ? (
        <table className="ttable mc-num">
          <tbody>
            {rows.map((row) => (
              <tr key={row.symbol}>
                <td>
                  {row.symbol} <span className="mc-tag">{tag}</span>
                </td>
                <td>{row.close.toLocaleString('en-IN')}</td>
                <td>
                  <Move value={row.change_1d} />
                </td>
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

/** New highs and lows and delivery spikes, beside the movers on the same tab. */
export function WatchContext({ ctx }: { ctx: MarketContext }) {
  const b = ctx.breadth;
  const d = ctx.delivery;
  return (
    <>
      {b.available ? (
        <section>
          <h3 className="report-h">
            Breaking out, breaking down
            <span className="tfine mc-sub">to {b.as_of}</span>
          </h3>
          <div className="tgrid mc-two">
            <NameList
              title="New 52-week highs"
              hint="Closed above every close of the past year. Shown when they trade ₹10 crore a day or more."
              rows={b.new_high_names}
              found={b.latest.new_highs}
              tag="new high"
            />
            <NameList
              title="New 52-week lows"
              hint="Closed below every close of the past year. Shown when they trade ₹10 crore a day or more."
              rows={b.new_low_names}
              found={b.latest.new_lows}
              tag="new low"
            />
          </div>
        </section>
      ) : (
        <Missing title="New highs and lows" reason={b.reason} />
      )}
      {d.available ? (
        <section>
          <h3 className="report-h">
            Bought to keep
            <span className="tfine mc-sub">
              {d.found} names, to {d.as_of}
            </span>
          </h3>
          <div className="tpanel">
            <p className="tfine">
              Stocks where far more of today&apos;s trading was taken as delivery than usual: shares
              bought to hold, not squared off the same day.
            </p>
            {d.stocks.length ? (
              <div className="mc-scroll">
                <table className="ttable mc-num">
                  <thead>
                    <tr>
                      <th>Stock</th>
                      <th>Delivered today</th>
                      <th>Usually</th>
                      <th>Today</th>
                      <th>Turnover</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.stocks.map((row) => (
                      <tr key={row.symbol}>
                        <td>
                          {row.symbol}{' '}
                          <span className="mc-tag">{row.ratio.toFixed(1)}× delivery</span>
                        </td>
                        <td>{row.delivery_pct.toFixed(0)}%</td>
                        <td className="mc-quiet">{row.usual_pct.toFixed(0)}%</td>
                        <td>
                          <Move value={row.change_1d} />
                        </td>
                        <td className="mc-quiet">₹{row.turnover_cr} Cr</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="tfine">No liquid stock was delivered at 1.5× its usual share today.</p>
            )}
            <Explain>
              Delivery % is the share of traded shares settled by delivery. Listed when today&apos;s is
              at least 1.5× its average over the previous {d.sessions} sessions, among names trading
              ₹10 crore a day. It does not say which side was buying.
            </Explain>
          </div>
        </section>
      ) : (
        <Missing title="Bought to keep" reason={d.reason} />
      )}
    </>
  );
}
