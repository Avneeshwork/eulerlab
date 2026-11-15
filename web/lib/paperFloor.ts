/**
 * The operator's paper floor (2026-11-16, ADR-207): a strategy whose backtest
 * Sharpe is below 0.5 is not offered for paper trading. The Sharpe is the one at
 * realistic fills where the server has it (ADR-205), else the stored one. A
 * strategy with no Sharpe at all is below the floor.
 *
 * This is the workbench's rule only; the server's deploy preflight does not
 * check it yet (T-4646).
 */
import type { FleetStrategy } from '@/lib/api';

export const PAPER_MIN_SHARPE = 0.5;

export function paperSharpe(s: FleetStrategy): number | null {
  return (s as FleetStrategy & { realistic?: { sharpe: number } | null }).realistic?.sharpe ?? s.sharpe;
}

/** Why paper trading is refused by the floor, or '' when it is not. */
export function belowPaperFloor(s: FleetStrategy): string {
  const sharpe = paperSharpe(s);
  if (sharpe === null) return 'No backtest Sharpe: paper trading needs at least 0.5.';
  return sharpe < PAPER_MIN_SHARPE
    ? `Backtest Sharpe ${sharpe.toFixed(2)} is below the 0.5 paper floor.`
    : '';
}
