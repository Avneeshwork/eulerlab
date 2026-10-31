'use client';

/**
 * A SIP backtester, after OpenAlgo's: a fixed amount invested every month in
 * one instrument, against putting the same total in once at the start.
 *
 * It is a calculator over landed closes from `/api/history` — the same rows a
 * backtest reads — not an engine run. No costs, no taxes, fractional units,
 * and nothing is recorded in the trial ledger, because a monthly purchase is a
 * savings plan rather than a strategy being searched for. The page says so.
 */

import { useEffect, useMemo, useState } from 'react';
import { Chip, Heading, Info, Move, Stat, Stats } from '@/components/terminal/ui';
import { api } from '@/lib/api';
import { ASSET_CLASSES } from '@/lib/assetClasses';
import { sip } from '@/lib/backtestStats';
import { moneyIn } from '@/lib/money';
import type { History, Instrument } from '@/lib/api';

const PERIODS = [
  { label: '1Y', days: 365 },
  { label: '3Y', days: 3 * 365 },
  { label: '5Y', days: 5 * 365 },
  { label: '10Y', days: 10 * 365 },
];

// /api/history serves equities from the panel and crypto and FX from their
// archives; it holds nothing else, so nothing else is offered.
const MARKETS = ASSET_CLASSES.filter((c) => ['equity', 'crypto', 'fx'].includes(c.value));

