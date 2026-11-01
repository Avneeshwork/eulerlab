import { test } from 'node:test';
import assert from 'node:assert/strict';
import { AGENT_STRIP, AGENTS_TAB, pollDelay } from './poll.ts';

test('a hidden page is not polled', () => {
  assert.equal(pollDelay(AGENTS_TAB, true, true), null);
  assert.equal(pollDelay(AGENT_STRIP, false, true), null);
});

test('a running agent is watched faster than an idle one', () => {
  assert.equal(pollDelay(AGENTS_TAB, true, false), 5_000);
  assert.equal(pollDelay(AGENTS_TAB, false, false), 30_000);
});

test('the strip asks less often than the tab that watches the run', () => {
  assert.ok(AGENT_STRIP.busyMs > AGENTS_TAB.busyMs);
  assert.ok(AGENT_STRIP.idleMs >= AGENTS_TAB.idleMs);
});

test('no rate is faster than 5 s, the 2.5 s of T-4373', () => {
  for (const rates of [AGENTS_TAB, AGENT_STRIP]) assert.ok(rates.busyMs >= 5_000);
});
