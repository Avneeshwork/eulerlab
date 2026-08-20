'use client';

// The Tweezer Bottom scanner.
//
// Deliberately not shaped like the daily backtest panel. There is no equity
// curve and no Sharpe here, because an intraday scan produces neither — it
// produces a list of trades, most days producing none at all. Borrowing the
// daily layout would imply the two are comparable.
//
// The most important thing on this screen is usually the *rejection* table:
// with real data this setup fires roughly twice per symbol per six months, and
// a panel that showed only the trades would leave the reader thinking the
// filters were doing something they are not.

import { useCallback, useEffect, useRef, useState } from 'react';
import { api, rupees, tweezerJob } from '@/lib/api';
import type { TweezerJob, TweezerResult } from '@/lib/api';

const DEFAULT_SYMBOLS = 'RELIANCE, TCS, INFY';

export function TweezerPanel() {
  const [symbols, setSymbols] = useState(DEFAULT_SYMBOLS);
  const [start, setStart] = useState('2024-01-01');
  const [end, setEnd] = useState('2024-06-30');
  const [job, setJob] = useState<TweezerJob | null>(null);
  const [problem, setProblem] = useState('');
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stop = useCallback(() => {
    if (timer.current) {
      clearInterval(timer.current);
      timer.current = null;
    }
  }, []);

  useEffect(() => stop, [stop]);

  const run = useCallback(async () => {
    setProblem('');
    const list = symbols
      .split(',')
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    if (!list.length) {
      setProblem('Name at least one symbol.');
      return;
    }

    const started = await api.tweezer({ symbols: list, start, end });
    if (!started.ok || !started.job) {
      setProblem(started.error ?? 'could not start the scan');
      return;
    }

    stop();
    const id = started.job;
    timer.current = setInterval(async () => {
      try {
        const next = await tweezerJob(id);
        setJob(next);
        if (next.status === 'done' || next.status === 'failed') stop();
      } catch (err) {
        setProblem(String(err));
        stop();
      }
    }, 1200);
  }, [symbols, start, end, stop]);

  const busy = job?.status === 'queued' || job?.status === 'running';
  const result: TweezerResult | null = job?.status === 'done' ? job.result : null;

  return (
    <div className="grid">
      <div>
        <div className="card">
          <h2>Tweezer Bottom</h2>
          <p className="sub">
            A bullish reversal on minute bars: two adjacent candles with matching lows,
            the first bearish and the second bullish, in a short-term downtrend and near
            support. Entry above the first candle&rsquo;s high, stop below the pattern,
            targets at 2R and 3R.
          </p>

          <label>
            <span>Symbols</span>
            <input
              value={symbols}
              onChange={(e) => setSymbols(e.target.value)}
              placeholder="RELIANCE, TCS, INFY"
            />
          </label>

          <div className="row">
            <label>
              <span>From</span>
              <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
            </label>
            <label>
              <span>To</span>
              <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
            </label>
          </div>

          <div className="run-row">
            <button className="primary" onClick={run} disabled={busy}>
              {busy ? 'Scanning…' : 'Scan for setups'}
            </button>
            {job && (
              <span className="muted">
                {job.message || job.status} · {job.elapsed.toFixed(1)}s
              </span>
            )}
          </div>
          <p className="footnote">
            Minute bars stream from cloud storage on first use, so the first symbol takes
            longer than the rest.
          </p>

          {problem && <div className="note bad">{problem}</div>}
          {job?.status === 'failed' && (
            <div className="note bad">
              <pre>{job.error}</pre>
            </div>
          )}
        </div>

        <div className="card">
          <h2>Why this is not a &ldquo;strategy&rdquo; here</h2>
          <p className="sub">It cannot be expressed as target weights.</p>
          <ul className="caveats">
            <li>Entry is conditional — a stop above the high that may never trigger.</li>
            <li>The exit is a bracket: two targets, a breakeven move, then a trail.</li>
            <li>Size comes from risk, not from a weight: 1% of equity divided by R.</li>
            <li>It is intraday, and everything is closed before the session ends.</li>
          </ul>
        </div>
      </div>

      <div>
        {!result && !busy && (
          <div className="card">
            <h2>No scan yet</h2>
            <p className="sub">
              Pick symbols and a window. Expect very few setups — the rules are strict,
              and that is the point.
            </p>
          </div>
        )}

        {result && (
          <>
            <div className="card">
              <h2>What the scan found</h2>
              <p className="sub">
                {result.period[0]} to {result.period[1]} · {result.sessions} sessions ·{' '}
                {result.candles.toLocaleString('en-IN')} candles
              </p>
              <div className="metrics">
                <Cell k="Setups found" v={String(result.setups)} />
                <Cell k="Orders filled" v={String(result.filled)} />
                <Cell
                  k="Winners"
                  v={result.filled ? `${result.wins} of ${result.filled}` : '—'}
                />
                <Cell
                  k="Net P&L"
                  v={result.filled ? rupees(result.net_pnl) : '—'}
                  sign={result.net_pnl}
                />
              </div>
              {result.filled > 0 && result.filled < 20 && (
                <div className="note warn" style={{ marginTop: 12 }}>
                  {result.filled} trade{result.filled === 1 ? '' : 's'} is far too few to
                  read a win rate from. This tells you the setup is <em>rare</em>, not that
                  it works.
                </div>
              )}
            </div>

            {result.trades.length > 0 && (
              <div className="card">
                <h2>Every trade</h2>
                <p className="sub">R is profit measured in units of the risk taken.</p>
                <div className="scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Symbol</th>
                        <th>Entry</th>
                        <th>Stop</th>
                        <th>Risk</th>
                        <th>Exit</th>
                        <th>R</th>
                        <th>P&amp;L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.trades.map((t, i) => (
                        <tr key={`${t.symbol}-${t.entry_ts}-${i}`}>
                          <td>{t.symbol}</td>
                          <td>{t.entry.toFixed(2)}</td>
                          <td>{t.stop.toFixed(2)}</td>
                          <td>{t.risk_pct.toFixed(2)}%</td>
                          <td>{t.exits.map((e) => e.reason).join(', ') || '—'}</td>
                          <td className={t.r_multiple >= 0 ? 'pos' : 'neg'}>
                            {t.r_multiple.toFixed(2)}
                          </td>
                          <td className={t.net_pnl >= 0 ? 'pos' : 'neg'}>
                            {rupees(t.net_pnl)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            <div className="card">
              <h2>Why candidates were refused</h2>
              <p className="sub">
                Usually the most informative table here. It shows which rules are doing
                the work — and which never get reached.
              </p>
              <div className="scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Rule</th>
                      <th>Refused</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.rejections.map(([reason, count]) => (
                      <tr key={reason}>
                        <td>{reason}</td>
                        <td>{count.toLocaleString('en-IN')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card">
              <h2>What this does not mean</h2>
              <p className="sub">Returned with the result, not written into the page.</p>
              <ul className="caveats">
                {result.caveats.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Cell({ k, v, sign }: { k: string; v: string; sign?: number }) {
  const cls = sign === undefined ? '' : sign > 0 ? ' pos' : sign < 0 ? ' neg' : '';
  return (
    <div className="metric">
      <div className="k">{k}</div>
      <div className={`v${cls}`}>{v}</div>
    </div>
  );
}
