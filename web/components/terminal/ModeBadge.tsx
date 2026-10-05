/**
 * Which mode the platform is in, on every screen.
 *
 * The architecture document's first design principle: mode is always visible,
 * so nobody places a real order by mistake. The badge here makes a stronger
 * claim than a paper/live toggle would. `Stage.LIVE` exists in the enum and
 * nothing produces it, there is no live broker adapter (S-015), and no capital
 * has ever been traded — so PAPER is a fact about this build, not a setting
 * someone could flip by accident.
 *
 * It also carries the kill switch, because a tripped switch is the one thing
 * that should interrupt whatever screen you are on.
 */

'use client';

import { useEffect, useState } from 'react';

import { api } from '@/lib/api';

type Mode = {
  ok: boolean;
  mode: string;
  live_possible: boolean;
  why: string;
  kill_switch_tripped: boolean;
};

export function ModeBadge() {
  const [mode, setMode] = useState<Mode | null>(null);

  useEffect(() => {
    let alive = true;
    const read = () =>
      api
        .mode()
        .then((m) => {
          if (alive) setMode(m);
        })
        .catch(() => undefined);
    read();
    // Polled, because a kill switch tripped by another process is exactly the
    // state this must not keep quiet about until the next page load.
    const timer = window.setInterval(read, 15000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  if (!mode?.ok) return null;

  if (mode.kill_switch_tripped) {
    return (
      <span className="tmode tripped" title="Reset is a separate process with separate credentials.">
        KILL SWITCH TRIPPED
      </span>
    );
  }

  return (
    <span className="tmode" title={mode.why}>
      {mode.mode.toUpperCase()}
      {!mode.live_possible && <b> · no live path</b>}
    </span>
  );
}
