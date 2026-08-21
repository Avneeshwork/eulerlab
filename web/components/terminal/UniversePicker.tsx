'use client';

/**
 * Which instruments a backtest may choose from.
 *
 * This existed only implicitly before: every run saw the whole panel and no
 * result recorded which instruments it had been offered. Two problems, and the
 * second is worse — you could not tell what a stored number was a number
 * *about*.
 *
 * `all` is the default because it is what every existing result ran on, so
 * defaulting to anything else would quietly make new numbers incomparable with
 * old ones. `nifty100` is marked recommended, because the cost model is
 * calibrated on traded names and the full panel includes many that barely
 * trade. Both facts are shown rather than one being chosen silently.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Universe } from '@/lib/api';

export function UniversePicker({
  value,
  onChange,
  label = 'Universe',
}: {
  value: string;
  onChange: (name: string) => void;
  label?: string;
}) {
  const [universes, setUniverses] = useState<Universe[]>([]);

  useEffect(() => {
    api
      .universes()
      .then((response) => setUniverses(response.universes))
      .catch(() => setUniverses([]));
  }, []);

  const chosen = universes.find((u) => u.name === value);

  return (
    <label className="tsort" style={{ marginLeft: 0 }} title={chosen?.note || undefined}>
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {universes.length === 0 && <option value={value}>{value}</option>}
        {universes.map((universe) => (
          <option key={universe.name} value={universe.name}>
            {universe.name} — {universe.symbols.toLocaleString('en-IN')} names
            {universe.recommended ? ' (recommended)' : ''}
          </option>
        ))}
      </select>
    </label>
  );
}

/** The one-line explanation of whatever is currently selected. */
export function UniverseNote({ value }: { value: string }) {
  const [universes, setUniverses] = useState<Universe[]>([]);
  useEffect(() => {
    api
      .universes()
      .then((response) => setUniverses(response.universes))
      .catch(() => setUniverses([]));
  }, []);
  const chosen = universes.find((u) => u.name === value);
  if (!chosen?.note) return null;
  return (
    <p className="tfine">
      <b>{chosen.name}</b> — {chosen.note}
    </p>
  );
}
