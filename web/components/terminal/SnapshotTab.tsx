'use client';

/**
 * The trader's first screen.
 *
 * Designed against Finviz, Benzinga Pro and Koyfin (docs/RESEARCH/021), each of
 * which contributes one thing: the map, the why, and the cross-asset context.
 *
 * The band order is the design. Most dashboards open with a price, and a price
 * without regime is nearly useless — +0.4% in a calm uptrend and +0.4% inside a
 * volatility spike are different facts about different markets. So the shape of
 * the session comes first and the numbers come second.
 *
 * Bands that cannot be filled say so. A panel reading "no news source is
 * connected" is a shopping list; the same panel quietly omitted is invisible,
 * and the reader never learns their movers have no reasons attached.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { IndexLevel, Snapshot, Story, Tile, WorldMover } from '@/lib/api';

const pct = (value: number, digits = 2) =>
  `${value >= 0 ? '+' : '−'}${Math.abs(value * 100).toFixed(digits)}%`;

/** Already-percent values. `pct` takes a fraction and multiplies by 100, which
 *  is right for the panel's returns and wrong for anything a quote API hands
 *  over — those arrive as percent already, and running them through `pct`
 *  rendered NIFTY's +0.20% as "+20.00%" and INDIA VIX's -3.30% as "-330.00%". */
const pctRaw = (value: number, digits = 2) =>
  `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(digits)}%`;

const crore = (value: number) =>
  value >= 1e7 ? `₹${(value / 1e7).toFixed(1)}Cr` : `₹${(value / 1e5).toFixed(1)}L`;

/** Six steps rather than a continuous ramp.
 *
 * A gradient makes every tile a slightly different colour and none of them
 * readable; steps let the eye bin a tile instantly, which is the whole reason
 * the map beats a table. */
/** "40m", "5h", "2d" — an age is only useful if it reads at a glance. */
function age(hours: number): string {
  if (hours < 0) return '';
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 48) return `${Math.round(hours)}h`;
  return `${Math.round(hours / 24)}d`;
}

