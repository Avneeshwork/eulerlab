'use client';

/**
 * Pricing a run before it is allowed to start.
 *
 * The most important component in this interface. A console makes running
 * things cheap, which is exactly what would let someone spend fifty trials in
 * an afternoon by clicking. So the cost is stated first, in the unit that is
 * actually spent, and the free path — re-reading results that already exist —
 * is a first-class button rather than something you get by accident.
 */

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { RunPrice } from '@/lib/api';

export function RunComposer({
  strategies,
  instruments,
  batch,
}: {
  strategies: string[];
  instruments: number;
  batch: string;
}) {
  const [price, setPrice] = useState<RunPrice | null>(null);
  // Assumed cached until a result cache exists to ask. Stated in the UI rather
  // than hidden, because a cost estimate resting on an unbuilt component is
  // exactly the kind of number that gets believed.
  const [cached, setCached] = useState(0);

  const configurations = strategies.length;

  useEffect(() => {
    if (configurations === 0) {
      setPrice(null);
      return;
    }
    api.priceRun(configurations, Math.min(cached, configurations)).then(setPrice).catch(() => undefined);
  }, [configurations, cached]);

  const run = useCallback(() => {
    window.alert(
      'The batch runner is not built yet (ADR-036, step 5).\n\n' +
        'This screen exists first because the cost check has to be in place ' +
        'before running many strategies is one click — not after.'
    );
  }, []);

  return (
    <div className="card">
      <h2>Run</h2>
      <p className="sub">A batch states its price before it can be launched.</p>

      <div className="compose-grid">
        <div className="cfield">
          <span className="lab">Strategies</span>
          <span className="val">
            {configurations === 0 ? 'none selected' : `${configurations} selected`}
          </span>
        </div>
        <div className="cfield">
          <span className="lab">Instruments</span>
          <span className="val">
            {batch || 'none'}{' '}
            {instruments > 0 && <span className="muted">· {instruments} names</span>}
          </span>
        </div>
      </div>

      {configurations === 0 && (
        <p className="muted" style={{ marginTop: 12 }}>
          Select at least one strategy in the fleet above.
        </p>
      )}

      {price && (
        <>
          <div className={`cost${price.irreversible ? '' : ' free'}`}>
            <div className="cost-h">
              {price.irreversible ? 'This run cannot be undone' : 'This run spends nothing'}
            </div>
            <div className="cost-move">
              <span className="from">{price.bar_before.toFixed(2)}</span>
              <span className="arw">→</span>
              <span className="to">{price.bar_after.toFixed(2)}</span>
              <span className="cost-unit">
                noise bar, after {price.new_trials} new trial{price.new_trials === 1 ? '' : 's'}
              </span>
            </div>
            <p className="cost-note">{price.note}</p>
          </div>

          <label className="cachedrow">
            <span>
              already cached
              <span
                className="help"
                tabIndex={0}
                role="note"
                data-tip="The result cache is not built yet (ADR-036, step 5). Until it is, this is a what-if control, not a measurement — set it to see how caching changes the cost."
              >
                ?
              </span>
            </span>
            <input
              type="number"
              min={0}
              max={configurations}
              value={cached}
              onChange={(e) => setCached(Math.max(0, Number(e.target.value)))}
            />
            <span className="muted">of {configurations}</span>
          </label>

          <div className="actions">
            <button className={price.irreversible ? 'go danger' : 'go safe'} onClick={run}>
              {price.irreversible
                ? `Spend ${price.new_trials} trial${price.new_trials === 1 ? '' : 's'} and run`
                : 'Run cached only — free'}
            </button>
            <span className="muted">there is no un-spend</span>
          </div>
        </>
      )}
    </div>
  );
}
