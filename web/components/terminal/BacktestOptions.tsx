/**
 * The options a backtest takes, in one place.
 *
 * There were three backtest entry points and each offered a different subset.
 * The Library dialog had the window presets, an explicit date range, the tier
 * and the starting capital. The Run tab had the tier and a window but neither
 * dates nor capital. The Build tab had none of it — `days: 800, tier: 'B',
 * starting_cash: 1_000_000` were written into the call, so a strategy composed
 * there could only ever be tested one way and there was nothing on screen to
 * say so.
 *
 * They all read the same state out of the terminal page already; they simply
 * rendered different parts of it. So this is the controls, once, and the three
 * surfaces render it rather than each deciding what a backtest is allowed to
 * ask.
 *
 * Layout is a prop because the surfaces genuinely differ: a dialog has a
 * column to fill and the Run tab has a toolbar. What must not differ is which
 * questions you can ask, and that is what this fixes.
 */

'use client';

export const WINDOWS = [250, 500, 800, 1200, 1800, 2500, 2869];

export type DateRange = { start: string; end: string };

export function BacktestOptions({
  window: days,
  tier,
  dateRange,
  startingCash,
  onWindow,
  onTier,
  onDateRange,
  onStartingCash,
  layout = 'form',
}: {
  window: number;
  tier: 'A' | 'B';
  dateRange: DateRange;
  startingCash: number;
  onWindow: (days: number) => void;
  onTier: (tier: 'A' | 'B') => void;
  onDateRange: (range: DateRange) => void;
  onStartingCash: (cash: number) => void;
  /** 'form' stacks the groups; 'bar' keeps them on one wrapping row. */
  layout?: 'form' | 'bar';
}) {
  const gap = layout === 'form' ? 12 : 0;
  return (
    <>
      <div className="ttools" style={{ marginBottom: gap }}>
        {WINDOWS.map((value) => (
          <button
            key={value}
            className="tchip"
            type="button"
            aria-pressed={days === value}
            onClick={() => onWindow(value)}
          >
            {value >= 2869 ? 'everything' : `${value}d`}
          </button>
        ))}
        <label className="tsort">
          Tier
          <select value={tier} onChange={(event) => onTier(event.target.value as 'A' | 'B')}>
            <option value="B">B — event-driven engine</option>
            <option value="A">A — vectorised screen</option>
          </select>
        </label>
      </div>

      {/* An explicit window and the account it is sized against.
       *
       * The presets above always end *today*, so every question they can ask
       * is about the recent past — "how did this behave through 2022" was
       * unaskable. And starting cash is not cosmetic: position sizing is a
       * fraction of equity, so it scales every position and decides whether a
       * capped fee binds at all. */}
      <div className="ttools" style={{ marginBottom: gap }}>
        <label className="tsort" style={{ marginLeft: 0 }}>
          From
          <input
            type="date"
            value={dateRange.start}
            onChange={(event) => onDateRange({ ...dateRange, start: event.target.value })}
          />
        </label>
        <label className="tsort">
          To
          <input
            type="date"
            value={dateRange.end}
            onChange={(event) => onDateRange({ ...dateRange, end: event.target.value })}
          />
        </label>
        <label className="tsort">
          Capital
          <input
            type="number"
            min={1000}
            step={100000}
            value={startingCash}
            onChange={(event) => onStartingCash(Number(event.target.value) || 1_000_000)}
            style={{ width: 130 }}
          />
        </label>
        {(dateRange.start || dateRange.end) && (
          <button
            className="tchip"
            type="button"
            onClick={() => onDateRange({ start: '', end: '' })}
            title="Fall back to the day presets above, which always end today."
          >
            clear dates
          </button>
        )}
      </div>
    </>
  );
}

/** What the current selection means, in a sentence. */
export function BacktestWindowNote({ dateRange }: { dateRange: DateRange }) {
  return (
    <p className="tfine" style={{ marginBottom: 12 }}>
      {dateRange.start && dateRange.end
        ? `Running ${dateRange.start} to ${dateRange.end}. The presets above are ignored while both dates are set.`
        : 'Set both dates to run a fixed window; with one or neither, the preset above applies and the run ends today.'}
    </p>
  );
}
