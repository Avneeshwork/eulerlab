import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buttonHelp, headline, needsYou, plainTitle, whatItDoes, who, whyRaised } from './taskWords.ts';

const titles = new Map([
  ['head_platform', 'Head of Data and Platform'],
  ['engineering', 'Engineering agent'],
]);
const base = {
  owner: 'engineering',
  created_by: 'head_platform',
  kind: 'fix_code',
  status: 'assigned',
  parent: 'T-1',
};

test('stacked watchdog prefixes come off the title', () => {
  const t =
    'Watchdog: task overdue since 2026-11-06: Watchdog: task overdue since 2026-11-05: Optimize slow pytest tests';
  assert.deepEqual(plainTitle(t), {
    text: 'Optimize slow pytest tests',
    lateSince: '2026-11-05',
    watchdog: true,
  });
  assert.equal(headline({ ...base, title: t }), 'Find out why a task is late: “Optimize slow pytest tests”');
  assert.equal(
    headline({ ...base, title: 'Watchdog: engineering run failed' }),
    'Look into a problem: engineering run failed',
  );
  assert.equal(headline({ ...base, title: 'Fix a file' }), 'Fix a file');
});

test('a title the watchdog cut short ends in an ellipsis', () => {
  const inner = 'x'.repeat(120);
  const stacked = `Watchdog: task overdue since 2026-11-07: Watchdog: task overdue since 2026-11-06: ${'y'.repeat(79)}`;
  assert.equal(plainTitle(`Watchdog: task overdue since 2026-11-06: ${inner}`).text, `${inner}…`);
  assert.ok(plainTitle(`Watchdog: task overdue since 2026-11-07: ${stacked.slice(41, 41 + 120)}`).text.endsWith('…'));
  assert.equal(plainTitle('Watchdog: task overdue since 2026-11-06: short').text, 'short');
});

test('internal names become the chart titles', () => {
  assert.equal(who('head_platform', titles), 'Head of Data and Platform');
  assert.equal(who('ceo', titles), 'you');
  assert.equal(who('head_unknown', titles), 'head of unknown');
});

test('a card says why it was raised and what it does without jargon', () => {
  const task = { ...base, title: 'Profile tests' };
  const why = whyRaised(task, titles, 'Watchdog: task overdue since 2026-11-06: Profile tests');
  assert.match(why, /^Head of Data and Platform broke “Find out why a task is late/);
  const does = whatItDoes(task, 'Fix the code problems the doctor queued', titles);
  assert.equal(does, 'Engineering agent will: fix the code problems the doctor queued.');
  for (const text of [why, does]) assert.doesNotMatch(text, /fix_code|head_platform|split by/);
});

test('a task that no agent may start says it needs you', () => {
  assert.equal(needsYou({ ...base, title: 'x' }, { auto: false, stuckSteps: false }).yes, true);
  assert.equal(needsYou({ ...base, title: 'x' }, { auto: true, stuckSteps: false }).yes, false);
  const head = {
    ...base,
    owner: 'head_platform',
    kind: '',
    status: 'done',
    title: 'x',
  };
  assert.match(needsYou(head, { auto: undefined, stuckSteps: false }).text, /accept it or send it back/);
});

test('every button explains itself', () => {
  for (const a of ['run', 'close', 'send_back', 'retry', 'cancel', 'assist'] as const)
    assert.ok(buttonHelp(a, { ...base, title: 'x' }, titles).length > 20);
  assert.match(buttonHelp('run', { ...base, title: 'x' }, titles), /only if you merge it/);
});
