/**
 * The stock screener (ADR-136): which liquid stocks each model would hold today, and why.
 *
 * Two tabs. Long-term: models that rebalance monthly (quality, value, momentum,
 * the F-score, a tree ranker, and the five best stored strategies). Swing:
 * models that rebalance weekly (a trend pullback and a 52-week breakout). Each
 * model shows its stored screening backtest, its gate status and how its past
 * selections did since they were recorded; each stock shows the reasons and
 * which models pick it. A list is what a model would hold, not advice.
 */

'use client';

import { useEffect, useMemo, useState } from 'react';
import { screener } from '@/lib/api';
import type { Screener, ScreenerList, ScreenerStock } from '@/lib/api';
import { Chip, Empty, Heading, Info, Seg, Stat, Stats } from '@/components/terminal/ui';
import './screener.css';

type Kind = 'long' | 'swing';

const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(digits)}%`;
const num = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? '—' : v.toFixed(digits);

function ModelCard({ list, onPick }: { list: ScreenerList; onPick: (id: string) => void }) {
  const bt = list.backtest;
  const t = list.track;
  return (
    <div className="scr-model tpanel">
      <Heading
        title={
          <button type="button" className="scr-link" onClick={() => onPick(list.id)}>
            {list.title}
          </button>
        }
        sub={`${list.picks.length} picks${list.new ? ' · new' : ' · existing'}`}
        info={list.gate}
      />
      {list.error && <p className="scr-warn">This model failed today: {list.error}</p>}
      <Stats>
        <Stat
          label="Backtest Sharpe"
          value={num(bt.sharpe, 2)}
          sub={bt.window ? `${bt.window[0]} to ${bt.window[1]}` : 'not run yet'}
          info="Screening backtest on the common engine, Tier B, after Indian costs. No trial was spent; the gate has not judged it."
        />
        <Stat
          label="Total return"
          value={pct(bt.total_return, 0)}
          sub={bt.benchmark?.total_return !== undefined ? `NIFTYBEES ${pct(bt.benchmark.total_return, 0)}` : ''}
        />
        <Stat label="Max drawdown" value={pct(bt.max_drawdown, 0)} tone="down" />
        <Stat
          label="Past picks vs Nifty"
          value={t.complete ? pct(t.mean_excess) : '—'}
          sub={
            t.complete
              ? `${t.complete} selections, ${Math.round((t.beat_nifty_share ?? 0) * 100)}% beat Nifty`
              : 'recorded from today; first result after one holding period'
          }
          info="Each recorded selection, equal-weighted, from the next session's close over the model's holding period (5 sessions swing, 21 long-term), minus NIFTYBEES over the same days, before costs."
        />
      </Stats>
      {list.halves && (
        <p className="ui-sub">
          Sharpe 2016-2020 {num(list.halves[0] ?? null, 2)} · 2021-2026 {num(list.halves[1] ?? null, 2)}
        </p>
      )}
      <div className="scr-chips">
        {list.main && <Chip tone="up">Main long-term list</Chip>}
        {list.chosen && <Chip tone="up">Chosen by the pre-registered rule</Chip>}
        <Chip tone="warn">Not gate-promoted</Chip>
      </div>
    </div>
  );
}

function History({ list }: { list: ScreenerList }) {
  if (!list.track.selections.length) {
    return <Empty reason="No past selection recorded yet: the history starts with the first screener build." />;
  }
  return (
    <table className="ttable">
      <thead>
        <tr>
          <th>Picked on</th>
          <th>Stocks</th>
          <th>From → to</th>
          <th>Return</th>
          <th>Nifty</th>
          <th>Excess</th>
          <th>Beat Nifty</th>
        </tr>
      </thead>
      <tbody>
        {list.track.selections.map((s) => (
          <tr key={s.as_of}>
            <td>{s.as_of}</td>
            <td>{s.n}</td>
            <td>
              {s.from} → {s.to}
              {!s.complete && <small> (open, {s.sessions} sessions)</small>}
            </td>
            <td className={s.return >= 0 ? 'up' : 'down'}>{pct(s.return)}</td>
            <td>{pct(s.nifty)}</td>
            <td className={s.excess >= 0 ? 'up' : 'down'}>{pct(s.excess)}</td>
            <td>{Math.round(s.beat_nifty * 100)}%</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function StockTable({
  symbols,
  stocks,
  kind,
  list,
  details,
}: {
  symbols: string[];
  stocks: Record<string, ScreenerStock>;
  kind: Kind;
  list: ScreenerList;
  details: boolean;
}) {
  if (!symbols.length) return <Empty reason="No stock qualifies today." />;
  const parts = list.part_picks ? Object.keys(list.part_picks).length : 0;
  return (
    <div className="tscroll">
      <table className="ttable scr-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Stock</th>
            {parts > 0 && (
              <th>
                Models agree <Info>How many of the models behind this list pick the stock. More agreement ranks higher.</Info>
              </th>
            )}
            <th>
              Weight <Info>The stock&rsquo;s share of the book in the backtested strategy, today.</Info>
            </th>
            <th>Price</th>
            <th>1 month</th>
            <th>
              1 year <Info>Price change from 12 months to 1 month ago, the momentum the models use.</Info>
            </th>
            <th>
              Quality <Info>Percentile among the 250 most-traded stocks on ROE, operating profit over assets, low debt and dividend payout, from the last annual results known 90 days after the year end.</Info>
            </th>
            <th>
              P/E <Info>Price over the last known annual earnings per share.</Info>
            </th>
            <th>
              News <Info align="right">Tone of the last 7 days of headlines naming the stock, -1 to +1, corrected by the news rules.</Info>
            </th>
            {details && (
              <>
                <th>To 52w high</th>
                <th>vs 200-day</th>
                {kind === 'swing' && <th>RSI(2)</th>}
                <th>Value rank</th>
                <th>F-score</th>
                <th>ROE</th>
                <th>P/B</th>
                <th>Debt/equity</th>
                <th>Turnover ₹cr</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {symbols.map((sym, i) => {
            const s = stocks[sym];
            if (!s) return null;
            const agreeing = list.part_picks
              ? Object.entries(list.part_picks)
                  .filter(([, picks]) => picks.includes(sym))
                  .map(([id]) => id)
              : [];
            const weight = list.weights?.[sym];
            return (
              <tr key={sym}>
                <td>{i + 1}</td>
                <td>
                  <a className="tsym" href={`/terminal/company/${encodeURIComponent(sym)}`}>
                    {sym}
                  </a>
                </td>
                {parts > 0 && (
                  <td title={agreeing.join(', ')}>
                    {list.votes?.[sym] ?? 0} of {parts}
                  </td>
                )}
                <td>{weight === undefined ? '—' : `${(weight * 100).toFixed(1)}%`}</td>
                <td>₹{s.close.toLocaleString('en-IN')}</td>
                <td className={(s.change_1m ?? 0) >= 0 ? 'up' : 'down'}>{pct(s.change_1m)}</td>
                <td className={(s.momentum_12_1 ?? 0) >= 0 ? 'up' : 'down'}>{pct(s.momentum_12_1, 0)}</td>
                <td title="Percentile among the 250 most-traded stocks: ROE, profit on assets, low debt, payout">
                  {s.quality_pct === null || s.quality_pct === undefined ? '—' : `${s.quality_pct}/100`}
                </td>
                <td>{num(s.pe)}</td>
                <td>{s.news_tone ? `${s.news_tone.mean >= 0 ? '+' : ''}${s.news_tone.mean.toFixed(2)}` : '—'}</td>
                {details && (
                  <>
                    <td>{s.near_high === null ? '—' : `${((1 - s.near_high) * 100).toFixed(1)}% below`}</td>
                    <td>{pct(s.above_200d)}</td>
                    {kind === 'swing' && <td>{num(s.rsi2)}</td>}
                    <td>{s.value_pct ?? '—'}</td>
                    <td>{s.fscore ?? '—'}</td>
                    <td>{pct(s.roe, 0)}</td>
                    <td>{num(s.pb, 2)}</td>
                    <td>{num(s.debt_equity, 2)}</td>
                    <td>{num(s.turnover_cr)}</td>
                  </>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

type TopN = '10' | '20' | 'all';

/** The list's stocks, best first: most models agreeing, then largest weight, quality, momentum. */
function ranked(list: ScreenerList, stocks: Record<string, ScreenerStock>): string[] {
  return [...list.picks].sort(
    (a, b) =>
      (list.votes?.[b] ?? 0) - (list.votes?.[a] ?? 0) ||
      (list.weights?.[b] ?? 0) - (list.weights?.[a] ?? 0) ||
      (stocks[b]?.quality_pct ?? -1) - (stocks[a]?.quality_pct ?? -1) ||
      (stocks[b]?.momentum_12_1 ?? -9) - (stocks[a]?.momentum_12_1 ?? -9) ||
      a.localeCompare(b),
  );
}

function Summary({ list, kind, top, caveats, why }: { list: ScreenerList; kind: Kind; top: string; caveats: string[]; why?: string }) {
  const bt = list.backtest;
  const nifty = bt.benchmark?.total_return;
  return (
    <Heading
      title={kind === 'long' ? 'Long-term buy list' : 'Swing buy list'}
      sub={kind === 'long' ? 'rebalance monthly' : 'rebalance weekly'}
      info={
        <>
          <p>
            {kind === 'long'
              ? 'Stocks that at least 3 of our 5 best long-term models pick.'
              : 'Our most consistent swing blend: volatility-adjusted momentum and Weinstein stage 2.'}
          </p>
          <p>
            Backtest 2016–2026, after costs: Sharpe {num(bt.sharpe, 2)}, return {pct(bt.total_return, 0)}
            {nifty !== undefined && <> (Nifty {pct(nifty, 0)})</>}, worst fall {pct(bt.max_drawdown, 0)}
            {list.halves && (
              <>
                ; Sharpe {num(list.halves[0] ?? null, 2)} in 2016–2020 and {num(list.halves[1] ?? null, 2)} in 2021–2026
              </>
            )}
            . Not yet passed the gate.
          </p>
          <p>
            Ranked by how many models agree, then weight, then quality. The backtest holds every stock on the list;
            buying only the top {top === 'all' ? 'few' : top} is more concentrated than what was tested.
          </p>
          {why && <p>How the swing list is chosen: {why}.</p>}
          <ul>
            {caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </>
      }
    >
      <Chip tone="warn">Not gate-promoted</Chip>
    </Heading>
  );
}

export function ScreenerTab() {
  const [data, setData] = useState<Screener | null>(null);
  const [error, setError] = useState('');
  const [kind, setKind] = useState<Kind>('long');
  const [other, setOther] = useState('');
  const [top, setTop] = useState<TopN>('10');
  const [details, setDetails] = useState(false);

  useEffect(() => {
    screener()
      .then((got) => (got.ok ? setData(got) : setError(got.error)))
      .catch((exc: unknown) => setError(String(exc)));
  }, []);

  const lists = useMemo(() => (data?.lists ?? []).filter((l) => l.kind === kind), [data, kind]);
  // One recommended list per tab: the long-term consensus, or the swing blend the rule chose.
  const main = lists.find((l) => (kind === 'long' ? l.main : l.chosen));
  const behind = useMemo(() => {
    if (!main) return [];
    const ids = new Set([...Object.keys(main.part_picks ?? {}), ...(main.parts ?? []).map((p) => p.id)]);
    return (data?.lists ?? []).filter((l) => ids.has(l.id));
  }, [data, main]);
  const rest = lists.filter((l) => l !== main && !behind.includes(l));
  const picked = (data?.lists ?? []).find((l) => l.id === other);
  const order = useMemo(() => (main && data ? ranked(main, data.stocks) : []), [main, data]);
  const shown = top === 'all' ? order : order.slice(0, Number(top));

  if (error) return <p className="scr-warn">{error}</p>;
  if (!data) return <p className="ui-sub">Loading the screener…</p>;

  return (
    <section className="scr">
      <div className="scr-bar">
        <Seg<Kind>
          label="Holding horizon"
          value={kind}
          options={[
            ['long', 'Long term'],
            ['swing', 'Swing'],
          ]}
          onChange={(k) => {
            setKind(k);
            setOther('');
          }}
        />
        <Seg<TopN>
          label="How many to show"
          value={top}
          options={[
            ['10', 'Top 10'],
            ['20', 'Top 20'],
            ['all', `All ${order.length}`],
          ]}
          onChange={setTop}
        />
        <label className="scr-filter">
          <input type="checkbox" checked={details} onChange={(e) => setDetails(e.target.checked)} />
          Show details
        </label>
        <span className="ui-sub">Prices of {data.as_of}</span>
      </div>

      {main ? (
        <div className="tpanel">
          <Summary list={main} kind={kind} top={top} caveats={data.caveats} why={data.choice?.why} />
          <StockTable symbols={shown} stocks={data.stocks} kind={kind} list={main} details={details} />
        </div>
      ) : (
        <p className="scr-warn">No list is chosen for this tab yet: {data.choice?.why ?? 'the screener has not run'}.</p>
      )}

      {main && (
        <details className="tpanel">
          <summary>How this list has done since we started recording it</summary>
          <History list={main} />
        </details>
      )}

      {behind.length > 0 && (
        <details className="tpanel">
          <summary>The {behind.length} models behind this list</summary>
          <div className="scr-models">
            {behind.map((l) => (
              <ModelCard key={l.id} list={l} onPick={(id) => setOther(id === other ? '' : id)} />
            ))}
          </div>
        </details>
      )}

      {rest.length > 0 && (
        <details className="tpanel">
          <summary>Other models we tested ({rest.length}), not used for this list</summary>
          <div className="scr-models">
            {rest.map((l) => (
              <ModelCard key={l.id} list={l} onPick={(id) => setOther(id === other ? '' : id)} />
            ))}
          </div>
        </details>
      )}

      {picked && picked !== main && (
        <div className="tpanel">
          <Heading title={`${picked.title}: today's picks`} sub={`${picked.picks.length} stocks`} />
          <StockTable symbols={ranked(picked, data.stocks)} stocks={data.stocks} kind={kind} list={picked} details={details} />
        </div>
      )}

    </section>
  );
}