/** One index cell. Level above, change below, colour carrying the sign. */
function IndexCell({ level, muted = false }: { level: IndexLevel; muted?: boolean }) {
  const up = level.change_pct >= 0;
  return (
    <div
      className={muted ? 'ixcell muted' : 'ixcell'}
      title={`${level.name} · ${level.symbol} · via ${level.source}`}
    >
      <span className="ixname">{level.name}</span>
      <span className="ixlast">
        {level.last.toLocaleString('en-IN', {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}
      </span>
      <span className={up ? 'ixchg up' : 'ixchg dn'}>{pctRaw(level.change_pct, 2)}</span>
    </div>
  );
}

/** The ribbon: India first because it is the market being traded, then the
 *  overnight context that set the tone before it opened. */
function IndexRibbon({
  groups,
  market,
}: {
  groups: Record<Market, IndexLevel[]>;
  market: Market;
}) {
  // The selected market leads; everything else stays visible but demoted.
  // Hiding the rest would be worse than the old undifferentiated strip — an
  // Indian trader reads NIFTY against last night's S&P and this morning's
  // USD/INR, and a view with only one of those is missing the comparison that
  // makes the strip worth its height.
  const lead = groups[market] ?? [];
  const rest = (Object.keys(groups) as Market[])
    .filter((k) => k !== market)
    .flatMap((k) => groups[k] ?? []);
  if (!lead.length && !rest.length) return null;
  return (
    <div className="ixribbon">
      {lead.map((l) => (
        <IndexCell key={l.symbol} level={l} />
      ))}
      {lead.length > 0 && rest.length > 0 && <span className="ixsplit" aria-hidden="true" />}
      {rest.map((l) => (
        <IndexCell key={l.symbol} level={l} muted />
      ))}
    </div>
  );
}

/** World movers, grouped by kind. Separate from the India movers table
 *  because they answer a different question — that one asks what moved in the
 *  book being traded, this one asks what moved everywhere else overnight. */
function WorldMovers({ rows }: { rows: WorldMover[] }) {
  const groups: [string, string][] = [
    ['gainer', 'Gainers'],
    ['loser', 'Losers'],
    ['active', 'Most active'],
  ];
  return (
    <div className="tgrid">
      {groups.map(([kind, label]) => {
        const kept = rows.filter((r) => r.kind === kind).slice(0, 6);
        return (
          <div className="tpanel" key={kind}>
            <h3>{label}</h3>
            <table className="ttable">
              <tbody>
                {kept.map((r) => (
                  <tr key={`${kind}-${r.symbol}`}>
                    <td>
                      <b>{r.symbol}</b>
                      <div className="tfine">{r.name.slice(0, 26) || r.exchange}</div>
                    </td>
                    <td className="r">
                      <b className={r.change_pct >= 0 ? 'up' : 'dn'}>{pctRaw(r.change_pct, 1)}</b>
                      <div className="tfine">${r.price.toFixed(2)}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {kept.length === 0 && <div className="tempty">Nothing to show.</div>}
          </div>
        );
      })}
    </div>
  );
}

/** US sectors, ranked. The US view's answer to India's constituent map — this
 *  platform holds no US price panel, so eleven named sectors with an average
 *  change is the most honest shape-of-the-session it can draw. */
function SectorStrip({ rows }: { rows: { sector: string; change_pct: number }[] }) {
  if (!rows.length) return null;
  const widest = Math.max(...rows.map((r) => Math.abs(r.change_pct)), 0.01);
  return (
    <div className="secstrip">
      {rows.map((r) => (
        <div className="secrow" key={r.sector}>
          <span className="secname">{r.sector}</span>
          <span className="secbar">
            <i
              className={r.change_pct >= 0 ? 'up' : 'dn'}
              style={{ width: `${(Math.abs(r.change_pct) / widest) * 100}%` }}
            />
          </span>
          <b className={r.change_pct >= 0 ? 'up' : 'dn'}>{pctRaw(r.change_pct, 2)}</b>
        </div>
      ))}
    </div>
  );
}

type Market = 'IN' | 'US' | 'CRYPTO' | 'FX';

const MARKETS: [Market, string, string][] = [
  ['IN', 'India', 'NSE — full panel, breadth and constituent map'],
  ['US', 'United States', 'Indices, movers and sector performance. No constituent map: this platform holds no US price panel.'],
  [
    'CRYPTO',
    'Crypto',
    'Live majors, plus a landed 1-minute archive of 20 pairs. No breadth: six majors is not a market to count advancers in.',
  ],
  [
    'FX',
    'Forex',
    'Live majors, plus a landed 1-minute archive of 10 pairs with bid and ask. USD/INR is second because it is the pair that reprices an Indian book.',
  ],
];

/** Ranked movers for a quoted group. Crypto and FX have no constituent panel
 *  here, so the six majors ranked by move *are* the detail — there is nothing
 *  deeper to drill into, and inventing a grid would say otherwise. */
function QuotedMovers({ rows, unit }: { rows: IndexLevel[]; unit: string }) {
  const ranked = [...rows].sort((a, b) => b.change_pct - a.change_pct);
  if (!ranked.length) return null;
  const widest = Math.max(...ranked.map((r) => Math.abs(r.change_pct)), 0.01);
  return (
    <div className="secstrip">
      {ranked.map((r) => (
        <div className="secrow" key={r.symbol}>
          <span className="secname">
            {r.name}
            <i className="tfine" style={{ marginLeft: 8, fontStyle: 'normal' }}>
              {unit}
              {r.last.toLocaleString('en-US', {
                minimumFractionDigits: 2,
                maximumFractionDigits: r.last < 10 ? 4 : 2,
              })}
            </i>
          </span>
          <span className="secbar">
            <i
              className={r.change_pct >= 0 ? 'up' : 'dn'}
              style={{ width: `${(Math.abs(r.change_pct) / widest) * 100}%` }}
            />
          </span>
          <b className={r.change_pct >= 0 ? 'up' : 'dn'}>{pctRaw(r.change_pct, 2)}</b>
        </div>
      ))}
    </div>
  );
}

/** When the numbers on screen were taken. Always visible, never inferred.
 *
 *  The page used to carry a settled panel date while quoting live prices
 *  underneath it — a disagreement the reader had no way to notice. Now the
 *  stamp says which it is, and a stale one is a fact on the screen rather than
 *  an assumption in the reader's head. */
function Stamp({ snap, market }: { snap: Snapshot; market: Market }) {
  const f = snap.freshness;
  const taken = market === 'IN' ? f?.taken_at : snap.world?.taken_at;
  const live = market === 'IN' ? Boolean(f?.live) : Boolean(taken);

  let when = market === 'IN' ? snap.as_of : '—';
  if (taken) {
    const d = new Date(taken);
    if (!Number.isNaN(d.getTime())) {
      when = d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
    }
  }

  const detail =
    market === 'IN'
      ? f?.live
        ? `${f.quoted.toLocaleString('en-IN')} of ${f.of.toLocaleString('en-IN')} quoted live via Zerodha. Panel close ${f.panel_date}.`
        : `End-of-day panel, ${snap.as_of}.${f?.reason ? ` No live quote: ${f.reason}.` : ''}`
      : taken
        ? `Swept at ${taken.slice(0, 19).replace('T', ' ')} UTC by \`make world\`.`
        : 'No sweep landed — run `make world`.';

  return (
    <span className={live ? 'stamp live' : 'stamp'} title={detail}>
      {live && <span className="tdot" />}
      {live ? 'live' : 'EOD'} {when}
    </span>
  );
}

function band(move: number): string {
  if (move >= 0.05) return 'up3';
  if (move >= 0.02) return 'up2';
  if (move > 0) return 'up1';
  if (move <= -0.05) return 'dn3';
  if (move <= -0.02) return 'dn2';
  return 'dn1';
}

/** Sectors ordered by weight, so the biggest block reads first. Unclassified
 * names go last under their own heading rather than being dropped — a missing
 * sector is a gap in the data, not a reason to hide the company. */
function groupBySector(tiles: Tile[]): [string, Tile[]][] {
  const groups = new Map<string, Tile[]>();
  for (const tile of tiles) {
    const key = tile.sector || 'Unclassified';
    const bucket = groups.get(key);
    if (bucket) bucket.push(tile);
    else groups.set(key, [tile]);
  }
  return [...groups.entries()].sort((a, b) => {
    if (a[0] === 'Unclassified') return 1;
    if (b[0] === 'Unclassified') return -1;
    return weight(b[1]) - weight(a[1]);
  });
}

const weight = (tiles: Tile[]) =>
  tiles.reduce((sum, t) => sum + (t.market_cap ?? t.turnover), 0);

/** Cap-weighted move for the sector, not the average of its members: a sector
 * is what its large companies did, and equal-weighting lets a microcap swing
 * the headline. */
function sectorMove(tiles: Tile[]): number {
  const total = weight(tiles);
  if (total <= 0) return 0;
  return tiles.reduce((sum, t) => sum + t.return * (t.market_cap ?? t.turnover), 0) / total;
}

function Cell({ tile, rank }: { tile: Tile; rank: number }) {
  return (
    <a
      className="tile"
      data-band={band(tile.return)}
      data-size={rank < 2 ? 'xl' : rank < 6 ? 'lg' : 'sm'}
      title={`${tile.symbol}  ${pct(tile.return)}  ${
        tile.market_cap ? `${crore(tile.market_cap)} mcap` : `${crore(tile.turnover)} traded`
      }${tile.pe ? `  P/E ${tile.pe}` : ''}${
        tile.industry ? `  ${tile.industry}` : ''
      }`}
    >
      <b>{tile.symbol}</b>
      <span>{pct(tile.return, 1)}</span>
    </a>
  );
}

export function SnapshotTab({ workspace }: { workspace: string }) {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState('');
  // Which market the detail bands describe. India is the default because it is
  // the book being traded; the US view is context, and says so.
  const [market, setMarket] = useState<Market>('IN');

  useEffect(() => {
    let live = true;
    api
      .snapshot(workspace)
      .then((next) => {
        if (!live) return;
        if (next.ok) setSnap(next);
        else setError(next.error ?? 'snapshot unavailable');
      })
      .catch((problem) => live && setError(String(problem)));
    return () => {
      live = false;
    };
  }, [workspace]);

  if (error) {
    return (
      <div className="tnote bad">
        <span className="mk">▲</span>
        <div>{error}</div>
      </div>
    );
  }
  if (!snap) return <div className="tempty">Reading the market…</div>;

  const r = snap.regime;
  const total = r.advancers + r.decliners + r.unchanged || 1;
  const negative = r.breadth_ratio !== null && r.breadth_ratio < 1;

  return (
    <>
      {/* --- band 0: the ribbon --------------------------------------------
          Index levels come first because every number below is relative to
          them. The page spent its whole existence saying "there is no index
          here", which meant breadth had nothing to diverge from and a mover
          could not be read against its own market. */}
      <div className="mkttoggle" role="tablist" aria-label="Market">
        {MARKETS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={market === key}
            className={market === key ? 'on' : ''}
            onClick={() => setMarket(key)}
          >
            {label}
          </button>
        ))}
        <Stamp snap={snap} market={market} />
        <span className="tfine mktnote" title={MARKETS.find(([key]) => key === market)?.[2]}>
          {market === 'IN' ? 'NSE' : market === 'US' ? 'US listings' : market === 'CRYPTO' ? 'Majors' : 'Majors'}
          <abbr className="whyq">?</abbr>
        </span>
      </div>

      {snap.world?.available ? (
        <IndexRibbon
          groups={{
            IN: snap.world.india ?? [],
            US: snap.world.world ?? [],
            CRYPTO: snap.world.crypto ?? [],
            FX: snap.world.fx ?? [],
          }}
          market={market}
        />
      ) : (
        <div className="ixribbon empty">
          No index source connected
          {snap.world?.errors
            ? ` — ${Object.values(snap.world.errors)[0]}`
            : ''}
        </div>
      )}

      {/* --- band 1: regime — India only -------------------------------------
          Every number here is computed from the NSE panel: the proxy return,
          the advance/decline count, the volatility. Leaving it on screen under
          a "United States" toggle would present Indian breadth as American,
          which is worse than showing nothing — the reader has no way to tell
          from the numbers themselves. */}
      {market === 'IN' ? (
      <section className="regime tight">
        <div className="regime-lead">
          <div className="theyebrow">The session</div>
          <div className="thnum">
            <b className={r.proxy_return_20d >= 0 ? 'up' : 'dn'}>
              {pct(r.proxy_return_20d)}
            </b>
            {/* The caveat is a tooltip, not a paragraph. It has to stay
                reachable — the number is an equal-weighted proxy, not an
                index — but three lines of it in the largest type on the page
                pushed everything that matters below the fold. */}
            <span
              className="unit"
              title={`${r.proxy_note} Computed from the panel's daily history, so it ends at the ${snap.as_of} close even when breadth above it is live.`}
            >
              20d equal-weighted, to {snap.as_of} <abbr className="whyq">?</abbr>
            </span>
          </div>
        </div>

        <div className="regime-stats">
          <div className="rstat">
            <span>
              Breadth
              {snap.freshness?.live && <span className="tdot" style={{ marginLeft: 5 }} />}
            </span>
            <b className={negative ? 'dn' : 'up'}>
              {r.advancers.toLocaleString('en-IN')} / {r.decliners.toLocaleString('en-IN')}
            </b>
            <i>{r.unchanged.toLocaleString('en-IN')} unchanged</i>
          </div>
          <div className="rstat">
            <span>Volatility</span>
            <b>{(r.volatility * 100).toFixed(1)}%</b>
            <i>
              {r.volatility_before === null
                ? 'annualised, 20 days'
                : r.volatility_rising
                  ? `rising from ${(r.volatility_before * 100).toFixed(1)}%`
                  : `easing from ${(r.volatility_before * 100).toFixed(1)}%`}
            </i>
          </div>
          <div className="rstat">
            <span>As of</span>
            <b>{snap.freshness?.live ? 'live' : snap.as_of}</b>
            {/* Per stat, not per band. Breadth is counted from live quotes
                while the 20-day proxy and the volatility figure are computed
                from the panel's history — they are genuinely end-of-day and
                cannot be otherwise. One blanket "as of" over both was wrong
                whichever date it showed. */}
            <i>
              {snap.freshness?.live
                ? `breadth live · 20d from ${snap.as_of} close`
                : 'end of day, not live'}
            </i>
          </div>
        </div>

        <div className="breadth-bar" title={`${r.advancers} advancing, ${r.decliners} declining`}>
          <i className="up" style={{ width: `${(r.advancers / total) * 100}%` }} />
          <i className="flat" style={{ width: `${(r.unchanged / total) * 100}%` }} />
          <i className="dn" style={{ width: `${(r.decliners / total) * 100}%` }} />
        </div>
      </section>
      ) : (
        <p className="tfine mktgap">
          {market === 'US'
            ? 'No session line for the US: breadth, volatility and the equal-weighted proxy are all computed from the NSE panel, and this platform holds no US price panel to compute them from. The indices and sectors above are quotes, not a panel.'
            : market === 'CRYPTO'
              ? 'No session line for crypto: breadth needs a population to count advancers in, and six majors is not one. The 1-minute archive underneath covers 20 pairs — enough to backtest against, not enough to call a market.'
              : 'No session line for FX: a currency pair has no advancers and decliners, and volatility here would describe six quotes rather than a market. The 1-minute archive underneath covers 10 pairs with bid and ask.'}
        </p>
      )}

      {/* --- band 2: the map — India only ------------------------------------
          Gated rather than emptied. There is no US price panel here, so a US
          map would be a blank grid claiming the data exists. */}
      {market === 'IN' && (
      <section>
        <h3 className="report-h">The map</h3>
        {snap.map.grouped ? (
          <div className="sectors mapscroll">
            {groupBySector(snap.map.tiles).map(([sector, tiles]) => (
              <div className="sector" key={sector}>
                <div className="sector-head">
                  <b>{sector}</b>
                  <i className={sectorMove(tiles) >= 0 ? 'up' : 'dn'}>
                    {pct(sectorMove(tiles), 1)}
                  </i>
                  <span>{tiles.length}</span>
                </div>
                <div className="heatmap">
                  {tiles.map((tile, index) => (
                    <Cell key={tile.symbol} tile={tile} rank={index} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="heatmap">
            {snap.map.tiles.map((tile, index) => (
              <Cell key={tile.symbol} tile={tile} rank={index} />
            ))}
          </div>
        )}
        {!snap.map.grouped && (
          <p className="tfine" style={{ marginTop: 10 }}>
            Ungrouped &mdash; no {snap.map.missing} is connected.
          </p>
        )}
      </section>
      )}

      {/* --- band 2-US: sectors ---------------------------------------------
          The US counterpart to the map. Ranked rather than gridded, because
          eleven averages is what the free data supports and a treemap drawn
          from eleven numbers would imply constituents it does not have. */}
      {market === 'US' && snap.world?.sectors?.length ? (
        <section>
          <h3 className="report-h">
            Sectors
            <span className="tfine" style={{ marginLeft: 10, fontWeight: 400 }}>
              last US close
            </span>
          </h3>
          <SectorStrip rows={snap.world.sectors} />
        </section>
      ) : null}

      {/* --- band 2-alt: crypto and FX ---------------------------------------
          The quoted majors, ranked. These markets have a landed minute archive
          but no daily panel, so there is no breadth to count and no map to
          draw — six ranked moves is the whole honest answer. */}
      {(market === 'CRYPTO' || market === 'FX') && (
        <section>
          <h3 className="report-h">
            {market === 'CRYPTO' ? 'Majors' : 'Pairs'}
            <span
              className="tfine"
              style={{ marginLeft: 10, fontWeight: 400 }}
              title={
                market === 'CRYPTO'
                  ? 'Quotes are live; the archive underneath is 1-minute bars for 20 pairs, which is what a strategy backtests against.'
                  : 'Quotes are live; the archive underneath is 1-minute bars for 10 pairs carrying bid and ask separately, so spread is measured rather than assumed.'
              }
            >
              live, ranked <abbr className="whyq">?</abbr>
            </span>
          </h3>
          <QuotedMovers
            rows={(market === 'CRYPTO' ? snap.world?.crypto : snap.world?.fx) ?? []}
            unit={market === 'CRYPTO' ? '$' : ''}
          />
        </section>
      )}

      {/* --- band 3: movers ------------------------------------------------ */}
      {market === 'IN' && (
      <section>
        <h3 className="report-h">
          Movers
          {/* Two stacked paragraphs became one line on the heading. Both facts
              still have to be reachable — how many are quoted live, and how
              many carry a reason — but they are status, not prose, and stacked
              above the table they read as an apology for it. */}
          <span
            className="tfine hstat"
            title={[
              snap.quotes?.note,
              snap.quotes?.errors?.zerodha ? `Zerodha: ${snap.quotes.errors.zerodha}` : '',
              snap.quotes?.errors?.yahoo ? `Yahoo: ${snap.quotes.errors.yahoo}` : '',
              snap.news?.available
                ? snap.news.note
                : `No news source reachable${snap.news?.reason ? ` (${snap.news.reason})` : ''}`,
            ]
              .filter(Boolean)
              .join(' · ')}
          >
            {snap.quotes?.available && <span className="tdot" />}
            {snap.quotes?.available ? `${Object.keys(snap.quotes.quotes).length} live` : 'EOD'}
            {' · '}
            {snap.news?.covered ?? 0}/{snap.news?.asked ?? 0} with a reason
            <abbr className="whyq">?</abbr>
          </span>
        </h3>
        <div className="tgrid">
          <Movers
            title="Gainers"
            rows={snap.movers.gainers}
            stories={snap.news?.stories}
            quotes={snap.quotes?.quotes}
          />
          <Movers
            title="Losers"
            rows={snap.movers.losers}
            stories={snap.news?.stories}
            quotes={snap.quotes?.quotes}
          />
          <Movers
            title="Unusual volume"
            rows={snap.movers.unusual_volume}
            stories={snap.news?.stories}
            quotes={snap.quotes?.quotes}
            showVolume
          />
        </div>
      </section>
      )}

      {/* --- band 3½: the world --------------------------------------------
          In the India view this is overnight context: NSE opens after Wall
          Street closes and while Asia trades, so what happened there is
          already priced into the first minute here. In the US view it is the
          subject, so the heading says which it is. */}
      {snap.world?.movers?.length && (market === 'IN' || market === 'US') ? (
        <section>
          <h3 className="report-h">
            {market === 'IN' ? 'Moving elsewhere' : 'Movers'}
            <span
              className="tfine"
              style={{ marginLeft: 10, fontWeight: 400 }}
              title="Filtered to $5 and above: the raw feed's median mover was a $4.75 micro-cap. Leveraged ETFs still slip through, so one underlying can appear under several tickers."
            >
              US listings, above $5 <abbr className="whyq">?</abbr>
            </span>
          </h3>
          <WorldMovers rows={snap.world.movers} />
        </section>
      ) : null}

      {/* --- band 3a: the tape ---------------------------------------------- */}
      {snap.news?.available && snap.news.tape.length > 0 && (
        <section>
          <h3 className="report-h">
            The tape
            <span
              className="tfine"
              style={{ marginLeft: 10, fontWeight: 400 }}
              title="Newest first, tagged with every listed company the headline names. A headline must carry the ticker or two words of the registered name to be tagged — 'Reliance Communications' is not a Reliance Industries story."
            >
              last {snap.news.window ?? '1d'} <abbr className="whyq">?</abbr>
            </span>
          </h3>
          <div className="tpanel tscroll">
            <ul className="ttape">
              {snap.news.tape.map((story) => (
                <li key={story.link || story.title}>
                  <span className="tage mono">{age(story.age_hours)}</span>
                  <a href={story.link} target="_blank" rel="noreferrer">
                    {story.title}
                  </a>
                  <span className="tfine">
                    {(story.affects?.length ? story.affects : story.symbols).join(', ')}
                    {story.sectors?.length ? (
                      <span className="tsector">{story.sectors.join(' · ')}</span>
                    ) : null}
                    {story.publisher ? ` · ${story.publisher}` : ''}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {/* --- band 3b: the calendar ------------------------------------------ */}
      <section>
        <h3 className="report-h">
          The calendar
          {snap.catalysts.high_impact !== undefined && (
            <span className="tfine" style={{ marginLeft: 10, fontWeight: 400 }}>
              {snap.catalysts.high_impact} high-impact of {snap.catalysts.total}
            </span>
          )}
        </h3>
        {snap.catalysts.available && snap.catalysts.events?.length ? (
          <div className="tpanel tscroll">
            <table className="ttable">
              <tbody>
                {snap.catalysts.events.map((event) => (
                  <tr key={`${event.at}-${event.title}`} data-past={event.past}>
                    <td style={{ width: 54 }}>
                      <span className="ccy">{event.country}</span>
                    </td>
                    <td>
                      <b>{event.title}</b>
                      <div className="tfine">
                        {new Date(event.at).toLocaleString('en-IN', {
                          weekday: 'short',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                        {event.past ? ' · released' : ' · upcoming'}
                      </div>
                    </td>
                    <td className="r">
                      <span className="impact" data-level={event.impact.toLowerCase()}>
                        {event.impact}
                      </span>
                    </td>
                    <td className="r tfine" style={{ width: 130 }}>
                      {event.forecast && <>forecast {event.forecast}</>}
                      {event.previous && <div>prev {event.previous}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="tfine">{snap.catalysts.reason}</p>
        )}

      </section>

      {/* --- band 4: cross-asset ------------------------------------------- */}
      <section>
        <h3 className="report-h">Across the book of markets</h3>
        <div className="cross">
          {snap.cross_asset.map((cell) => (
            <div className="cross-cell" key={cell.asset_class}>
              <span>{cell.label}</span>
              <b>{cell.instruments.toLocaleString('en-IN')}</b>
              <i>{cell.detail}</i>
            </div>
          ))}
        </div>
      </section>

      {/* --- band 5: evidence ---------------------------------------------- */}
      <section>
        <h3 className="report-h">Is any of it evidence</h3>
        <div className="tpanel">
          <div className="tfacts">
            <div className="tfact">
              <span>Noise bar</span>
              <b>{snap.evidence.bar.toFixed(2)}</b>
            </div>
            <div className="tfact">
              <span>Strategies</span>
              <b>{snap.evidence.strategies}</b>
            </div>
            <div className="tfact">
              <span>Clearing it</span>
              <b className={snap.evidence.clearing ? 'up' : ''}>{snap.evidence.clearing}</b>
            </div>
            <div className="tfact">
              <span>Trials spent</span>
              <b>{snap.evidence.trials}</b>
            </div>
          </div>
          <p className="tfine" style={{ marginTop: 12 }}>
            Every other terminal shows patterns. This one is built to say when a pattern
            is indistinguishable from luck, which is why the bar sits on the first screen
            rather than three clicks in.
            {snap.evidence.clearing_names.length > 0 &&
              ` Clearing today: ${snap.evidence.clearing_names.join(', ')}.`}
          </p>
        </div>
      </section>

      {/* --- what is missing, said out loud -------------------------------- */}
      <section>
        <h3 className="report-h">What this screen cannot show yet</h3>
        <ul className="gaps">
          {snap.gaps.map((gap) => (
            <li key={gap}>{gap}</li>
          ))}
        </ul>
      </section>
    </>
  );
}

function Movers({
  title,
  rows,
  stories,
  quotes,
  showVolume = false,
}: {
  title: string;
  rows: Tile[];
  stories?: Record<string, Story>;
  quotes?: Record<string, { last: number; change_pct: number; source: string }>;
  showVolume?: boolean;
}) {
  return (
    <div className="tpanel">
      <h3>{title}</h3>
      <table className="ttable">
        <tbody>
          {rows.map((row) => (
            <tr key={row.symbol}>
              <td>
                <b>{row.symbol}</b>
                <div className="tfine">{crore(row.turnover)} traded</div>
                {stories &&
                  (stories[row.symbol] ? (
                    <a
                      className="tstory"
                      href={stories[row.symbol].link}
                      target="_blank"
                      rel="noreferrer"
                      title={stories[row.symbol].title}
                    >
                      {stories[row.symbol].title}
                      <span className="tage">
                        {stories[row.symbol].publisher} · {age(stories[row.symbol].age_hours)}
                      </span>
                    </a>
                  ) : (
                    // Stated, not left blank. A large move with no news is a
                    // different fact from one with news, and an empty cell
                    // would read as "not checked".
                    <div className="tnostory">no story in 24h</div>
                  ))}
              </td>
              <td className="r">
                <b className={row.return >= 0 ? 'up' : 'dn'}>{pct(row.return, 1)}</b>
                {showVolume && row.relative_volume !== null && (
                  <div className="tfine">{row.relative_volume}× normal</div>
                )}
                {quotes?.[row.symbol] && (
                  // The live price sits under the settled one rather than
                  // replacing it: they answer different questions, and
                  // overwriting the close would quietly change what the
                  // percentage column is a percentage of.
                  <div className="tlivepx" title={`live via ${quotes[row.symbol].source}`}>
                    {quotes[row.symbol].last.toLocaleString('en-IN', {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}
                    <span className={quotes[row.symbol].change_pct >= 0 ? 'up' : 'dn'}>
                      {' '}
                      {pctRaw(quotes[row.symbol].change_pct, 2)}
                    </span>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <div className="tempty">Nothing to show.</div>}
    </div>
  );
}
