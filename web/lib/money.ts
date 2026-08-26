/**
 * One money formatter, because five of them disagreed.
 *
 * `ReportDialog`, `ExplainDialog`, `AdoptedReport`, `SweepPanel` and `Library`
 * each grew their own, with three different signatures — `money(v)`,
 * `money(v, market)` and `moneyIn(class)(v)`. The one that took no market wrote
 * ₹ unconditionally, which was right while every backtest here was NSE and
 * became wrong the moment a US run could be opened: a QQQ figure displayed as
 * "₹25,894" is off by the exchange rate and reads as directly comparable to the
 * India rows beside it.
 *
 * The lesson is not "someone forgot". Formatting money is a decision about
 * *which market the number came from*, and a function that cannot see the
 * market cannot make it. So the market is a required argument here.
 */

/** The symbol each market's numbers are denominated in. */
const SYMBOL: Record<string, string> = {
  equity: '₹',
  us: '$',
  crypto: '$',
  fx: '$',
  mutual_fund: '₹',
};

/** Indian digit grouping for rupees, Western for everything else. */
const LOCALE: Record<string, string> = { '₹': 'en-IN' };

/**
 * Format an amount in the currency of the market it came from.
 *
 * Unknown markets fall back to ₹ rather than throwing: a new asset class should
 * render a slightly wrong symbol rather than blank the page, and the fallback
 * is the one the rest of this platform defaults to.
 */
export function money(value: number, market: string): string {
  const symbol = SYMBOL[market] ?? '₹';
  const locale = LOCALE[symbol] ?? 'en-US';
  // A minus sign rather than a hyphen: at small sizes a hyphen next to a digit
  // reads as part of the number.
  const sign = value < 0 ? '−' : '';
  return `${sign}${symbol}${Math.abs(Math.round(value)).toLocaleString(locale)}`;
}

/** Bound to one market, for callers formatting many figures from one run. */
export function moneyIn(market: string): (value: number) => string {
  return (value: number) => money(value, market);
}

/** The bare symbol, for labels like "Return on $1M". */
export function currencySymbol(market: string): string {
  return SYMBOL[market] ?? '₹';
}
