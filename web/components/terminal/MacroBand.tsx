'use client';

/**
 * The macro band — yields, energy, metals and risk.
 *
 * Sourced from TradingView's public scanner rather than FMP, because FMP's
 * free plan answers 402 for WTI, natural gas and the dollar index, and serves
 * no sovereign yields at all. The scanner returns all seventeen series in one
 * request with no key, which is also why this can refresh often.
 *
 * The yields are shown as a curve, not a list, because the shape is the point:
 * a reader is looking for whether the front end sits above the long end, and
 * four numbers in a row do not answer that at a glance.
 */

import { useState } from 'react';
import type { MacroReading } from '@/lib/api';
import { MiniChart } from '@/components/terminal/MiniChart';

const pctRaw = (value: number, digits = 2) =>
  `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(digits)}%`;

function Tile({ reading }: { reading: MacroReading }) {
  const up = reading.change_pct >= 0;
  return (
    <div className="mtile" title={`${reading.name} · ${reading.symbol}`}>
      <span className="mname">{reading.name}</span>
      <span className="mlast">
        {reading.last.toLocaleString('en-US', {
          minimumFractionDigits: 2,
          maximumFractionDigits: reading.last < 20 ? 3 : 2,
        })}
        {reading.unit && <i className="munit">{reading.unit}</i>}
      </span>
      <span className={up ? 'mchg up' : 'mchg dn'}>{pctRaw(reading.change_pct)}</span>
    </div>
  );
}

