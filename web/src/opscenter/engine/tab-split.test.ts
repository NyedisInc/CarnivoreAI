/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { dropZone, freeSlot, zoneTarget } from './tab-split';
import { pickBodyDrop, pickDrop, type BodyTarget, type DragSurface } from './tab-drag';
import { terminalLayout } from './layout.svelte';
import { activeTabFor, mergeComponent, resetTabCache, selectTab, setGroups, splitTabOut, tabsFor } from './tab-groups.svelte';
import { takenSlots } from './components-actions';
import { normalize } from './tabs';
import { MAX_VIEWERS, PRIMARY_SLOT, rowOfCell } from './model';
import type { SlotId } from './types';

const B = 'terminal:ses_b';
const C = 'terminal:ses_c';
const X = 'terminal:ses_x';
const BOX = { left: 0, right: 400, top: 0, bottom: 200 };

test('dropZone: the outer quarter on each side is an edge, the rest is the middle', () => {
  expect(dropZone(BOX, 50, 100)).toBe('left');
  expect(dropZone(BOX, 350, 100)).toBe('right');
  expect(dropZone(BOX, 200, 20)).toBe('top');
  expect(dropZone(BOX, 200, 180)).toBe('bottom');
  expect(dropZone(BOX, 200, 100)).toBe('center');
  expect(dropZone(BOX, 101, 51)).toBe('center');
});

test('dropZone: a corner goes to the nearer edge, and outside the box is nothing', () => {
  expect(dropZone(BOX, 10, 30)).toBe('left');
  expect(dropZone(BOX, 60, 5)).toBe('top');
  expect(dropZone(BOX, 401, 100)).toBeNull();
  expect(dropZone({ left: 0, right: 0, top: 0, bottom: 0 }, 0, 0)).toBeNull();
});

test('freeSlot: the tab itself when free, else the next free tab id', () => {
  expect(freeSlot([PRIMARY_SLOT], [B, C])).toBe(B);
  expect(freeSlot([PRIMARY_SLOT, B], [B, C])).toBe(C);
  expect(freeSlot([B, C], [B, C])).toBeNull();
});

const body = (slot: string, tabs: string[]): BodyTarget => ({ slot, tabs, ...BOX });

test('pickBodyDrop: the middle of its own component and any edge of its only-tab component are no drop', () => {
  expect(pickBodyDrop(body(PRIMARY_SLOT, [PRIMARY_SLOT, B]), 200, 100, B)).toBeNull();
  expect(pickBodyDrop(body(PRIMARY_SLOT, [PRIMARY_SLOT, B]), 10, 100, B)).toEqual({ kind: 'zone', slot: PRIMARY_SLOT, zone: 'left' });
  expect(pickBodyDrop(body(X, [X]), 10, 100, X)).toBeNull();
  expect(pickBodyDrop(body(X, [X]), 200, 100, B)).toEqual({ kind: 'zone', slot: X, zone: 'center' });
});

test('pickDrop: strip first, then a body, then the layout drop', () => {
  const surface: DragSurface = {
    strips: [{ slot: X, left: 0, right: 400, top: 0, bottom: 30, tabs: [{ id: X, centre: 50 }] }],
    bodies: [body(X, [X])],
    out: () => ({ kind: 'new', after: null }),
  };
  expect(pickDrop(surface, 300, 10, B)).toEqual({ kind: 'strip', slot: X, index: 1 });
  expect(pickDrop(surface, 390, 100, B)).toEqual({ kind: 'zone', slot: X, zone: 'right' });
  expect(pickDrop(surface, 900, 100, B)).toEqual({ kind: 'out', target: { kind: 'new', after: null } });
});

beforeEach(() => {
  terminalLayout.add('terminal', 'ses_x');
  expect(takenSlots(terminalLayout)).toContain(X);
});

afterEach(() => {
  terminalLayout.resetAll();
  resetTabCache();
  localStorage.clear();
});

test('zoneTarget: left and right are a place in the row either side, top and bottom a stack', () => {
  const layout = terminalLayout.state.layout;
  const row = rowOfCell(layout, X)!;
  const at = row.slots.findIndex((slot) => slot.id === X);
  expect(zoneTarget(layout, X as SlotId, 'left')).toEqual({ kind: 'row', row: row.id, index: at });
  expect(zoneTarget(layout, X as SlotId, 'right')).toEqual({ kind: 'row', row: row.id, index: at + 1 });
  expect(zoneTarget(layout, X as SlotId, 'bottom')).toEqual({ kind: 'stack', of: X, edge: 'below' });
  expect(zoneTarget(layout, X as SlotId, 'center')).toBeNull();
});

