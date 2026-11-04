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
import { Chip, Empty, Heading, Seg, Stat, Stats } from '@/components/terminal/ui';
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
  titles,
}: {
  symbols: string[];
  stocks: Record<string, ScreenerStock>;
  kind: Kind;
  titles: Record<string, string>;
}) {
  if (!symbols.length) return <Empty reason="No stock qualifies today." />;
  return (
    <div className="tscroll">
      <table className="ttable scr-table">
        <thead>
          <tr>
            <th>Stock</th>
            <th>Models</th>
            <th>Close</th>
            <th>1 month</th>
            <th>12-1 mom.</th>
            <th>To 52w high</th>
            <th>vs 200d</th>
            {kind === 'swing' && <th>RSI(2)</th>}
            {kind === 'long' && (
              <>
                <th>Quality</th>
                <th>Value</th>
                <th>F-score</th>
                <th>ROE</th>
                <th>P/E</th>
                <th>P/B</th>
                <th>D/E</th>
              </>
            )}
            <th>News</th>
            <th>Turnover ₹cr</th>
          </tr>
        </thead>
        <tbody>
          {symbols.map((sym) => {
            const s = stocks[sym];
            if (!s) return null;
            const mine = s.models.filter((m) => titles[m]);
            return (
              <tr key={sym}>
                <td>
                  <a className="tsym" href={`/terminal/company/${encodeURIComponent(sym)}`}>
                    {sym}
                  </a>
                </td>
                <td title={mine.map((m) => titles[m]).join(', ')}>{mine.length}</td>
                <td>{s.close.toLocaleString('en-IN')}</td>
                <td className={(s.change_1m ?? 0) >= 0 ? 'up' : 'down'}>{pct(s.change_1m)}</td>
                <td>{pct(s.momentum_12_1, 0)}</td>
                <td>{s.near_high === null ? '—' : `${((1 - s.near_high) * 100).toFixed(1)}% below`}</td>
                <td>{pct(s.above_200d)}</td>
                {kind === 'swing' && <td>{num(s.rsi2)}</td>}
                {kind === 'long' && (
                  <>
                    <td>{s.quality_pct ?? '—'}</td>
                    <td>{s.value_pct ?? '—'}</td>
                    <td>{s.fscore ?? '—'}</td>
                    <td>{pct(s.roe, 0)}</td>
                    <td>{num(s.pe)}</td>
                    <td>{num(s.pb, 2)}</td>
                    <td>{num(s.debt_equity, 2)}</td>
                  </>
                )}
                <td>{s.news_tone ? `${s.news_tone.mean >= 0 ? '+' : ''}${s.news_tone.mean.toFixed(2)} (${s.news_tone.n})` : '—'}</td>
                <td>{num(s.turnover_cr)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ScreenerTab() {
  const [data, setData] = useState<Screener | null>(null);
  const [error, setError] = useState('');
  const [kind, setKind] = useState<Kind>('long');
  const [model, setModel] = useState('');
  const [minTurnover, setMinTurnover] = useState(0);

  useEffect(() => {
    screener()
      .then((got) => (got.ok ? setData(got) : setError(got.error)))
      .catch((exc: unknown) => setError(String(exc)));
  }, []);

  const lists = useMemo(() => (data?.lists ?? []).filter((l) => l.kind === kind), [data, kind]);
  const titles = useMemo(() => Object.fromEntries(lists.map((l) => [l.id, l.title])), [lists]);
  // Each tab opens on its pre-registered list: the 70:30 blend, or the swing blend the rule chose.
  const preferred = lists.find((l) => (kind === 'long' ? l.main : l.chosen));
  const chosen = lists.find((l) => l.id === model) ?? (model === '' ? preferred : undefined);
  const symbols = useMemo(() => {
    if (!data) return [];
    const base = chosen
      ? chosen.picks
      : Object.keys(data.stocks).filter((s) => data.stocks[s].models.some((m) => titles[m]));
    return base
      .filter((s) => (data.stocks[s]?.turnover_cr ?? 0) >= minTurnover)
      .sort((a, b) => {
        const ma = data.stocks[a].models.filter((m) => titles[m]).length;
        const mb = data.stocks[b].models.filter((m) => titles[m]).length;
        return mb - ma || (data.stocks[b].quality_pct ?? 0) - (data.stocks[a].quality_pct ?? 0) || a.localeCompare(b);
      });
  }, [data, chosen, titles, minTurnover]);

  if (error) return <p className="scr-warn">{error}</p>;
  if (!data) return <p className="ui-sub">Loading the screener…</p>;

  return (
    <section className="scr">
      <div className="scr-bar">
        <Seg<Kind>
          label="Holding horizon"
          value={kind}
          options={[
            ['long', 'Long term · monthly'],
            ['swing', 'Swing · weekly'],
          ]}
          onChange={(k) => {
            setKind(k);
            setModel('');
          }}
        />
        <label className="scr-filter">
          Min turnover ₹cr
          <input
            type="number"
            min={0}
            step={5}
            value={minTurnover}
            onChange={(e) => setMinTurnover(Number(e.target.value) || 0)}
          />
        </label>
        <span className="ui-sub">
          As of {data.as_of} · {data.universe}
        </span>
      </div>

      {data.choice && <p className="scr-choice">How the lists are chosen ({data.choice.rule}): {data.choice.why}.</p>}

      <ul className="scr-caveats">
        {data.caveats.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>

      <div className="scr-models">
        {lists.map((l) => (
          <ModelCard key={l.id} list={l} onPick={(id) => setModel(id === (chosen?.id ?? '') ? 'all' : id)} />
        ))}
      </div>

      <div className="tpanel">
        <Heading
          title={chosen ? `${chosen.title}: today's picks` : 'Stocks picked by at least one model'}
          sub={`${symbols.length} stocks`}
          info="Sorted by how many of this tab's models pick the stock, then by quality rank. Click a model's name to see only its picks; click again for all."
        />
        <StockTable symbols={symbols} stocks={data.stocks} kind={kind} titles={titles} />
      </div>

      {chosen && (
        <div className="tpanel">
          <Heading
            title={`${chosen.title}: past selections`}
            info="Every recorded selection of this model, newest first, measured from the next session's close."
          />
          <History list={chosen} />
        </div>
      )}
    </section>
  );
}
