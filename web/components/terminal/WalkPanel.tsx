'use client';

/**
 * Walk-forward evidence: the only out-of-sample number this platform produces.
 *
 * Everything else in a strategy row is in-sample. The parameter was chosen by
 * searching a window and then reported on that same window; the noise bar
 * corrects for *how much searching happened*, which is a real correction and a
 * different thing from testing on days the choice never saw.
 *
 * The panel leads with the verdict rather than with PBO, because the number
 * alone is misread in a specific and predictable way — see below.
 */

import type { WalkResult } from '@/lib/api';

function tone(walk: WalkResult): string {
  if (walk.splits < 4) return 'verdict-error';
  // A high PBO on a broadly profitable grid is not a warning. When every
  // setting works they perform near-identically, so which one wins in sample is
  // close to a coin toss and PBO climbs toward 0.5 by construction.
  if (walk.pbo > 0.25 && walk.most_settings_work) return 'verdict-flat';
  if (walk.pbo > 0.5) return 'verdict-loss';
  if (walk.pbo > 0.25) return 'verdict-tail';
  return 'verdict-ok';
}

export function WalkPanel({ walk }: { walk: WalkResult }) {
  const profitableShare = walk.settings_total
    ? walk.settings_profitable_oos / walk.settings_total
    : 0;

  return (
    <div className="walk">
      <div className="walk-head">
        <h4>Out of sample</h4>
        <span className="walk-where">
          {walk.symbol} · {walk.splits} splits
        </span>
        <span className={`verdict ${tone(walk)}`}>PBO {walk.pbo.toFixed(2)}</span>
      </div>

      <p className="walk-read">{walk.verdict}</p>

      <div className="walk-stats">
        <div>
          <span>Splits profitable</span>
          <b className={walk.oos_positive_splits * 2 > walk.splits ? 'pos' : 'neg'}>
            {walk.oos_positive_splits}/{walk.splits}
          </b>
        </div>
        <div>
          <span>Settings that work</span>
          <b className={profitableShare >= 0.75 ? 'pos' : undefined}>
            {walk.settings_profitable_oos}/{walk.settings_total}
          </b>
        </div>
        <div>
          <span>Winner, per split</span>
          <b className={walk.winner_oos_pnl < 0 ? 'neg' : 'pos'}>
            {Math.round(walk.winner_oos_pnl).toLocaleString()}
          </b>
        </div>
        <div>
          <span>Median setting</span>
          <b className={walk.median_oos_pnl < 0 ? 'neg' : 'pos'}>
            {Math.round(walk.median_oos_pnl).toLocaleString()}
          </b>
        </div>
      </div>

      <p className="walk-fine">
        Sessions are cut into six blocks and two are held out at a time, in every
        combination. PBO asks how often the setting that won on the training blocks lands
        below the median on the held-out ones — so it indicts <em>the act of choosing</em>,
        not any single setting. A low PBO does not certify the winner; it says choosing
        this way, on this data, is not by itself a mistake.
      </p>
    </div>
  );
}