test('splitOut: a tab split to an edge becomes its own component there, shown, and leaves its old strip', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B, C] }, [X]: { tabs: [X] } });
  selectTab(terminalLayout, PRIMARY_SLOT, B);
  const target = zoneTarget(terminalLayout.state.layout, X as SlotId, 'right')!;
  expect(splitTabOut(terminalLayout, B, target)).toBe('split');
  expect(takenSlots(terminalLayout)).toContain(B);
  const row = rowOfCell(terminalLayout.state.layout, X)!;
  const ids = row.slots.map((slot) => slot.id);
  expect(ids.indexOf(B as SlotId)).toBe(ids.indexOf(X as SlotId) + 1);
  expect(tabsFor(terminalLayout, B)).toEqual([B]);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, C]);
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(C);
});

test('splitOut: a stack edge stacks the new component in the target column', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] }, [X]: { tabs: [X] } });
  expect(splitTabOut(terminalLayout, B, { kind: 'stack', of: X as SlotId, edge: 'below' })).toBe('split');
  const home = rowOfCell(terminalLayout.state.layout, B)!;
  expect(home.id).not.toBe(rowOfCell(terminalLayout.state.layout, X)!.id);
});

test('splitOut: the tab its component is named after takes the next free id, and no session is in two tabs', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] }, [X]: { tabs: [X, C] } });
  expect(splitTabOut(terminalLayout, X, { kind: 'stack', of: PRIMARY_SLOT, edge: 'above' })).toBe('split');
  expect(tabsFor(terminalLayout, C)).toEqual([X]);
  expect(tabsFor(terminalLayout, X)).toEqual([C]);
  const every = takenSlots(terminalLayout).flatMap((slot) => tabsFor(terminalLayout, slot));
  expect(new Set(every).size).toBe(every.length);
});

test("splitOut: the only tab of a component moves that component, and a refused landing changes nothing", () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] }, [X]: { tabs: [X] } });
  expect(splitTabOut(terminalLayout, X, { kind: 'stack', of: PRIMARY_SLOT, edge: 'below' })).toBe('moved');
  expect(tabsFor(terminalLayout, X)).toEqual([X]);
  const before = JSON.stringify(terminalLayout.state.layout);
  expect(splitTabOut(terminalLayout, B, { kind: 'stack', of: 'terminal:gone' as SlotId, edge: 'below' })).toBeNull();
  expect(JSON.stringify(terminalLayout.state.layout)).toBe(before);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, B]);
});

test('caps: a split past the component cap is refused and puts everything back', () => {
  for (let at = 1; at < MAX_VIEWERS; at += 1) terminalLayout.add('terminal', `ses_cap${at}`);
  const tabs = [PRIMARY_SLOT, B];
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs } });
  const before = JSON.stringify(terminalLayout.state.layout);
  expect(splitTabOut(terminalLayout, B, { kind: 'stack', of: X as SlotId, edge: 'below' })).toBe('cap');
  expect(JSON.stringify(terminalLayout.state.layout)).toBe(before);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual(tabs);
  expect(takenSlots(terminalLayout)).not.toContain(B);
});

test('mergeGroup: a whole component dropped on another joins its strip and leaves the grid', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] }, [X]: { tabs: [X, B] } });
  selectTab(terminalLayout, X, B);
  expect(mergeComponent(terminalLayout, X, PRIMARY_SLOT)).toBe('merged');
  expect(takenSlots(terminalLayout)).not.toContain(X);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, X, B]);
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(B);
});

test("mergeGroup: the page's own component is never merged away", () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] }, [X]: { tabs: [X] } });
  expect(mergeComponent(terminalLayout, PRIMARY_SLOT, X)).toBe('primary');
  expect(mergeComponent(terminalLayout, X, X)).toBeNull();
  expect(takenSlots(terminalLayout)).toContain(X);
  expect(tabsFor(terminalLayout, X)).toEqual([X]);
});

test('normalize: an emptied group is named for removal and a duplicated tab keeps its first', () => {
  const { groups, remove } = normalize({ [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] }, [X]: { tabs: [B] } }, [PRIMARY_SLOT, X]);
  expect(groups[X]!.tabs).toEqual([]);
  expect(remove).toEqual([X]);
});
