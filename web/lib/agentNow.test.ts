import { test } from 'node:test';
import assert from 'node:assert/strict';
import { nowLine } from './agentNow.ts';

const steps = [
  { at: '2026-11-01T10:00:00Z', kind: 'step', text: '12 card(s) queued' },
  { at: '2026-11-01T10:55:00Z', kind: 'step', text: 'Testing mom-63-ab12cd: IC screen first' },
];

test('the newest step is the now line, with its own time', () => {
  const line = nowLine(steps, true);
  assert.equal(line.text, 'Testing mom-63-ab12cd: IC screen first');
  assert.equal(line.since, '2026-11-01T10:55:00Z');
});

test('the now step is not listed again below it', () => {
  assert.deepEqual(nowLine(steps, true).before, [steps[0]]);
});

test('a finished run keeps every step and has no now line', () => {
  const line = nowLine(steps, false);
  assert.equal(line.text, '');
  assert.deepEqual(line.before, steps);
});

test('a run that has reported nothing yet has no time to show', () => {
  assert.deepEqual(nowLine([], true), { text: '', since: '', before: [] });
});
