'use client';

/**
 * One company's page: what is held about it, on one screen.
 *
 * Built from the screener.in fundamentals file, the price panel and the news
 * archive (`features/company_page.py`). Modelled on a broker's stock page, with
 * one difference: panels that page fills from data not held here (analyst
 * ratings, targets, estimates, a DCF) are listed as not held, not drawn empty
 * and not filled with a guess.
 */

import Link from 'next/link';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  companyPage,
  companySearch,
  type CompanyHit,
  type CompanyPage,
  type CompanyTable,
  type FairValue,
} from '@/lib/api';
import './company.css';

/* ---------- numbers ---------- */

const DASH = '—';
const fixed = (value: number, digits = 2) =>
  value.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const price = (value?: number | null) => (value == null ? DASH : `₹${fixed(value)}`);
const plain = (value?: number | null, digits = 2) => (value == null ? DASH : fixed(value, digits));
const percent = (value?: number | null, digits = 1) =>
  value == null ? DASH : `${fixed(value, digits)}%`;
const share = (value?: number | null) =>
  value == null ? DASH : `${value >= 0 ? '+' : ''}${fixed(value * 100, 1)}%`;
/** ₹ crore, as the statements print it. */
const crore = (value?: number | null) =>
  value == null ? DASH : `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`;
/** A ₹ amount as crore, or lakh crore once it is large. */
function bigRupees(value?: number | null): string {
  if (value == null) return DASH;
  const inCrore = value / 1e7;
  return inCrore >= 1e5 ? `₹${fixed(inCrore / 1e5)} lakh Cr` : crore(inCrore);
}
function volume(value?: number | null): string {
  if (value == null) return DASH;
  if (value >= 1e7) return `${fixed(value / 1e7)} Cr`;
  if (value >= 1e5) return `${fixed(value / 1e5)} lakh`;
  return value.toLocaleString('en-IN');
}
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
/** `2026-03-31` as `Mar 26`. */
function period(iso: string): string {
  const [year, month] = iso.split('-');
  return `${MONTHS[Number(month) - 1] ?? ''} ${year.slice(2)}`;
}
const longDate = (iso: string) => {
  const [year, month, day] = iso.slice(0, 10).split('-');
  return `${Number(day)} ${MONTHS[Number(month) - 1]} ${year}`;
};

/* ---------- small pieces ---------- */

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="co-stat">
      <span>{label}</span>
      <b>{value}</b>
      {note && <small>{note}</small>}
    </div>
  );
}

