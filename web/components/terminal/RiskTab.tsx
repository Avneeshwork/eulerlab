/**
 * Limits, breaches and the kill switch.
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

import { Info } from '@/components/terminal/ui';
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

  if (!risk) return <section className="tsection" />;

  if (!risk.ok) {
    return (
      <section className="tsection">
        <h2 className="ui-heading">
          Limits could not be read
          <Info>
            The limits the order path enforces are unchanged by this: it reads the same file
            directly. What is broken is this screen&rsquo;s view of them.
          </Info>
        </h2>
        <p className="tdesc">{risk.error}</p>
      </section>
    );
  }

  return (
    <section className="tsection">
      <h2 className="thero">
        {risk.tripped ? 'Tripped' : 'Armed'} <i>kill switch</i>
        <Info>
          {risk.tripped
            ? 'Trading is stopped.'
            : 'No limit has been breached. Each one below is a count or a rupee amount a human can check by hand against the day’s activity: a limit whose breach cannot be confirmed independently is a limit nobody trusts at the moment it fires.'}{' '}
          {risk.reset_note}
        </Info>
      </h2>

      {risk.tripped ? (
        <p className="tdesc">
          Trading is stopped. Reason: <b>{risk.reason || 'not recorded'}</b>
        </p>
      ) : null}

      <div className="tpanel" style={{ padding: 16, marginTop: 24 }}>
        <h3>What stops trading</h3>
        <table className="ttable">
          <thead>
            <tr>
              <th>Limit</th>
              <th style={{ textAlign: 'right' }}>Trips at</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {risk.limits.map((limit) => (
              <tr key={limit.name}>
                <td>{limit.name}</td>
                <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                  {amount(limit.value, limit.unit)}
                </td>
                <td className="tfine">{limit.note || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

    </section>
  );
}
