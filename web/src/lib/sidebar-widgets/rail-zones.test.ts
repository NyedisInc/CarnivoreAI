import { expect, test } from 'vitest';
import { RAIL_SPLIT, resolveRailZones, slotGroup, splitSequence, zoneSequence } from './rail-zones';

const row = (id: string): { id: string } => ({ id });
const top = ['agents', 'swarm', 'sessions', 'hosts'].map(row);
const bottom = ['docs', 'changelog', 'settings'].map(row);

test('no marker: the default zones come back untouched, even with an older stored order', () => {
  expect(resolveRailZones(top, bottom, [])).toEqual({ top: ['agents', 'swarm', 'sessions', 'hosts'], bottom: ['docs', 'changelog', 'settings'] });
  expect(resolveRailZones(top, bottom, ['settings', 'docs'])).toEqual({ top: ['agents', 'swarm', 'sessions', 'hosts'], bottom: ['docs', 'changelog', 'settings'] });
});

test('the marker puts settings up and an icon down, in the stored order', () => {
  const stored = ['agents', 'settings', 'swarm', 'sessions', RAIL_SPLIT, 'hosts', 'docs', 'changelog'];
  expect(resolveRailZones(top, bottom, stored)).toEqual({ top: ['agents', 'settings', 'swarm', 'sessions'], bottom: ['hosts', 'docs', 'changelog'] });
});

test('an icon the stored order does not name keeps its default zone, after the named ones; unknown ids vanish', () => {
  const stored = ['agents', RAIL_SPLIT, 'docs', 'gone'];
  expect(resolveRailZones(top, bottom, stored)).toEqual({ top: ['agents', 'swarm', 'sessions', 'hosts'], bottom: ['docs', 'changelog', 'settings'] });
});

test('sequence and split are inverses', () => {
  const zones = { top: ['a', 'b'], bottom: ['c'] };
  expect(zoneSequence(zones)).toEqual(['a', 'b', RAIL_SPLIT, 'c']);
  expect(splitSequence(zoneSequence(zones))).toEqual(zones);
  expect(splitSequence(['a', 'b'])).toEqual({ top: ['a', 'b'], bottom: [] });
});

test('slotGroup: a group reorders inside the slots it held and never crosses the marker', () => {
  expect(slotGroup(['a', 'b', RAIL_SPLIT, 's'], ['b', 'a'])).toEqual(['b', 'a', RAIL_SPLIT, 's']);
  expect(slotGroup(['a', RAIL_SPLIT, 's', 'b'], ['b', 'a'])).toEqual(['b', RAIL_SPLIT, 's', 'a']);
  expect(slotGroup(['a', RAIL_SPLIT, 's'], ['a', 'n'])).toEqual(['a', 'n', RAIL_SPLIT, 's']);
});
