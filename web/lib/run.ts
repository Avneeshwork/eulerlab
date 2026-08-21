/**
 * Starting a backtest and waiting for it, in one place.
 *
 * Every surface that runs something — the library row button, the Run tab, the
 * Build tab — goes through here, so the polling interval, the failure handling
 * and the "this spends no trial" accounting cannot drift apart between them.
 */

import { api } from '@/lib/api';
import type { BatchResult } from '@/lib/api';

const POLL_MS = 700;
const TIMEOUT_MS = 10 * 60 * 1000;

export class RunFailed extends Error {}

/**
 * Run a batch and resolve when it finishes.
 *
 * Rejects rather than resolving with a partial result: a caller that got a
 * half-finished batch back would render its numbers as though the run had
 * completed.
 */
export async function runBatch(
  strategies: string[],
  days: number,
  tier: 'A' | 'B',
  universe: string,
  instruments: string[] = [],
  assetClass = 'equity',
  onProgress?: (message: string) => void
): Promise<BatchResult> {
  const started = await api.runBatch(strategies, days, tier, universe, instruments, assetClass);
  if (!started.ok || !started.job) throw new RunFailed(started.error ?? 'could not start the run');

  const deadline = Date.now() + TIMEOUT_MS;
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    const job = await api.batchJob(started.job);
    if (job.message) onProgress?.(job.message);
    if (job.status === 'done') return job.result;
    if (job.status === 'failed') throw new RunFailed(job.error || 'the run failed');
    if (Date.now() > deadline) {
      throw new RunFailed(
        `still running after ${Math.round(TIMEOUT_MS / 60000)} minutes — giving up on waiting, ` +
          `though the job itself may still finish`
      );
    }
  }
}
