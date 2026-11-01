/**
 * Chart indicators, computed in the browser from the bars the chart already
 * holds. Pure functions over closes: no data source of their own, so an
 * indicator cannot disagree with the candles under it.
 *
 * Each returns one value per input, `null` where the window is not yet full,
 * so the output lines up index for index with the bars.
 *
 * Definitions (tested against hand-worked numbers in `indicators.test.ts`):
 * - SMA(n): mean of the last n closes.
 * - EMA(n): seeded with SMA(n) at index n-1, then k = 2/(n+1).
 * - RSI(n): Wilder's smoothing; first average is the simple mean of the first
 *   n changes, then avg = (prev*(n-1) + current)/n. RSI = 100 - 100/(1+RS);
 *   100 when there are no losses.
 * - MACD(12, 26, 9): EMA12 - EMA26; signal = EMA9 of MACD; histogram = MACD - signal.
 * - Bollinger(20, 2): SMA20 ± 2 × population standard deviation of the window.
 */

export type Series = (number | null)[];

export function sma(values: number[], n: number): Series {
  const out: Series = [];
  let sum = 0;
  for (let i = 0; i < values.length; i += 1) {
    sum += values[i];
    if (i >= n) sum -= values[i - n];
    out.push(i >= n - 1 ? sum / n : null);
  }
  return out;
}

export function ema(values: number[], n: number): Series {
  const out: Series = [];
  const k = 2 / (n + 1);
  let prev: number | null = null;
  for (let i = 0; i < values.length; i += 1) {
    if (i < n - 1) {
      out.push(null);
      continue;
    }
    if (prev === null) {
      let sum = 0;
      for (let j = i - n + 1; j <= i; j += 1) sum += values[j];
      prev = sum / n;
    } else {
      prev = values[i] * k + prev * (1 - k);
    }
    out.push(prev);
  }
  return out;
}

export function rsi(values: number[], n = 14): Series {
  const out: Series = values.map(() => null);
  if (values.length <= n) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= n; i += 1) {
    const change = values[i] - values[i - 1];
    if (change > 0) gain += change;
    else loss -= change;
  }
  gain /= n;
  loss /= n;
  const value = () => (loss === 0 ? 100 : 100 - 100 / (1 + gain / loss));
  out[n] = value();
  for (let i = n + 1; i < values.length; i += 1) {
    const change = values[i] - values[i - 1];
    gain = (gain * (n - 1) + Math.max(change, 0)) / n;
    loss = (loss * (n - 1) + Math.max(-change, 0)) / n;
    out[i] = value();
  }
  return out;
}

export function macd(
  values: number[],
  fast = 12,
  slow = 26,
  signalPeriod = 9,
): { macd: Series; signal: Series; histogram: Series } {
  const f = ema(values, fast);
  const s = ema(values, slow);
  const line: Series = values.map((_, i) => {
    const a = f[i];
    const b = s[i];
    return a === null || b === null ? null : a - b;
  });
  const start = line.findIndex((v) => v !== null);
  const signal: Series = values.map(() => null);
  if (start >= 0) {
    const tail = ema(line.slice(start) as number[], signalPeriod);
    tail.forEach((v, j) => {
      signal[start + j] = v;
    });
  }
  const histogram: Series = line.map((v, i) => {
    const sig = signal[i];
    return v === null || sig === null ? null : v - sig;
  });
  return { macd: line, signal, histogram };
}

export function bollinger(
  values: number[],
  n = 20,
  width = 2,
): { middle: Series; upper: Series; lower: Series } {
  const middle = sma(values, n);
  const upper: Series = [];
  const lower: Series = [];
  for (let i = 0; i < values.length; i += 1) {
    const mean = middle[i];
    if (mean === null) {
      upper.push(null);
      lower.push(null);
      continue;
    }
    let squares = 0;
    for (let j = i - n + 1; j <= i; j += 1) squares += (values[j] - mean) ** 2;
    const sd = Math.sqrt(squares / n);
    upper.push(mean + width * sd);
    lower.push(mean - width * sd);
  }
  return { middle, upper, lower };
}