const pct = (value: number | null) =>
  value === null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(2)}%`;

export function SipTab() {
  const [market, setMarket] = useState('equity');
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<Instrument[]>([]);
  const [symbol, setSymbol] = useState('');
  const [amount, setAmount] = useState(10_000);
  const [dayOfMonth, setDayOfMonth] = useState(1);
  const [stepUp, setStepUp] = useState(0);
  const [period, setPeriod] = useState(3 * 365);
  const [history, setHistory] = useState<History | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      api
        .instruments(query, '', market, 12)
        .then((list) => setFound(list.instruments))
        .catch(() => setFound([]));
    }, 180);
    return () => clearTimeout(timer);
  }, [query, market]);

  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    setLoading(true);
    api
      .history(symbol, market, period)
      .then((h) => alive && setHistory(h))
      .catch((problem) =>
        alive &&
        setHistory({ ok: false, error: problem instanceof Error ? problem.message : String(problem), bars: [] })
      )
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [symbol, market, period]);

  const money = moneyIn(market);
  const result = useMemo(
    () => (history?.ok ? sip(history.bars, amount, dayOfMonth, stepUp) : null),
    [history, amount, dayOfMonth, stepUp]
  );

  return (
    <>
      <div className="tpanel" style={{ padding: 16 }}>
        <Heading
          title="Plan"
          info="A fixed amount bought every month at that day's close, against putting the same total in once at the first instalment's close."
        />
        <div className="sip-form">
          <label>
            Market
            <select
              value={market}
              onChange={(event) => {
                setMarket(event.target.value);
                setSymbol('');
                setHistory(null);
              }}
            >
              {MARKETS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label className="wide">
            Instrument
            <input
              placeholder="Search a symbol…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <label>
            Monthly amount
            <input
              type="number"
              min={1}
              value={amount}
              onChange={(event) => setAmount(Math.max(0, Number(event.target.value)))}
            />
          </label>
          {/* htmlFor: the Info button inside would otherwise become the label's control. */}
          <label htmlFor="sip-day">
            <span>
              Day of month
              <Info>The first trading day on or after this day each month. A month with no close on or after it is skipped.</Info>
            </span>
            <input
              id="sip-day"
              type="number"
              min={1}
              max={28}
              value={dayOfMonth}
              onChange={(event) => setDayOfMonth(Math.min(28, Math.max(1, Number(event.target.value))))}
            />
          </label>
          <label htmlFor="sip-step">
            <span>
              Yearly step-up %
              <Info>After every 12 instalments the monthly amount rises by this percent, compounding.</Info>
            </span>
            <input
              id="sip-step"
              type="number"
              min={0}
              max={100}
              value={stepUp * 100}
              onChange={(event) => setStepUp(Math.max(0, Number(event.target.value)) / 100)}
            />
          </label>
        </div>
        <div className="ttools" style={{ marginTop: 12 }}>
          {found.map((instrument) => (
            <button
              key={instrument.symbol}
              className="tchip sm"
              type="button"
              aria-pressed={symbol === instrument.symbol}
              onClick={() => setSymbol(instrument.symbol)}
              title={instrument.name}
            >
              {instrument.symbol}
            </button>
          ))}
          {found.length === 0 && <span className="tfine">No instruments match.</span>}
          <div className="ttools-actions">
            {PERIODS.map((p) => (
              <button
                key={p.label}
                className="tchip sm"
                type="button"
                aria-pressed={period === p.days}
                onClick={() => setPeriod(p.days)}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {!symbol && <div className="tempty">Pick an instrument to run the plan.</div>}
      {symbol && loading && <div className="tempty">Reading {symbol}…</div>}
      {symbol && !loading && history && !history.ok && (
        <div className="tnote bad">
          <span className="mk">▲</span>
          <div>{history.error}</div>
        </div>
      )}

      {symbol && !loading && result && history?.ok && (
        <>
          <Stats>
            <Stat label="Invested" value={money(result.invested)} sub={`${result.instalments.length} instalments`} />
            <Stat
              label="Value now"
              value={money(result.value)}
              tone={result.value >= result.invested ? 'up' : 'down'}
              sub={
                <Move
                  value={result.value / result.invested - 1}
                  text={`${money(result.value - result.invested)} (${pct(result.value / result.invested - 1)})`}
                />
              }
            />
            <Stat
              label="XIRR"
              value={<Move value={result.xirr} text={pct(result.xirr)} />}
              info="Annual and money-weighted: the rate at which every instalment and the final value net to zero."
            />
            <Stat
              label="Same total, invested once"
              value={money(result.lumpSum)}
              sub={
                <Chip tone={result.lumpSum >= result.value ? 'down' : 'up'}>
                  {result.lumpSum >= result.value ? '↓ SIP trailed' : '↑ SIP beat it'}
                </Chip>
              }
              info={`The whole ${money(result.invested)} bought at the close on ${result.instalments[0].day} and held to the end.`}
            />
          </Stats>

          <div className="tpanel" style={{ padding: 16 }}>
            <Heading
              title="Value against money put in"
              sub={`${history.first} → ${history.last}`}
              info="Solid line and fill: what the units bought so far were worth at each close. Dashed: the running total put in."
            />
            <SipChart path={result.path} money={money} />
          </div>

          <div className="tpanel" style={{ padding: 16 }}>
            <Heading title="Instalments" sub={history.source ?? 'landed data'}>
              <Chip tone="warn">Upper bound</Chip>
              <Info align="right">
                Closes from the {history.source ?? 'landed data'}, {history.first} to {history.last}. No brokerage,
                taxes or stamp duty, and fractional units, so this is an upper bound on what the plan returned. It is
                not recorded in the trial ledger.
              </Info>
            </Heading>
            <div className="tscroll" style={{ maxHeight: '45vh' }}>
              <table className="ttable">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Day</th>
                    <th className="r">Close</th>
                    <th className="r">Amount</th>
                    <th className="r">Units</th>
                  </tr>
                </thead>
                <tbody>
                  {result.instalments.map((i, index) => (
                    <tr key={i.day}>
                      <td className="tdim">{index + 1}</td>
                      <td>{i.day}</td>
                      <td className="r">{i.price.toFixed(2)}</td>
                      <td className="r">{money(i.amount)}</td>
                      <td className="r">{i.units.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </>
  );
}

function SipChart({
  path,
  money,
}: {
  path: { day: string; invested: number; value: number }[];
  money: (value: number) => string;
}) {
  if (path.length < 2) return <p className="tfine">Not enough bars to draw.</p>;
  const W = 720;
  const H = 220;
  const high = Math.max(...path.map((p) => Math.max(p.invested, p.value)), 1);
  const x = (i: number) => (i / (path.length - 1)) * W;
  const y = (v: number) => H - (v / high) * (H - 8);
  const line = (key: 'invested' | 'value') =>
    path.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join(' ');
  const last = path[path.length - 1];
  return (
    <figure className="eqchart">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="SIP value and amount invested">
        <path d={`${line('value')} L${W},${H} L0,${H} Z`} className="eq-fill up" />
        <path d={line('invested')} className="eq-base" />
        <path d={line('value')} className="eq-line up" />
      </svg>
      <figcaption>
        <span>
          {path[0].day} → {last.day}
        </span>
        <span className={last.value >= last.invested ? 'pos' : 'neg'}>value {money(last.value)}</span>
        <span className="tdim">- - {money(last.invested)} put in</span>
      </figcaption>
    </figure>
  );
}
