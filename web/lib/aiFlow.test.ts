import { test } from 'node:test';
import assert from 'node:assert/strict';

import { ago, filterResults, istDay, openView, todaysRuns } from './aiFlow.ts';

test('every old AI view name opens the view that holds it now', () => {
  assert.deepEqual(openView('inbox'), { view: 'overview' });
  assert.deepEqual(openView('live'), { view: 'overview' });
  assert.deepEqual(openView('brief'), { view: 'results', filter: 'brief' });
  assert.deepEqual(openView('research'), { view: 'team', team: 'cards' });
  assert.deepEqual(openView('ask'), { view: 'team', team: 'cards' });
  assert.deepEqual(openView('org'), { view: 'team', team: 'org' });
  assert.deepEqual(openView('calendar'), { view: 'team', team: 'schedule' });
  assert.deepEqual(openView('quality'), { view: 'team', team: 'health' });
  assert.deepEqual(openView('log'), { view: 'team', team: 'health' });
  assert.deepEqual(openView(''), { view: 'overview' });
  assert.deepEqual(openView('nonsense'), { view: 'overview' });
});

test('filters split research results from agent checks', () => {
  const rows = [
    { kind: 'batch', pipeline: true },
    { kind: 'verdict', pipeline: true },
    { kind: 'paper', pipeline: true },
    { kind: 'check', pipeline: false },
    { kind: 'brief', pipeline: false },
  ];
  assert.equal(filterResults(rows, 'research').length, 3);
  assert.deepEqual(
    filterResults(rows, 'verdicts').map((r) => r.kind),
    ['verdict', 'paper'],
  );
  assert.deepEqual(
    filterResults(rows, 'checks').map((r) => r.kind),
    ['check'],
  );
  assert.deepEqual(
    filterResults(rows, 'brief').map((r) => r.kind),
    ['brief'],
  );
  assert.equal(filterResults(rows, 'all').length, 5);
});

test('the IST day turns over at 18:30 UTC', () => {
  assert.equal(istDay('2026-11-07T18:29:00+00:00'), '2026-11-07');
  assert.equal(istDay('2026-11-07T18:30:00+00:00'), '2026-11-08');
  assert.equal(istDay('bad'), '');
});

test("today's runs: running first, then today's newest, nothing older", () => {
  const now = Date.parse('2026-11-07T15:00:00Z');
  const agents = [
    { name: 'a', state: 'ok', started: '2026-11-07T10:00:00+00:00' },
    { name: 'b', state: 'ok', started: '2026-11-06T10:00:00+00:00' },
    { name: 'c', state: 'running', started: '2026-11-07T09:00:00+00:00' },
    { name: 'd', state: 'failed', started: '2026-11-07T12:00:00+00:00' },
    { name: 'e', state: 'idle', started: '' },
  ];
  assert.deepEqual(
    todaysRuns(agents, now).map((a) => a.name),
    ['c', 'd', 'a'],
  );
});

test('ago reads in seconds, minutes, hours and days', () => {
  const now = Date.parse('2026-11-07T15:00:00Z');
  assert.equal(ago('2026-11-07T14:59:30Z', now), '30 s ago');
  assert.equal(ago('2026-11-07T14:30:00Z', now), '30 min ago');
  assert.equal(ago('2026-11-07T12:00:00Z', now), '3 h ago');
  assert.equal(ago('2026-11-05T15:00:00Z', now), '2 d ago');
  assert.equal(ago('', now), '');
});
