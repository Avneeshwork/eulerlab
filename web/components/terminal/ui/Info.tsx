'use client';

/**
 * The one place explanation lives on the dashboard (ADR-082).
 *
 * The operator asked for no running text on the page: numbers and pictures,
 * with every definition, rule and caveat behind an info button. A hover
 * tooltip cannot be reached on a phone, so this opens on tap or click, closes
 * on a second tap, a click elsewhere or Escape, and is a real button for the
 * keyboard and screen readers.
 *
 * The popup is portalled into the `.terminal` root and positioned with
 * `position: fixed` (ADR-119). Drawn inside the card, it was cut off by any
 * card with `overflow: hidden`, sat under the next card along (each glass card
 * makes its own stacking layer), and ran off the window near the edges.
 * `.terminal` is the portal target, not `document.body`, because the colour
 * tokens are defined on that element.
 */

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { placePopover, type Placement } from '@/lib/placePopover';

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
  const [place, setPlace] = useState<Placement | null>(null);
  const holder = useRef<HTMLSpanElement | null>(null);
  const button = useRef<HTMLButtonElement | null>(null);
  const pop = useRef<HTMLSpanElement | null>(null);
  const id = useId();

  const reposition = useCallback(() => {
    if (!button.current || !pop.current) return;
    const a = button.current.getBoundingClientRect();
    // Measure the popup at its natural height, not a height capped earlier.
    pop.current.style.maxHeight = '';
    const p = pop.current.getBoundingClientRect();
    setPlace(
      placePopover(
        a,
        { width: p.width, height: p.height },
        { width: document.documentElement.clientWidth, height: window.innerHeight },
        align,
      ),
    );
  }, [align]);

  // Place before paint, so the popup never flashes at the wrong spot.
  useLayoutEffect(() => {
    if (open) reposition();
    else setPlace(null);
  }, [open, reposition]);

  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent | TouchEvent) => {
      const target = event.target as Node;
      if (holder.current?.contains(target) || pop.current?.contains(target)) return;
      setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener('mousedown', away);
    document.addEventListener('touchstart', away);
    document.addEventListener('keydown', escape);
    // Follow the button when the page, or any panel inside it, scrolls.
    window.addEventListener('scroll', reposition, true);
    window.addEventListener('resize', reposition);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('touchstart', away);
      document.removeEventListener('keydown', escape);
      window.removeEventListener('scroll', reposition, true);
      window.removeEventListener('resize', reposition);
    };
  }, [open, reposition]);

  const root = holder.current?.closest('.terminal') ?? (typeof document !== 'undefined' ? document.body : null);

  return (
    <span className="info" ref={holder}>
      <button
        ref={button}
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
      {open &&
        root &&
        createPortal(
          <span
            id={id}
            ref={pop}
            role="note"
            className={`info-pop ${place?.side ?? 'below'}`}
            style={
              place
                ? { top: place.top, left: place.left, maxHeight: place.maxHeight }
                : { top: 0, left: 0, visibility: 'hidden' }
            }
          >
            {children}
          </span>,
          root,
        )}
    </span>
  );
}
