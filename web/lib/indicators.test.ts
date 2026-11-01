/**
 * Indicator maths against hand-worked numbers. Run with `npm test`
 * (Node's own test runner; no test framework is installed).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bollinger, ema, macd, rsi, sma } from './indicators.ts';

const close = (a: number | null, b: number, tol = 1e-9) => {
  assert.ok(a !== null, 'expected a value, got null');
  assert.ok(Math.abs((a as number) - b) < tol, `${a} != ${b}`);
};

test('SMA is the mean of the last n closes, null until the window fills', () => {
  const out = sma([1, 2, 3, 4, 5], 3);
  assert.deepEqual(out.slice(0, 2), [null, null]);
  close(out[2], 2);
  close(out[3], 3);
  close(out[4], 4);
});

test('EMA is seeded with the SMA, then k = 2/(n+1)', () => {
  // n = 3, k = 0.5: seed (1+2+3)/3 = 2; then 4*0.5 + 2*0.5 = 3; then 5*0.5 + 3*0.5 = 4.
  const out = ema([1, 2, 3, 4, 5], 3);
  assert.deepEqual(out.slice(0, 2), [null, null]);
  close(out[2], 2);
  close(out[3], 3);
  close(out[4], 4);
});

test("RSI uses Wilder's smoothing", () => {
  // n = 2. Changes: +1, -1, +2. First averages: gain 0.5, loss 0.5 -> RSI 50.
  // Next: gain (0.5*1 + 2)/2 = 1.25, loss (0.5*1 + 0)/2 = 0.25 -> RS 5 -> RSI 83.33…
  const out = rsi([10, 11, 10, 12], 2);
  assert.deepEqual(out.slice(0, 2), [null, null]);
  close(out[2], 50);
  close(out[3], 100 - 100 / 6);
});

test('RSI is 100 when nothing fell', () => {
  close(rsi([1, 2, 3, 4], 2)[3], 100);
});

test('MACD is fast EMA minus slow EMA; signal is an EMA of it', () => {
  const values = [1, 2, 3, 4, 5, 6];
  const out = macd(values, 2, 3, 2);
  // EMA2: seed 1.5 at i=1, k=2/3: i2 2.5, i3 3.5, i4 4.5, i5 5.5.
  // EMA3: seed 2 at i=2, k=0.5: i3 3, i4 4, i5 5. MACD from i2: 0.5 each.
  close(out.macd[2], 0.5);
  close(out.macd[5], 0.5);
  // Signal EMA2 over MACD from i2: seed at i3 = 0.5.
  assert.equal(out.signal[2], null);
  close(out.signal[3], 0.5);
  close(out.histogram[5], 0);
});

test('Bollinger bands are SMA ± width × population sd', () => {
  // Window [2, 4, 4, 4, 5, 5, 7, 9]: mean 5, population sd 2.
  const out = bollinger([2, 4, 4, 4, 5, 5, 7, 9], 8, 2);
  close(out.middle[7], 5);
  close(out.upper[7], 9);
  close(out.lower[7], 1);
});
