'use client';

/**
 * The one place explanation lives on the dashboard (ADR-082).
 *
 * The operator asked for no running text on the page: numbers and pictures,
 * with every definition, rule and caveat behind an info button. A hover
 * tooltip cannot be reached on a phone, so this opens on tap or click, closes
 * on a second tap, a click elsewhere or Escape, and is a real button for the
 * keyboard and screen readers.
 */

import { useEffect, useId, useRef, useState } from 'react';

export function Info({
  children,
  label = 'What is this?',
  align = 'left',
}: {
  children: React.ReactNode;
  label?: string;
  align?: 'left' | 'right';
}) {
  const [open, setOpen] = useState(false);
  const holder = useRef<HTMLSpanElement | null>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent | TouchEvent) => {
      if (holder.current && !holder.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', away);
    document.addEventListener('touchstart', away);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('touchstart', away);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  return (
    <span className="info" ref={holder}>
      <button
        type="button"
        className="info-btn"
        aria-label={label}
        aria-expanded={open}
        aria-controls={id}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((now) => !now);
        }}
      >
        i
      </button>
      {open && (
        <span id={id} role="note" className={`info-pop ${align}`}>
          {children}
        </span>
      )}
    </span>
  );
}
