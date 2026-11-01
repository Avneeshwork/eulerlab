/**
 * Daily bars rolled up into weekly and monthly candles.
 *
 * A week runs Monday to Sunday and a month is the calendar month. A candle's
 * date is its first trading day, its open that day's open, its close the last
 * day's close, high and low the extremes and volume the sum, as TradingView
 * and Kite draw them. Done here rather than on the server because the chart
 * already holds ten years of daily bars; a second request would add nothing.
 */

export type Ohlc = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type Period = 'W' | 'M';

/** The Monday of the week (UTC) that holds this ISO date. */
function weekOf(iso: string): string {
  const day = new Date(`${iso}T00:00:00Z`);
  const back = (day.getUTCDay() + 6) % 7;
  day.setUTCDate(day.getUTCDate() - back);
  return day.toISOString().slice(0, 10);
}

export function rollUp(bars: Ohlc[], period: Period): Ohlc[] {
  const out: Ohlc[] = [];
  let key = '';
  for (const bar of bars) {
    const next = period === 'W' ? weekOf(bar.time) : bar.time.slice(0, 7);
    const last = out[out.length - 1];
    if (next !== key || !last) {
      out.push({ ...bar });
      key = next;
      continue;
    }
    last.high = Math.max(last.high, bar.high);
    last.low = Math.min(last.low, bar.low);
    last.close = bar.close;
    last.volume += bar.volume;
  }
  return out;
}
