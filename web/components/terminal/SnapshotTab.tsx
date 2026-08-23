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
import type { Snapshot, Story, Tile } from '@/lib/api';

const pct = (value: number, digits = 2) =>
  `${value >= 0 ? '+' : '−'}${Math.abs(value * 100).toFixed(digits)}%`;

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
      {/* --- band 1: regime ------------------------------------------------ */}
      <section className="regime">
        <div className="regime-lead">
          <div className="theyebrow">The session</div>
          <div className="thnum">
            <b className={r.proxy_return_20d >= 0 ? 'up' : 'dn'}>
              {pct(r.proxy_return_20d)}
            </b>
            <span className="unit">20 days, equal-weighted</span>
          </div>
          <p className="tfine" style={{ marginTop: 8 }}>
            {r.proxy_note}
          </p>
        </div>

        <div className="regime-stats">
          <div className="rstat">
            <span>Breadth</span>
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
            <b>{snap.as_of}</b>
            <i>end of day, not live</i>
          </div>
        </div>

        <div className="breadth-bar" title={`${r.advancers} advancing, ${r.decliners} declining`}>
          <i className="up" style={{ width: `${(r.advancers / total) * 100}%` }} />
          <i className="flat" style={{ width: `${(r.unchanged / total) * 100}%` }} />
          <i className="dn" style={{ width: `${(r.decliners / total) * 100}%` }} />
        </div>
      </section>

      {/* --- band 2: the map ----------------------------------------------- */}
      <section>
        <h3 className="report-h">The map</h3>
        {snap.map.grouped ? (
          <div className="sectors">
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
        <p className="tfine" style={{ marginTop: 10 }}>
          {snap.map.note}{' '}
          {snap.map.grouped
            ? 'Grouped because a red tile is one company\u2019s problem and a red block is a rotation, and only the grouping lets the eye tell them apart.'
            : `Ungrouped \u2014 no ${snap.map.missing} is connected.`}
        </p>
      </section>

      {/* --- band 3: movers ------------------------------------------------ */}
      <section>
        <h3 className="report-h">Movers</h3>
        {snap.quotes?.note && (
          <p className="tfine tlive" data-live={snap.quotes.available}>
            {snap.quotes.available && <span className="tdot" />}
            {snap.quotes.note}
            {snap.quotes.errors?.yahoo ? ` Yahoo: ${snap.quotes.errors.yahoo}.` : ''}
            {snap.quotes.errors?.zerodha ? ` Zerodha: ${snap.quotes.errors.zerodha}.` : ''}
          </p>
        )}
        <p className="tfine" style={{ marginBottom: 12 }}>
          {snap.news?.available
            ? snap.news.note
            : `No stock-specific news source is reachable${
                snap.news?.reason ? ` (${snap.news.reason})` : ''
              }, so every mover here is a price without a reason.`}
        </p>
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

      {/* --- band 3a: the tape ---------------------------------------------- */}
      {snap.news?.available && snap.news.tape.length > 0 && (
        <section>
          <h3 className="report-h">
            The tape
            <span className="tfine" style={{ marginLeft: 10, fontWeight: 400 }}>
              last {snap.news.window ?? '1d'}, movers only
            </span>
          </h3>
          <p className="tfine" style={{ marginBottom: 12 }}>
            Newest first, tagged with every listed company the headline names and
            the sectors they sit in — a story naming four lenders is one event with
            four exposures. A headline must carry the ticker or two words of the
            registered name to be tagged: &ldquo;Reliance Communications&rdquo; is not a
            Reliance Industries story, and printing it beside that price would be a
            false reason rather than a weak one.
          </p>
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
        {snap.catalysts.available && (
          <p className="tfine" style={{ marginTop: 10 }}>{snap.catalysts.reason}</p>
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
                      {pct(quotes[row.symbol].change_pct, 2)}
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
