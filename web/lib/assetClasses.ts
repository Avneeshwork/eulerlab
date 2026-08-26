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
