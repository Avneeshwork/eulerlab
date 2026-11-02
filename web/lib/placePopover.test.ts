import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EDGE, GAP, placePopover } from './placePopover.ts';

const view = { width: 1200, height: 800 };
const button = (left: number, top: number) => ({ left, top, right: left + 18, bottom: top + 18 });

test('opens below the button when there is room', () => {
  const p = placePopover(button(100, 100), { width: 300, height: 120 }, view);
  assert.equal(p.side, 'below');
  assert.equal(p.top, 118 + GAP);
  assert.equal(p.left, 100 - EDGE);
});

test('flips above near the bottom of the window', () => {
  const p = placePopover(button(100, 760), { width: 300, height: 120 }, view);
  assert.equal(p.side, 'above');
  assert.equal(p.top, 760 - GAP - 120);
});

test('never runs off the right edge', () => {
  const p = placePopover(button(1150, 100), { width: 340, height: 120 }, view);
  assert.equal(p.left + 340, view.width - EDGE);
});

test('never runs off the left edge, even when aligned right', () => {
  const p = placePopover(button(4, 100), { width: 340, height: 120 }, view, 'right');
  assert.equal(p.left, EDGE);
});

test('aligned right, the popup ends at the button', () => {
  const p = placePopover(button(600, 100), { width: 300, height: 120 }, view, 'right');
  assert.equal(p.left + 300, 618 + EDGE);
});

test('a popup wider than a phone is squeezed to fit', () => {
  const phone = { width: 360, height: 700 };
  const p = placePopover(button(300, 100), { width: 500, height: 120 }, phone);
  assert.equal(p.left, EDGE);
});

test('a popup taller than both sides is capped to the larger side', () => {
  const p = placePopover(button(100, 300), { width: 300, height: 2000 }, view);
  assert.equal(p.side, 'below');
  assert.equal(p.maxHeight, 800 - 318 - GAP - EDGE);
  assert.ok(p.top + p.maxHeight <= view.height - EDGE);
});
