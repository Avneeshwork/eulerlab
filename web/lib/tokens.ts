/**
 * Read a design token (tokens.css) as a concrete colour, for libraries such as
 * lightweight-charts that cannot take `var(--x)`.
 *
 * Tokens are defined on `.terminal`, so they are read there. Reading them off
 * `<html>` returned nothing, and the theme attribute also lives on
 * `.terminal`, which is why the candles used to ignore the dark toggle.
 */
export function token(name: string, fallback = ''): string {
  if (typeof document === 'undefined') return fallback;
  const root = document.querySelector('.terminal') ?? document.documentElement;
  const value = getComputedStyle(root).getPropertyValue(name).trim();
  return value || fallback;
}
