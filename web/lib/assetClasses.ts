/**
 * The asset classes a backtest can run on, in one place.
 *
 * Three separate components carried their own hardcoded `<option>` lists, and
 * they drifted: US equity was landed, panelled, costed and sweepable while all
 * three still offered only NSE, crypto and mutual funds. FX had been runnable
 * for longer still and was offered nowhere.
 *
 * A list copied into three files is a list that will be wrong in at least one
 * of them. This is the single source; adding a class means editing it once.
 *
 * Ordered by how much data stands behind each, not alphabetically — the first
 * entry is what a picker lands on by default and should be the one most likely
 * to be wanted.
 */

export type AssetClassOption = {
  value: string;
  label: string;
  /** Shown where there is room for it — a picker, not a dropdown. */
  note: string;
};

export const ASSET_CLASSES: AssetClassOption[] = [
  { value: 'equity', label: 'Equities (NSE)', note: 'Kite minute bars and the daily panel' },
  { value: 'us', label: 'US equities', note: 'Alpaca daily and 1-minute, IEX feed' },
  { value: 'crypto', label: 'Crypto', note: 'Binance minute archive, Delta fees' },
  { value: 'fx', label: 'FX', note: 'FXCM minute bars, spread measured per bar' },
  { value: 'mutual_fund', label: 'Mutual funds', note: 'AMFI NAV history, direct growth plans' },
];

/** Display name for a class id, falling back to the raw id.
 *
 * Falls back rather than throwing, so a class the backend gains before the UI
 * knows its name is unlabelled instead of invisible. */
export function assetClassLabel(value: string): string {
  return ASSET_CLASSES.find((c) => c.value === value)?.label ?? value.replace('_', ' ');
}

/** Whether a class uses NSE's liquidity-ranked batches.
 *
 * Only NSE equity has them: the batches are built from our own turnover
 * history (ADR-008) and mean nothing to another market. */
export function usesBatches(value: string): boolean {
  return value === 'equity';
}

/** The markets a strategy can actually be pointed at.
 *
 * The Library's filter chips were built from the classes the strategies
 * *declare*, and only two values exist across all 36 — `equity` and `crypto`.
 * So US equity and FX never appeared, and there was no way into them from the
 * page that lists what you can run.
 *
 * The declared class is not the market, though. It says which engine and cost
 * model a strategy belongs to, and the market is chosen per run: `orb_breakout`
 * and `orb_breakout_in` are the same detect function pointed at QQQ and at
 * NIFTYBEES. Treating the tag as the market is what hid two markets behind it.
 *
 * Minute signals run wherever there are minute bars. Daily strategies need a
 * panel, which exists for the two equity markets. Crypto is its own engine and
 * its own fee schedule, so it does not mix.
 */
export function marketsFor(strategy: { asset_class: string; timeframe: string }): string[] {
  if (strategy.asset_class === 'crypto') return ['crypto'];
  if (strategy.timeframe === '1m') return ['equity', 'us', 'fx'];
  return ['equity', 'us'];
}

/** Markets at least one of these strategies can run on, in canonical order.
 *
 * Derived rather than listed so a chip never appears with nothing behind it —
 * a filter that always returns zero is worse than an absent one, because it
 * reads as "we have none of that" rather than "that is not offered here".
 */
export function marketsPresent(
  strategies: { asset_class: string; timeframe: string }[]
): AssetClassOption[] {
  const available = new Set(strategies.flatMap(marketsFor));
  return ASSET_CLASSES.filter((option) => available.has(option.value));
}
