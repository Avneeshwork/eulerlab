/**
 * Limits, breaches and the kill switch: one line on Deployment, the limits
 * one click away (operator, 2026-11-16; it was its own tab).
 *
 * The architecture document puts risk on the home screen, one click away. It
 * was reachable only from a terminal, which means in practice it was not
 * reachable at the moment anyone would want it.
 *
 * Every number here is read from `config/killswitch.yaml` through the same
 * loader `oms/killswitch.py` enforces with. Not a second copy: a risk screen
 * showing limits that have drifted from the enforced ones is worse than no
 * risk screen, because it is believed.
 */

'use client';

import { useEffect, useState } from 'react';

import { api } from '@/lib/api';

type Limit = { name: string; value: number; unit: string; note: string };
type Risk = {
  ok: boolean;
  tripped: boolean;
  reason: string;
  limits: Limit[];
  reset_note: string;
  error?: string;
};

function amount(value: number, unit: string): string {
  if (unit === 'INR') {
    return `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
  }
  return `${value.toLocaleString('en-IN')} ${unit}`;
}

export function RiskTab() {
  const [risk, setRisk] = useState<Risk | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const read = () =>
      api
        .risk()
        .then((r) => {
          if (alive) setRisk(r);
        })
        .catch(() => undefined);
    read();
    const timer = window.setInterval(read, 15000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  if (!risk) return null;

  if (!risk.ok) {
    return <div className="tnote bad">Kill-switch limits could not be read: {risk.error}</div>;
  }

  return (
    <div className="tpanel ks-line">
      <div className="ks-head">
        <b>Kill switch</b>
        <span className="tbadge" data-tone={risk.tripped ? 'down' : 'up'}>
          {risk.tripped ? 'Tripped' : 'Armed'}
        </span>
        <span className="tfine ks-reason" title={risk.reset_note}>
          {risk.tripped ? risk.reason || 'reason not recorded' : 'no limit breached'} · {risk.limits.length} limits
        </span>
        <button className="tbtn sm" type="button" onClick={() => setOpen((v) => !v)}>
          {open ? 'Hide limits' : 'Show limits'}
        </button>
      </div>
      {open && (
        <table className="ttable">
          <tbody>
            {risk.limits.map((limit) => (
              <tr key={limit.name}>
                <td>{limit.name}</td>
                <td className="r">{amount(limit.value, limit.unit)}</td>
                <td className="tfine">{limit.note || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
