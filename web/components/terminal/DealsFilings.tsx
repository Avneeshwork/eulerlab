'use client';

/**
 * Dashboard → India → Deals & filings (ADR-096): what NSE publishes each
 * evening about who traded, borrowed, financed, pledged and filed. Read from
 * the summary `make market-reports` writes; every panel names its date.
 * Context only: none of it has been through the gate.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Deal, DealClient, MarketReports, MtfRow } from '@/lib/api';
import { Info } from './ui';
import './dealsfilings.css';

const crore = (value: number) =>
  `₹${value.toLocaleString('en-IN', { maximumFractionDigits: value >= 100 ? 0 : 1 })}Cr`;
const count = (value: number) =>
  value >= 1e7
    ? `${(value / 1e7).toFixed(2)}Cr`
    : value >= 1e5
      ? `${(value / 1e5).toFixed(1)}L`
      : value.toLocaleString('en-IN');
const pct = (fraction: number | null) =>
  fraction === null ? '—' : `${fraction >= 0 ? '+' : '−'}${Math.abs(fraction * 100).toFixed(1)}%`;
const day = (iso: string | null | undefined) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '';

function Heading({ title, sub, info }: { title: string; sub?: string; info: React.ReactNode }) {
  return (
    <h3 className="report-h mc-h">
      {title}
      {sub && <span className="tfine mc-sub">{sub}</span>}
      <Info>{info}</Info>
    </h3>
  );
}

function Missing({ title, reason }: { title: string; reason: string }) {
  return (
    <section>
      <Heading title={title} info={`Not available: ${reason}.`} />
      <div className="tpanel mc-missing">—</div>
    </section>
  );
}

function Bar({ share, tone }: { share: number; tone: 'up' | 'down' | 'acc' }) {
  return <span className={`mc-fill ${tone}`} style={{ width: `${Math.max(2, share * 100)}%` }} />;
}

function DealTable({ rows }: { rows: Deal[] }) {
  const top = Math.max(1, ...rows.map((r) => r.value_cr));
  return rows.length ? (
    <div className="mc-scroll">
      <table className="ttable mc-num">
        <thead>
          <tr>
            <th>Stock</th>
            <th>Who</th>
            <th>Side</th>
            <th>Value</th>
            <th>Price</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.symbol}-${r.client}-${i}`}>
              <td>
                {r.symbol}
                {r.kind === 'block' && <span className="tfine"> · block</span>}
              </td>
              <td className="mc-quiet" title={r.client}>
                {r.client.length > 28 ? `${r.client.slice(0, 27)}…` : r.client}
              </td>
              <td className={r.side === 'BUY' ? 'pos' : 'neg'}>{r.side === 'BUY' ? 'Buy' : 'Sell'}</td>
              <td className="mc-cellbar">
                <Bar share={r.value_cr / top} tone={r.side === 'BUY' ? 'up' : 'down'} />
                <span className="dfl-v">{crore(r.value_cr)}</span>
              </td>
              <td className="mc-quiet">{r.price.toLocaleString('en-IN')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <div className="mc-missing">No deals that day.</div>
  );
}

function ClientList({ title, rows, side }: { title: string; rows: DealClient[]; side: 'buy' | 'sell' }) {
  const picked = rows.filter((r) => (side === 'buy' ? r.net_cr > 0 : r.net_cr < 0));
  const top = Math.max(1, ...picked.map((r) => Math.abs(r.net_cr)));
  return (
    <div className="tpanel">
      <h3 className="mc-h">{title}</h3>
      {picked.length ? (
        <table className="ttable mc-num">
          <tbody>
            {picked.map((r) => (
              <tr key={r.client}>
                <td title={r.client}>{r.client.length > 30 ? `${r.client.slice(0, 29)}…` : r.client}</td>
                <td className="mc-cellbar">
                  <Bar share={Math.abs(r.net_cr) / top} tone={side === 'buy' ? 'up' : 'down'} />
                  <span className="dfl-v">{crore(Math.abs(r.net_cr))}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="mc-missing">—</div>
      )}
    </div>
  );
}

function MtfList({ title, rows, info }: { title: string; rows: MtfRow[]; info: string }) {
  const top = Math.max(0.01, ...rows.map((r) => Math.abs(r.change ?? 0)));
  return (
    <div className="tpanel">
      <h3 className="mc-h">
        {title}
        <Info>{info}</Info>
      </h3>
      <table className="ttable mc-num">
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol}>
              <td>{r.symbol}</td>
              <td className="mc-cellbar">
                <Bar share={Math.abs(r.change ?? 0) / top} tone={(r.change ?? 0) >= 0 ? 'up' : 'down'} />
                <span className="dfl-v">{pct(r.change)}</span>
              </td>
              <td className="mc-quiet">{crore(r.cr)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DealsFilings() {
  const [data, setData] = useState<MarketReports | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    api
      .marketReports()
      .then((next) => alive && setData(next))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, []);

  if (error) return <div className="tempty">Could not read deals and filings: {error}</div>;
  if (!data) return <div className="tempty">Reading deals and filings…</div>;
  if (!data.ok) return <div className="tempty">No deals and filings yet: {data.reason}</div>;
  const { deals, ban, mtf, shorts, filings, pledges, ipos } = data;

  return (
    <>
      {/* --- F&O ban and IPOs: the short answers first ------------------- */}
      <section>
        <div className="tgrid mc-two">
          {ban?.available ? (
            <div className="tpanel">
              <h3 className="mc-h">
                F&amp;O ban
                <span className="tfine mc-sub">{day(ban.as_of)}</span>
                <Info>
                  Stocks whose open interest passed 95% of the market-wide position limit. No new F&amp;O
                  positions may be opened in them until it falls below 80%; existing ones can only be
                  reduced. New means not in the previous day&apos;s list.
                </Info>
              </h3>
              {ban.symbols.length ? (
                <div className="dfl-chips">
                  {ban.symbols.map((s) => (
                    <span key={s} className={`dfl-chip ${ban.added.includes(s) ? 'new' : ''}`}>
                      {s}
                      {ban.added.includes(s) && <small> new</small>}
                    </span>
                  ))}
                </div>
              ) : (
                <div className="mc-missing">Nothing in the ban.</div>
              )}
              {ban.removed.length > 0 && (
                <p className="tfine">Out of the ban: {ban.removed.join(', ')}</p>
              )}
            </div>
          ) : (
            <Missing title="F&O ban" reason={ban?.reason ?? 'not built'} />
          )}
          {ipos?.available ? (
            <div className="tpanel">
              <h3 className="mc-h">
                IPOs open now
                <span className="tfine mc-sub">{day(ipos.as_of)}</span>
                <Info>
                  Issues taking bids on NSE today. Subscribed is bids against shares offered across all
                  categories, as NSE last reported it. SME issues are on NSE Emerge.
                </Info>
              </h3>
              {ipos.open.length ? (
                <table className="ttable mc-num">
                  <tbody>
                    {ipos.open.map((r) => (
                      <tr key={r.symbol}>
                        <td title={r.company}>
                          {r.symbol}
                          {r.series === 'SME' && <span className="tfine"> · SME</span>}
                        </td>
                        <td className="mc-quiet">{r.price.replaceAll('Rs.', '₹')}</td>
                        <td>{r.subscribed.toFixed(2)}×</td>
                        <td className="mc-quiet">closes {r.closes.slice(0, 6)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="mc-missing">No issue open.</div>
              )}
              {ipos.listed.length > 0 && (
                <p className="tfine">
                  Listed lately:{' '}
                  {ipos.listed
                    .slice(0, 6)
                    .map((r) => `${r.symbol} (${day(r.listed)})`)
                    .join(', ')}
                </p>
              )}
            </div>
          ) : (
            <Missing title="IPOs" reason={ipos?.reason ?? 'not built'} />
          )}
        </div>
      </section>

      {/* --- Bulk and block deals ----------------------------------------- */}
      {deals?.available ? (
        <section>
          <Heading
            title="Bulk and block deals"
            sub={`${deals.today_count} on ${day(deals.as_of)}`}
            info={
              <>
                A bulk deal is one client trading more than 0.5% of a company&apos;s shares in a day on the
                normal market; a block deal is a single large trade in NSE&apos;s separate block
                window. Value is quantity times NSE&apos;s reported price. Biggest first; the client names
                are NSE&apos;s.
              </>
            }
          />
          <div className="tpanel">
            <DealTable rows={deals.today} />
          </div>
          <Heading
            title="Who bought and sold most"
            sub={`${day(deals.since)} to ${day(deals.as_of)} · ${deals.count} deals`}
            info="Each client's bulk and block buys minus sells over the last 30 trading days, all stocks together."
          />
          <div className="tgrid mc-two">
            <ClientList title="Net buyers" rows={deals.buyers} side="buy" />
            <ClientList title="Net sellers" rows={deals.sellers} side="sell" />
          </div>
        </section>
      ) : (
        <Missing title="Bulk and block deals" reason={deals?.reason ?? 'not built'} />
      )}

      {/* --- Margin trading ------------------------------------------------ */}
      {mtf?.available ? (
        <section>
          <Heading
            title="Margin trading (MTF)"
            sub={`${day(mtf.as_of)} · ${crore(mtf.totals_cr.closing ?? 0)} funded`}
            info={
              <>
                Money brokers lend clients to hold shares, by stock, as NSE reports it each day. A rise means
                more buying on borrowed money. Change is against {day(mtf.compared_with)}; listed when ₹50
                crore or more is funded. Fresh {crore(mtf.totals_cr.fresh ?? 0)}, repaid{' '}
                {crore(mtf.totals_cr.liquidated ?? 0)} on the day.
              </>
            }
          />
          <div className="tgrid mc-two">
            <MtfList title="Rising" rows={mtf.rising} info="Largest rise in funded amount over the week." />
            <MtfList title="Falling" rows={mtf.falling} info="Largest fall in funded amount over the week." />
          </div>
        </section>
      ) : (
        <Missing title="Margin trading" reason={mtf?.reason ?? 'not built'} />
      )}

      {/* --- Short selling and lending -------------------------------------- */}
      {shorts?.available ? (
        <section>
          <Heading
            title="Short selling and stock lending"
            sub={day(shorts.as_of)}
            info={
              <>
                Short sold is the quantity institutions disclosed selling short that day ({shorts.short_count}{' '}
                stocks). Lent is shares borrowed through NSE&apos;s lending and borrowing market (SLBM) on{' '}
                {day(shorts.slbm_as_of)}, with the highest lending fee per share. Borrowing usually precedes a
                short or covers a delivery.
              </>
            }
          />
          <div className="tgrid mc-two">
            <div className="tpanel">
              <h3 className="mc-h">Most short sold</h3>
              <table className="ttable mc-num">
                <tbody>
                  {shorts.short_sold.map((r) => (
                    <tr key={r.symbol}>
                      <td>{r.symbol}</td>
                      <td>{count(r.qty)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="tpanel">
              <h3 className="mc-h">Most borrowed (SLBM)</h3>
              <table className="ttable mc-num">
                <tbody>
                  {shorts.lent.map((r) => (
                    <tr key={r.symbol}>
                      <td>{r.symbol}</td>
                      <td>{count(r.qty)}</td>
                      <td className="mc-quiet">fee ₹{r.fee.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      ) : (
        <Missing title="Short selling" reason={shorts?.reason ?? 'not built'} />
      )}

      {/* --- Promoter and insider filings ----------------------------------- */}
      {filings?.available ? (
        <section>
          <Heading
            title="Promoter and large-holder filings"
            sub={`last ${filings.days} days`}
            info={
              <>
                SEBI takeover rules (SAST regulation 29) make anyone crossing 5% of a company, or changing a
                holding above it by 2%, file the trade. Promoter rows are marked. % is of the company; After is
                their holding once it settled.
              </>
            }
          />
          <div className="tpanel">
            <div className="mc-scroll">
              <table className="ttable mc-num">
                <thead>
                  <tr>
                    <th>Stock</th>
                    <th>Who</th>
                    <th>Side</th>
                    <th>%</th>
                    <th>After</th>
                    <th>Filed</th>
                  </tr>
                </thead>
                <tbody>
                  {filings.sast.map((r, i) => (
                    <tr key={`${r.symbol}-${i}`}>
                      <td title={r.company}>{r.symbol}</td>
                      <td className="mc-quiet" title={r.who}>
                        {r.who.length > 26 ? `${r.who.slice(0, 25)}…` : r.who}
                        {r.promoter && <span className="tfine"> · promoter</span>}
                      </td>
                      <td className={r.side === 'BUY' ? 'pos' : 'neg'}>{r.side === 'BUY' ? 'Bought' : 'Sold'}</td>
                      <td>{r.pct.toFixed(2)}%</td>
                      <td className="mc-quiet">{r.after_pct.toFixed(2)}%</td>
                      <td className="mc-quiet">{r.time.slice(0, 6)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <Heading
            title="Insider trading disclosures"
            sub={`${filings.insider_count} in ${filings.days} days`}
            info="Filings under SEBI's insider trading rules (PIT). NSE's list names the company and the rule, not the size; the figures are in each filing, linked."
          />
          <div className="tpanel">
            <div className="dfl-chips">
              {filings.insider.map((r, i) => (
                <a key={`${r.symbol}-${i}`} className="dfl-chip" href={r.link} target="_blank" rel="noreferrer" title={`${r.company} · ${r.regulation} · ${r.time}`}>
                  {r.symbol}
                </a>
              ))}
            </div>
          </div>
        </section>
      ) : (
        <Missing title="Filings" reason={filings?.reason ?? 'not built'} />
      )}

      {/* --- Pledges -------------------------------------------------------- */}
      {pledges?.available ? (
        <section>
          <Heading
            title="Promoter pledges"
            sub={`${pledges.count} companies · ${day(pledges.as_of)}`}
            info={
              <>
                Shares promoters have pledged as loan collateral, from their latest shareholding filing. Of the
                company is the pledged shares as a share of all shares; of promoter is the share of the
                promoters&apos; own stake. A lender can sell pledged shares if the price falls far enough.
                Filings older than two quarters are left out.
              </>
            }
          />
          <div className="tpanel">
            <table className="ttable mc-num">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Of the company</th>
                  <th>Of promoter</th>
                  <th>Quarter</th>
                </tr>
              </thead>
              <tbody>
                {pledges.top.map((r) => (
                  <tr key={r.company}>
                    <td>{r.company.replace(/ Limited$/, '')}</td>
                    <td className="mc-cellbar">
                      <Bar share={r.of_company_pct / 100} tone="down" />
                      <span className="dfl-v">{r.of_company_pct.toFixed(1)}%</span>
                    </td>
                    <td>{r.of_promoter_pct.toFixed(0)}%</td>
                    <td className="mc-quiet">{r.quarter}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        <Missing title="Promoter pledges" reason={pledges?.reason ?? 'not built'} />
      )}
    </>
  );
}
