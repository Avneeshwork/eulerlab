'use client';

import { useEffect } from 'react';
import { pollDelay, type PollRates } from './poll';

/**
 * Call `read` now and then on the delay `pollDelay` gives. Stops while the
 * browser tab is hidden and asks once at once when it is shown again, so a
 * tab left open in the background sends nothing.
 */
export function usePoll(read: () => void, rates: PollRates, busy: boolean, enabled = true): void {
  useEffect(() => {
    if (!enabled) return undefined;
    let timer: number | undefined;
    const schedule = () => {
      window.clearInterval(timer);
      const delay = pollDelay(rates, busy, document.hidden);
      timer = delay === null ? undefined : window.setInterval(read, delay);
    };
    const onVisible = () => {
      if (!document.hidden) read();
      schedule();
    };
    read();
    schedule();
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [read, rates, busy, enabled]);
}
