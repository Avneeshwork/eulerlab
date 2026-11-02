/**
 * Where an info popup goes on screen (ADR-119).
 *
 * The popup is drawn in a layer above every card, so no card can clip it. This
 * function decides its position from three things: where the (i) button is,
 * how big the popup is, and how big the window is. It is pure so it can be
 * tested without a browser.
 *
 * Rules, in order:
 *   1. Open below the button. If it does not fit below and there is more room
 *      above, open above instead.
 *   2. If it fits on neither side, cap its height to the larger side; the
 *      popup then scrolls inside itself.
 *   3. Line its edge up with the button (left edge by default, right edge for
 *      align='right'), then slide it sideways so it stays inside the window.
 */

export type Rect = { top: number; left: number; right: number; bottom: number };

export type Placement = {
  top: number;
  left: number;
  side: 'below' | 'above';
  maxHeight: number;
};

/** Space kept between the popup and the window edge, in pixels. */
export const EDGE = 8;
/** Space between the button and the popup, in pixels. */
export const GAP = 6;

export function placePopover(
  anchor: Rect,
  pop: { width: number; height: number },
  view: { width: number; height: number },
  align: 'left' | 'right' = 'left',
): Placement {
  const roomBelow = view.height - anchor.bottom - GAP - EDGE;
  const roomAbove = anchor.top - GAP - EDGE;
  const side: Placement['side'] = pop.height <= roomBelow || roomBelow >= roomAbove ? 'below' : 'above';
  const maxHeight = Math.max(0, side === 'below' ? roomBelow : roomAbove);
  const height = Math.min(pop.height, maxHeight);
  const top = side === 'below' ? anchor.bottom + GAP : anchor.top - GAP - height;

  const width = Math.min(pop.width, view.width - 2 * EDGE);
  const wanted = align === 'right' ? anchor.right + EDGE - width : anchor.left - EDGE;
  const left = Math.min(Math.max(wanted, EDGE), view.width - EDGE - width);

  return { top, left, side, maxHeight };
}