/** The US curve drawn as a curve. Inversion is a shape, not a number. */
function Curve({ rows, spread }: { rows: MacroReading[]; spread?: number | null }) {
  const us = rows.filter((r) => r.name.startsWith('US ') && r.unit === '%');
  if (us.length < 2) return null;

  const rates = us.map((r) => r.last);
  const low = Math.min(...rates);
  const high = Math.max(...rates);
  const span = high - low || 1;
  const width = 100;
  const height = 46;

  const points = us.map((r, index) => {
    const x = (index / (us.length - 1)) * width;
    const y = height - ((r.last - low) / span) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const inverted = spread !== null && spread !== undefined && spread < 0;

  return (
    <div className="curvebox">
      <div className="curvehead">
        <span className="mname">US CURVE</span>
        {spread !== null && spread !== undefined && (
          <b className={inverted ? 'dn' : 'up'}>
            2s10s {spread >= 0 ? '+' : '−'}
            {Math.abs(spread).toFixed(2)}
          </b>
        )}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="curvesvg">
        <polyline
          points={points.join(' ')}
          fill="none"
          stroke={inverted ? 'var(--down)' : 'var(--neon-deep)'}
          strokeWidth="1.6"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="curveaxis">
        {us.map((r) => (
          <span key={r.symbol}>{r.name.replace('US ', '')}</span>
        ))}
      </div>
      <div className="tfine">
        {inverted
          ? 'Inverted — the two-year yields more than the ten.'
          : 'Upward sloping — no inversion at the 2s10s.'}
      </div>
    </div>
  );
}

/** What the mini-chart widget will actually draw.
 *
 *  The scanner serves every macro symbol we quote; the **widget does not**.
 *  `TVC:US10Y`, `US30Y`, `DE10Y` and `GB10Y` answer "No data here yet", and
 *  `IN10Y` and `JP10Y` answer "This symbol is only available on TradingView".
 *  They are different products with different licensing, and verifying against
 *  the scanner and assuming the widget agreed is what put six empty boxes on
 *  the page.
 *
 *  So charts are drawn from ordinary securities — ETFs, the same class as
 *  SPY and NIFTYBEES that the embed serves without complaint — and each is
 *  labelled as the fund it is rather than the concept it stands for.
 *
 *  Bond ETFs are the delicate case: **price moves inversely to yield**, so a
 *  chart of TLT rising is the 30-year yield falling. Labelling one "US 30Y"
 *  would draw the line the wrong way round, so they are named as the funds
 *  they are and the caption says which direction is which.
 */
const CHARTABLE: Record<string, { symbol: string; label: string; note?: string }> = {
  'US 2Y': { symbol: 'NASDAQ:SHY', label: 'SHY · 1-3Y TREASURY', note: 'price, inverse to yield' },
  'US 10Y': { symbol: 'NASDAQ:IEF', label: 'IEF · 7-10Y TREASURY', note: 'price, inverse to yield' },
  'US 30Y': { symbol: 'NASDAQ:TLT', label: 'TLT · 20+Y TREASURY', note: 'price, inverse to yield' },
  'WTI CRUDE': { symbol: 'AMEX:USO', label: 'USO · US OIL FUND' },
  BRENT: { symbol: 'AMEX:BNO', label: 'BNO · BRENT OIL FUND' },
  'NAT GAS': { symbol: 'AMEX:UNG', label: 'UNG · NATURAL GAS FUND' },
  GOLD: { symbol: 'AMEX:GLD', label: 'GLD · SPDR GOLD' },
  SILVER: { symbol: 'AMEX:SLV', label: 'SLV · ISHARES SILVER' },
  COPPER: { symbol: 'AMEX:CPER', label: 'CPER · COPPER INDEX FUND' },
  'DOLLAR INDEX': { symbol: 'AMEX:UUP', label: 'UUP · DOLLAR BULLISH' },
};

const GROUPS: [string, string][] = [
  ['yields', 'Sovereign yields'],
  ['energy', 'Energy'],
  ['metals', 'Metals'],
  ['risk', 'Risk'],
];

export function MacroBand({
  rows,
  spread,
  stale,
}: {
  rows: MacroReading[];
  spread?: number | null;
  stale?: boolean;
}) {
  const [view, setView] = useState<'charts' | 'numbers'>('charts');
  if (!rows.length) return null;
  return (
    <section>
      <h3 className="report-h">
        Macro
        <span
          className="tfine hstat"
          title="TradingView's public scanner — one request, no key. FMP's free plan answers 402 for WTI, natural gas and the dollar index, and serves no sovereign yields at all."
        >
          {stale ? 'from the last sweep' : 'live'} · 17 series
          <abbr className="whyq">?</abbr>
        </span>
      </h3>

      <div className="mkttoggle" style={{ marginBottom: 12 }}>
        {(['charts', 'numbers'] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            className={view === mode ? 'on' : ''}
            onClick={() => setView(mode)}
          >
            {mode === 'charts' ? 'Charts' : 'Numbers'}
          </button>
        ))}
        {view === 'charts' && (
          <span className="tfine mktnote">
            Each series with its own history. The scanner that feeds the numbers view
            returns one reading per symbol and no history at all.
          </span>
        )}
      </div>

      {view === 'numbers' ? (
        <div className="macrogrid">
          <Curve rows={rows} spread={spread} />
          {GROUPS.map(([group, label]) => {
            const kept = rows.filter((r) => r.group === group);
            if (!kept.length) return null;
            return (
              <div className="mgroup" key={group}>
                <div className="mgrouphead">{label}</div>
                <div className="mtiles">
                  {kept.map((r) => (
                    <Tile key={r.symbol} reading={r} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        GROUPS.map(([group, label]) => {
          const kept = rows.filter((r) => r.group === group && CHARTABLE[r.name]);
          const uncharted = rows.filter((r) => r.group === group && !CHARTABLE[r.name]);
          if (!kept.length && !uncharted.length) return null;
          return (
            <div key={group} style={{ marginBottom: 16 }}>
              <div className="mgrouphead">{label}</div>
              {kept.length > 0 && (
                <div className="minigrid">
                  {kept.map((r) => {
                    const spec = CHARTABLE[r.name];
                    return (
                      <MiniChart
                        key={r.symbol}
                        symbol={spec.symbol}
                        label={`${spec.label}${spec.note ? ` — ${spec.note}` : ''}`}
                      />
                    );
                  })}
                </div>
              )}
              {uncharted.length > 0 && (
                <p className="tfine mktgap" style={{ marginTop: kept.length ? 10 : 0 }}>
                  No chart for {uncharted.map((r) => r.name).join(', ')} — the embed
                  refuses these symbols even though the quote feed serves them. Their
                  levels are in the Numbers view, and a history is being accumulated from
                  each sweep.
                </p>
              )}
            </div>
          );
        })
      )}
    </section>
  );
}