function FairValuePanel({ value, series }: { value: FairValue; series: [string, number][] }) {
  const coe = value.cost_of_equity;
  const assumptions = value.assumptions;
  const models = value.models ?? {};
  const upperCase = assumptions?.valuation_scenarios?.high;
  const modelNames: Record<string, string> = {
    residual_income: 'Central case · residual income',
    residual_income_low: 'Lower historical ROE case',
    residual_income_high: upperCase?.terminal_mode === 'persistent_excess_returns'
      ? 'Upper ROE · persistent returns'
      : 'Upper historical ROE case',
    peer_pe: 'Peer P/E',
    peer_pb: 'Peer P/B cross-check',
  };
  if (value.status !== 'available' || value.fair_value_per_share == null) {
    return (
      <section className="tpanel co-fair-value">
        <div className="co-fv-heading">
          <div>
            <p className="co-kicker">Valuation estimate</p>
            <h3>Fair value</h3>
          </div>
          <span className="co-fv-badge is-low">Unavailable</span>
        </div>
        <p className="tfine">{value.reason || 'Required inputs are not held for this company.'}</p>
        {(value.warnings ?? []).length > 0 && (
          <details className="co-fv-details">
            <summary>Data notes ({value.warnings?.length})</summary>
            <ul className="co-fv-warnings">
              {(value.warnings ?? []).map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          </details>
        )}
      </section>
    );
  }
  const upside = value.upside;
  const marketPrice = value.current_price;
  const pricePosition = value.model_range && marketPrice != null
    ? marketPrice < value.model_range.low
      ? 'Below model range'
      : marketPrice > value.model_range.high
        ? 'Above model range'
        : 'Within model range'
    : upside == null
      ? DASH
      : share(upside);
  const centralGapNote = upside == null
    ? undefined
    : `Central case ${share(upside)}`;
  const modelRows = Object.entries(models).filter(
    ([key, amount]) => key !== 'composite' && amount != null,
  );
  const coePercent = (amount?: number) => (amount == null ? DASH : `${fixed(amount * 100, 1)}%`);

  return (
    <section className="tpanel co-fair-value">
      <div className="co-fv-heading">
        <div>
          <h3>Fair value</h3>
        </div>
        <span className="co-fv-badge is-low">Low confidence</span>
      </div>
      {value.confidence_reason && <p className="tfine">{value.confidence_reason}</p>}
      <div className="co-fv-summary">
        <Stat label="Current price" value={price(value.current_price)} />
        <Stat label="Central scenario" value={price(value.fair_value_per_share)} />
        <Stat
          label={value.model_range ? 'Price vs scenarios' : 'Gap vs central case'}
          value={pricePosition}
          note={value.model_range ? centralGapNote : undefined}
        />
        <Stat
          label={value.range_type === 'roe_persistence_scenarios' ? 'ROE scenario range' : 'Scenario range'}
          value={
            value.model_range
              ? `${price(value.model_range.low)} – ${price(value.model_range.high)}`
              : DASH
          }
        />
      </div>
      <PriceChart series={series} fairValue={value} />
      {modelRows.length > 0 && (
        <div className="co-fv-models">
          {modelRows.map(([key, amount]) => (
            <div key={key}>
              <span>{modelNames[key] || key}</span>
              <b>{price(amount)}</b>
            </div>
          ))}
        </div>
      )}
      <details className="co-fv-details">
        <summary>Assumptions &amp; data notes</summary>
        <div className="co-fv-assumptions">
          <p>
            Cost of equity {coePercent(coe?.rate)} · India 10Y {coePercent(coe?.risk_free_rate)} ·
            {' '}betas M/S/H {plain(coe?.betas.MF)} / {plain(coe?.betas.SMB)} /{' '}
            {plain(coe?.betas.HML)} ({coe?.beta_observations ?? 0} observations).
          </p>
          <p>
            {coe?.method || 'Cost of equity method'} · India ERP{' '}
            {coe?.premia ? percent(coe.premia.market * 100) : DASH}
            {coe?.market_erp_as_of ? ` as of ${coe.market_erp_as_of}` : ''} ·{' '}
            {coe?.factor_release || 'Factor data'}
            {coe?.factor_through ? ` through ${coe.factor_through}` : ''}
            {coe?.premia ? ` · SMB/HML premia ${percent(coe.premia.size * 100)} / ${percent(coe.premia.value * 100)}` : ''}.
          </p>
          {assumptions && (
            <p>
              {assumptions.forecast_method} Payout {percent(assumptions.payout_ratio * 100)}
              {assumptions.payout_assumed ? ' (assumed)' : ''}.
            </p>
          )}
          {assumptions && (
            <p>
              TTM ROE proxy {percent((assumptions.current_roe ?? 0) * 100)} · year 5 ROE anchor{' '}
              {percent((assumptions.valuation_scenarios?.base?.year_5_roe_anchor ?? 0) * 100)} ·{' '}
              year 10 ROE converges to cost of equity {percent((assumptions.valuation_scenarios?.base?.long_run_roe ?? 0) * 100)}.
            </p>
          )}
          {assumptions?.terminal_roe_source && (
            <p>ROE anchor: {assumptions.terminal_roe_source}.</p>
          )}
          {assumptions && (
            <div className="co-fv-sensitivity">
              {Object.entries(assumptions.sensitivity).map(([key, amount]) => (
                <div key={key}>
                  <span>{key.replaceAll('_', ' ')}</span>
                  <b>{price(amount)}</b>
                </div>
              ))}
            </div>
          )}
          {(value.warnings ?? []).map((warning) => <p key={warning}>{warning}</p>)}
          <p className="co-fv-provenance">
            Fundamentals {value.fundamentals_as_of || DASH} · price {value.price_as_of || DASH} ·{' '}
            {value.model_version}
          </p>
          <p className="tfine">Model estimate for research, not investment advice.</p>
        </div>
      </details>
    </section>
  );
}

function Search() {
  const [text, setText] = useState('');
  const [hits, setHits] = useState<CompanyHit[]>([]);
  useEffect(() => {
    const wanted = text.trim();
    if (wanted.length < 2) {
      setHits([]);
      return;
    }
    let live = true;
    const timer = window.setTimeout(() => {
      companySearch(wanted)
        .then((found) => live && setHits(found.rows))
        .catch(() => live && setHits([]));
    }, 150);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [text]);
  return (
    <div className="co-search">
      <input
        value={text}
        placeholder="Find a company by name or symbol"
        aria-label="Find a company"
        onChange={(event) => setText(event.target.value)}
      />
      {hits.length > 0 && (
        <ul>
          {hits.map((hit) => (
            <li key={hit.symbol}>
              <Link href={`/terminal/company/${encodeURIComponent(hit.symbol)}`}>
                <b>{hit.symbol}</b>
                <span>{hit.name || hit.industry}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ---------- price chart ---------- */

const RANGES: [string, number][] = [
  ['1M', 21],
  ['3M', 63],
  ['6M', 126],
  ['1Y', 252],
  ['3Y', 756],
  ['5Y', 1260],
];
const W = 900;
const H = 260;
const PAD = { top: 12, right: 56, bottom: 22, left: 4 };

function PriceChart({ series, fairValue }: { series: [string, number][]; fairValue?: FairValue }) {
  const [range, setRange] = useState('1Y');
  const [hover, setHover] = useState<number | null>(null);
  const frame = useRef<SVGSVGElement>(null);
  const shown = useMemo(() => {
    const days = RANGES.find(([name]) => name === range)?.[1] ?? 252;
    return series.slice(-days);
  }, [series, range]);

  if (shown.length < 2) return <p className="tfine">No price history is held for this company.</p>;

  const values = shown.map(([, close]) => close);
  const modelRange = fairValue?.model_range;
  const target = fairValue?.fair_value_per_share ?? null;
  const overlay = Boolean(modelRange && target != null);
  const hasRoeScenarios = fairValue?.range_type === 'roe_persistence_scenarios';
  const upperCasePersists = fairValue?.assumptions?.valuation_scenarios?.high?.terminal_mode
    === 'persistent_excess_returns';
  const rangeLabel = hasRoeScenarios ? 'ROE scenario range' : 'value range';
  const chartRight = W - PAD.right - (overlay ? 190 : 0);
  const chartValues = overlay ? [...values, modelRange!.low, modelRange!.high, target!] : values;
  const low = Math.min(...chartValues);
  const high = Math.max(...chartValues);
  const span = high - low || 1;
  const x = (i: number) => PAD.left + (i / (shown.length - 1)) * (chartRight - PAD.left);
  const y = (v: number) => PAD.top + (1 - (v - low) / span) * (H - PAD.top - PAD.bottom);
  const line = shown.map(([, v], i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const area = `${line.join(' ')} L${x(shown.length - 1)},${H - PAD.bottom} L${x(0)},${H - PAD.bottom} Z`;
  const change = values[values.length - 1] / values[0] - 1;
  const at = hover == null ? null : shown[hover];
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * (shown.length - 1)));

  function move(event: React.PointerEvent<SVGSVGElement>) {
    const box = frame.current?.getBoundingClientRect();
    if (!box) return;
    const inside = ((event.clientX - box.left) / box.width) * W;
    const index = Math.round(((inside - PAD.left) / (chartRight - PAD.left)) * (shown.length - 1));
    setHover(Math.max(0, Math.min(shown.length - 1, index)));
  }

  return (
    <div className="co-chart">
      <div className="co-chart-head">
        <p>
          {at ? (
            <>
              <b>{price(at[1])}</b> <span>{longDate(at[0])}</span>
            </>
          ) : (
            <>
              <b className={change >= 0 ? 'is-up' : 'is-down'}>{share(change)}</b>{' '}
              <span>
                over {range}, {longDate(shown[0][0])} to {longDate(shown[shown.length - 1][0])}
              </span>
            </>
          )}
        </p>
        <div className="co-ranges" role="group" aria-label="Chart range">
          {RANGES.map(([name, days]) => (
            <button
              key={name}
              type="button"
              className={name === range ? 'is-on' : ''}
              disabled={series.length < Math.min(days, 22)}
              onClick={() => setRange(name)}
            >
              {name}
            </button>
          ))}
        </div>
      </div>
      <svg
        ref={frame}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Adjusted closing price over ${range}: ${share(change)}${overlay ? `; fair value ${price(target!)}, ${rangeLabel} ${price(modelRange!.low)} to ${price(modelRange!.high)}` : ''}`}
        onPointerMove={move}
        onPointerLeave={() => setHover(null)}
      >
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line
              className="co-grid"
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(low + f * span)}
              y2={y(low + f * span)}
            />
            <text className="co-axis" x={W - PAD.right + 6} y={y(low + f * span) + 4}>
              {fixed(low + f * span, 0)}
            </text>
          </g>
        ))}
        {overlay && modelRange && target != null && (
          <g className="co-valuation-zone">
            <line
              className="co-valuation-divider"
              x1={chartRight + 10}
              x2={chartRight + 10}
              y1={PAD.top}
              y2={H - PAD.bottom}
            />
            <text className="co-valuation-label" x={chartRight + 23} y={PAD.top + 12}>
              ROE SCENARIOS
            </text>
            <text className="co-valuation-sub" x={chartRight + 23} y={PAD.top + 27}>
              low fade · {upperCasePersists ? 'upper persists' : 'upper fade'}
            </text>
            <rect
              className="co-valuation-band"
              x={chartRight + 23}
              y={y(modelRange.high)}
              width={W - PAD.right - chartRight - 35}
              height={Math.max(2, y(modelRange.low) - y(modelRange.high))}
              rx="4"
            />
            <line
              className="co-valuation-target"
              x1={chartRight + 23}
              x2={W - PAD.right - 5}
              y1={y(target)}
              y2={y(target)}
            />
            <circle className="co-valuation-dot" cx={chartRight + 23} cy={y(target)} r="4" />
            <text className="co-valuation-value" x={chartRight + 23} y={y(target) - 9}>
              {price(target)}
            </text>
          </g>
        )}
        {ticks.map((i) => (
          <text
            key={i}
            className="co-axis"
            x={x(i)}
            y={H - 6}
            textAnchor={i === 0 ? 'start' : i === shown.length - 1 ? 'end' : 'middle'}
          >
            {period(shown[i][0])}
          </text>
        ))}
        <path className="co-area" d={area} />
        <path className="co-line" d={line.join(' ')} />
        {hover != null && at && (
          <g>
            <line
              className="co-cross"
              x1={x(hover)}
              x2={x(hover)}
              y1={PAD.top}
              y2={H - PAD.bottom}
            />
            <circle className="co-dot" cx={x(hover)} cy={y(at[1])} r={4} />
          </g>
        )}
      </svg>
      {overlay && (
        <div className="co-chart-legend" aria-label="Chart legend">
          <span><i className="is-price" /> Share price</span>
          <span><i className="is-fair" /> Fair value</span>
          <span><i className="is-range" /> {hasRoeScenarios ? 'ROE scenario range' : 'Value range'}</span>
        </div>
      )}
      <p className="tfine">
        Closing prices adjusted for splits and bonuses
        {overlay && hasRoeScenarios
          ? ` · range reflects historical ROE levels${upperCasePersists ? ' and a persistent-return upper case' : ' with both cases fading to cost of equity'}`
          : ''}.
      </p>
    </div>
  );
}

/* ---------- bars: one measure, by period ---------- */

function Bars({ title, table, label }: { title: string; table: CompanyTable; label: string }) {
  const row = table.rows.find((r) => r.label === label);
  const points = (row?.values ?? [])
    .map((value, i) => ({ value, when: table.periods[i] }))
    .filter((p): p is { value: number; when: string } => p.value != null)
    .slice(-8);
  if (points.length < 2) return null;
  const top = Math.max(...points.map((p) => p.value), 0);
  const bottom = Math.min(...points.map((p) => p.value), 0);
  const span = top - bottom || 1;
  const BH = 150;
  const zero = (top / span) * BH;
  return (
    <figure className="co-bars">
      <figcaption>{title}</figcaption>
      <div className="co-bars-plot" style={{ height: BH }}>
        <i className="co-zero" style={{ top: zero }} />
        {points.map((p) => {
          const size = (Math.abs(p.value) / span) * BH;
          return (
            <div
              key={p.when}
              className="co-bar-slot"
              title={`${period(p.when)}: ${crore(p.value)}`}
            >
              <span
                className={`co-bar${p.value < 0 ? ' is-neg' : ''}`}
                style={{ height: Math.max(size, 2), top: p.value >= 0 ? zero - size : zero }}
              />
            </div>
          );
        })}
      </div>
      <div className="co-bars-axis">
        {points.map((p) => (
          <span key={p.when}>{period(p.when)}</span>
        ))}
      </div>
      <p className="tfine">
        Latest {crore(points[points.length - 1].value)}, {period(points[points.length - 1].when)}.
        Hover a bar for its figure.
      </p>
    </figure>
  );
}

/* ---------- statements ---------- */

const STATEMENTS: [string, string][] = [
  ['quarters', 'Quarterly results'],
  ['profit-loss', 'Profit and loss'],
  ['balance-sheet', 'Balance sheet'],
  ['cash-flow', 'Cash flow'],
  ['ratios', 'Ratios'],
  ['shareholding', 'Shareholding'],
];

function Statements({ tables }: { tables: Record<string, CompanyTable> }) {
  const [which, setWhich] = useState('quarters');
  const table = tables[which];
  const periods = table?.periods.slice(-8) ?? [];
  const skip = (table?.periods.length ?? 0) - periods.length;
  const isShare = which === 'shareholding';
  return (
    <section className="tpanel">
      <div className="co-tabs" role="tablist" aria-label="Statement">
        {STATEMENTS.map(([id, name]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={id === which}
            className={id === which ? 'is-on' : ''}
            onClick={() => setWhich(id)}
          >
            {name}
          </button>
        ))}
      </div>
      {!table || table.rows.length === 0 ? (
        <p className="tfine">This statement is not in the file for this company.</p>
      ) : (
        <div className="co-table-wrap">
          <table className="co-table">
            <thead>
              <tr>
                <th scope="col">{isShare ? 'Holder, % of shares' : '₹ crore'}</th>
                {periods.map((p) => (
                  <th key={p} scope="col">
                    {period(p)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row) => (
                <tr key={row.label}>
                  <th scope="row">{row.label}</th>
                  {row.values.slice(skip).map((value, i) => (
                    <td key={periods[i]} className={value != null && value < 0 ? 'is-neg' : ''}>
                      {value == null
                        ? DASH
                        : value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/* ---------- the page ---------- */

export default function CompanyPageView({ params }: { params: { symbol: string } }) {
  const symbol = decodeURIComponent(params.symbol).toUpperCase();
  const [page, setPage] = useState<CompanyPage | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    setPage(null);
    setError('');
    companyPage(symbol)
      .then((reply) => {
        if (!live) return;
        if (reply.ok) setPage(reply);
        else setError(reply.error);
      })
      .catch((reason) => live && setError(String(reason)));
    return () => {
      live = false;
    };
  }, [symbol]);

  const top = (
    <div className="co-top">
      <Link href="/terminal" className="co-back">
        ← Back
      </Link>
      <Search />
    </div>
  );

  if (error)
    return (
      <main className="co-page">
        {top}
        <p className="co-error">{error}</p>
      </main>
    );
  if (!page)
    return (
      <main className="co-page">
        {top}
        <p className="tfine">Loading {symbol}…</p>
      </main>
    );

  const { profile, metrics, price: px, peers } = page;
  const move = px.close != null && px.previous_close ? px.close / px.previous_close - 1 : null;
  const position =
    px.close != null && px.high_52w != null && px.low_52w != null && px.high_52w > px.low_52w
      ? Math.max(0, Math.min(1, (px.close - px.low_52w) / (px.high_52w - px.low_52w)))
      : null;

  return (
    <main className="co-page">
      {top}
      <div className="co-grid-main">
        <aside className="co-side">
          <section className="tpanel co-id">
            <h1>{page.name || symbol}</h1>
            <p className="co-sym">
              NSE: {symbol}
              {profile.industry && ` · ${profile.industry}`}
            </p>
            <div className="co-price">
              <b>{price(px.close ?? profile.price)}</b>
              {move != null && (
                <span className={move >= 0 ? 'is-up' : 'is-down'}>
                  {move >= 0 ? '▲' : '▼'} {share(move)}
                </span>
              )}
            </div>
            <p className="tfine">
              {px.day ? `Close on ${longDate(px.day)}` : 'Price from the fundamentals file'}
              {px.previous_close != null && `, previous ${price(px.previous_close)}`}
            </p>
            {px.provisional && (
              <p className="tfine co-provisional">
                {longDate(px.provisional.d)}: {price(px.provisional.close)} at 15:29 from minute
                bars ({share(px.close ? px.provisional.close / px.close - 1 : 0)}). NSE&apos;s
                bhavcopy for that day is missing; this is replaced when it lands.
              </p>
            )}
            <div className="co-stats two">
              <Stat label="Market cap" value={bigRupees(profile.market_cap)} />
              <Stat label="Volume" value={volume(px.volume)} />
            </div>
          </section>

          <section className="tpanel">
            <h3>Vitals</h3>
            <div className="co-stats two">
              <Stat label="P/E" value={plain(profile.pe, 1)} />
              <Stat
                label="Industry median P/E"
                value={plain(peers.median_pe, 1)}
                note={
                  peers.median_pe != null
                    ? `${peers.pe_count} companies with earnings`
                    : 'too few companies'
                }
              />
              <Stat label="ROCE" value={percent(profile.roce)} />
              <Stat label="ROE" value={percent(profile.roe)} />
              <Stat label="Debt to equity" value={plain(metrics.debt_to_equity)} />
              <Stat label="Dividend yield" value={percent(profile.dividend_yield, 2)} />
              <Stat label="Book value per share" value={price(profile.book_value)} />
              <Stat label="Promoter holding" value={percent(metrics.promoter_holding, 2)} />
            </div>
          </section>

          {profile.sector_levels.length > 0 && (
            <section className="tpanel">
              <h3>Classification</h3>
              <p className="co-crumbs">{profile.sector_levels.join(' › ')}</p>
              {profile.indices.length > 0 && (
                <ul className="co-chips">
                  {profile.indices.map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              )}
            </section>
          )}

          <section className="tpanel co-missing">
            <h3>Not held</h3>
            <p className="tfine">
              A stock page often shows these. No file on this platform holds them, so they are not
              shown:
            </p>
            <ul>
              {page.not_held.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>

          <p className="tfine">
            Fundamentals from screener.in, file of {longDate(page.as_of)}
            {page.consolidated === true && ', consolidated'}
            {page.consolidated === false && ', standalone'}. Not investment advice.
          </p>
        </aside>

        <div className="co-main">
          {page.fair_value ? (
            <FairValuePanel value={page.fair_value} series={px.series} />
          ) : (
            <section className="tpanel">
              <h3>Performance</h3>
              <PriceChart series={px.series} />
            </section>
          )}

          <section className="tpanel">
            <h3>Key metrics</h3>
            <div className="co-stats four">
              <Stat label="52-week high (close)" value={price(px.high_52w)} />
              <Stat label="52-week low (close)" value={price(px.low_52w)} />
              <Stat
                label="Operating margin"
                value={share(metrics.operating_margin).replace('+', '')}
              />
              <Stat label="Net profit margin" value={share(metrics.net_margin).replace('+', '')} />
              <Stat
                label="EPS, last four quarters"
                value={price(metrics.eps_ttm)}
                note={metrics.eps != null ? `Annual ${price(metrics.eps)}` : undefined}
              />
              <Stat
                label="Sales growth, year"
                value={share(metrics.sales_growth)}
                note={metrics.annual_period ? `to ${period(metrics.annual_period)}` : undefined}
              />
              <Stat label="Profit growth, year" value={share(metrics.profit_growth)} />
              <Stat
                label="Last reported quarter"
                value={metrics.quarter_period ? period(metrics.quarter_period) : DASH}
                note={
                  metrics.quarter_profit_growth != null
                    ? `Profit ${share(metrics.quarter_profit_growth)} on a year earlier`
                    : undefined
                }
              />
            </div>
            {position != null && (
              <div className="co-range">
                <span>{price(px.low_52w)}</span>
                <div className="co-range-track">
                  <i style={{ left: `${position * 100}%` }} />
                </div>
                <span>{price(px.high_52w)}</span>
              </div>
            )}
          </section>

          <section className="tpanel">
            <h3>Earnings and revenue</h3>
            <div className="co-bars-row">
              <Bars title="Sales, by quarter" table={page.tables.quarters} label="Sales" />
              <Bars
                title="Net profit, by quarter"
                table={page.tables.quarters}
                label="Net Profit"
              />
              <Bars title="Sales, by year" table={page.tables['profit-loss']} label="Sales" />
              <Bars
                title="Free cash flow, by year"
                table={page.tables['cash-flow']}
                label="Free Cash Flow"
              />
            </div>
          </section>

          <Statements tables={page.tables} />

          {peers.rows.length > 0 && (
            <section className="tpanel">
              <h3>
                Peers in {peers.industry} ({peers.count} companies)
              </h3>
              <div className="co-table-wrap">
                <table className="co-table">
                  <thead>
                    <tr>
                      <th scope="col">Company</th>
                      <th scope="col">Market cap</th>
                      <th scope="col">P/E</th>
                      <th scope="col">ROCE</th>
                      <th scope="col">ROE</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="is-self">
                      <th scope="row">{page.name || symbol}</th>
                      <td>{bigRupees(profile.market_cap)}</td>
                      <td>{plain(profile.pe, 1)}</td>
                      <td>{percent(profile.roce)}</td>
                      <td>{percent(profile.roe)}</td>
                    </tr>
                    {peers.rows.map((peer) => (
                      <tr key={peer.symbol}>
                        <th scope="row">
                          <Link href={`/terminal/company/${encodeURIComponent(peer.symbol)}`}>
                            {peer.name || peer.symbol}
                          </Link>
                        </th>
                        <td>{bigRupees(peer.market_cap)}</td>
                        <td>{plain(peer.pe, 1)}</td>
                        <td>{percent(peer.roce)}</td>
                        <td>{percent(peer.roe)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section className="tpanel">
            <h3>News</h3>
            {page.news.length === 0 ? (
              <p className="tfine">No headline in the last three months is tagged {symbol}.</p>
            ) : (
              <ul className="co-news">
                {page.news.map((item) => (
                  <li key={item.link}>
                    <a href={item.link} target="_blank" rel="noreferrer noopener">
                      {item.title}
                    </a>
                    <small>
                      {item.publisher}
                      {item.time && ` · ${longDate(item.time)}`}
                    </small>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
