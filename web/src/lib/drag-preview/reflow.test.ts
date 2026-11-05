import { expect, test } from 'vitest';
import { previewOrder } from './reflow';
import { RAIL_SPLIT } from '../sidebar-widgets/rail-zones';

const list = ['a', 'b', 'c', 'd'];

test('hovering above a row previews the dragged row just before it; the input is untouched', () => {
  expect(previewOrder(list, 'd', { before: 'b' })).toEqual(['a', 'd', 'b', 'c']);
  expect(list).toEqual(['a', 'b', 'c', 'd']);
});

test('hovering past the last row previews it last', () => {
  expect(previewOrder(list, 'a', { before: null })).toEqual(['b', 'c', 'd', 'a']);
});

test('no spot (Escape or a cancelled pointer) restores the original order as a copy', () => {
  const out = previewOrder(list, 'c', null);
  expect(out).toEqual(list);
  expect(out).not.toBe(list);
});

test('hovering at the dragged row\'s own place, or over itself, changes nothing', () => {
  expect(previewOrder(list, 'b', { before: 'c' })).toEqual(list);
  expect(previewOrder(list, 'b', { before: 'b' })).toEqual(list);
});

test('across the rail split: the end of the top list lands before the zone marker, the end of the bottom list last', () => {
  const rail = ['agents', 'swarm', RAIL_SPLIT, 'docs', 'settings'];
  expect(previewOrder(rail, 'settings', { before: null, end: RAIL_SPLIT })).toEqual(['agents', 'swarm', 'settings', RAIL_SPLIT, 'docs']);
  expect(previewOrder(rail, 'agents', { before: null, end: null })).toEqual(['swarm', RAIL_SPLIT, 'docs', 'settings', 'agents']);
});

test('an id the list does not hold, or a spot naming a missing row, previews the original order', () => {
  expect(previewOrder(list, 'zzz', { before: 'a' })).toEqual(list);
  expect(previewOrder(list, 'a', { before: 'nope' })).toEqual(list);
});
