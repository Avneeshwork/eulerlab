import { test } from 'node:test';
import assert from 'node:assert/strict';
import { rollUp, type Ohlc } from './bars.ts';

const bar = (time: string, open: number, high: number, low: number, close: number): Ohlc => ({
  time,
  open,
  high,
  low,
  close,
  volume: 10,
});

// Thu 30 Oct 2025 to Tue 4 Nov 2025: two weeks, two months.
const days = [
  bar('2025-10-30', 10, 12, 9, 11),
  bar('2025-10-31', 11, 15, 10, 14),
  bar('2025-11-03', 14, 14, 8, 9),
  bar('2025-11-04', 9, 13, 9, 12),
];

test('weekly candles start on the first trading day of each week', () => {
  const weeks = rollUp(days, 'W');
  assert.deepEqual(weeks, [
    { time: '2025-10-30', open: 10, high: 15, low: 9, close: 14, volume: 20 },
    { time: '2025-11-03', open: 14, high: 14, low: 8, close: 12, volume: 20 },
  ]);
});

test('monthly candles follow the calendar month', () => {
  const months = rollUp(days, 'M');
  assert.equal(months.length, 2);
  assert.deepEqual(months[1], { time: '2025-11-03', open: 14, high: 14, low: 8, close: 12, volume: 20 });
});

test('a Sunday belongs to the week that began the Monday before', () => {
  const weeks = rollUp([bar('2025-11-03', 1, 1, 1, 1), bar('2025-11-09', 2, 2, 2, 2)], 'W');
  assert.equal(weeks.length, 1);
});

test('rolling up does not change the daily bars', () => {
  const copy = JSON.parse(JSON.stringify(days));
  rollUp(days, 'W');
  assert.deepEqual(days, copy);
});
