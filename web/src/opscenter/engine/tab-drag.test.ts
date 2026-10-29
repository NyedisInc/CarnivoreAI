/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { pickDrop, pickStripDrop, type StripTarget } from './tab-drag';
import { terminalLayout } from './layout.svelte';
import { activeTabFor, placeTab, resetTabCache, selectTab, setGroups, tabsFor } from './tab-groups.svelte';
import { takenSlots } from './components-actions';
import { PRIMARY_SLOT } from './model';

const B = 'terminal:ses_b';
const C = 'terminal:ses_c';
const D = 'terminal:ses_d';

const STRIPS: StripTarget[] = [
  {
    slot: PRIMARY_SLOT,
    left: 0,
    right: 500,
    top: 0,
    bottom: 40,
    tabs: [
      { id: PRIMARY_SLOT, centre: 50 },
      { id: B, centre: 150 },
      { id: C, centre: 250 },
    ],
  },
  { slot: 'terminal:ses_x', left: 510, right: 1000, top: 0, bottom: 40, tabs: [{ id: D, centre: 560 }] },
];

test('the index counts the tab centres left of the pointer', () => {
  expect(pickStripDrop(STRIPS, 10, 20, 'terminal:new')).toEqual({ kind: 'strip', slot: PRIMARY_SLOT, index: 0 });
  expect(pickStripDrop(STRIPS, 200, 20, 'terminal:new')).toEqual({ kind: 'strip', slot: PRIMARY_SLOT, index: 2 });
  expect(pickStripDrop(STRIPS, 490, 20, 'terminal:new')).toEqual({ kind: 'strip', slot: PRIMARY_SLOT, index: 3 });
});

test('the dragged tab is not counted, so dragging it right past one neighbour is index 1', () => {
  expect(pickStripDrop(STRIPS, 160, 20, PRIMARY_SLOT)).toEqual({ kind: 'strip', slot: PRIMARY_SLOT, index: 1 });
});

test('another strip answers with its own slot', () => {
  expect(pickStripDrop(STRIPS, 600, 20, B)).toEqual({ kind: 'strip', slot: 'terminal:ses_x', index: 1 });
  expect(pickStripDrop(STRIPS, 520, 20, B)).toEqual({ kind: 'strip', slot: 'terminal:ses_x', index: 0 });
});

test('off every strip, and in the gap between two, there is no drop', () => {
  const surface = { strips: STRIPS, bodies: [], out: () => null };
  expect(pickDrop(surface, 200, 41, B)).toBeNull();
  expect(pickDrop(surface, 505, 20, B)).toBeNull();
  expect(pickDrop({ ...surface, strips: [] }, 10, 10, B)).toBeNull();
});

beforeEach(() => {
  terminalLayout.add('terminal', 'ses_x');
  expect(takenSlots(terminalLayout)).toContain('terminal:ses_x');
});

afterEach(() => {
  terminalLayout.resetAll();
  resetTabCache();
  localStorage.clear();
});

const X = 'terminal:ses_x';

test('a reorder inside one strip moves the tab and shows it', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B, C] } });
  expect(placeTab(terminalLayout, PRIMARY_SLOT, C, 0)).toBe('moved');
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([C, PRIMARY_SLOT, B]);
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(C);
});

test('a move to another strip leaves one copy, and the source shows a neighbour', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B, C] }, [X]: { tabs: [X] } });
  selectTab(terminalLayout, PRIMARY_SLOT, B);
  expect(placeTab(terminalLayout, X, B, 0)).toBe('moved');
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, C]);
  expect(tabsFor(terminalLayout, X)).toEqual([B, X]);
  expect(activeTabFor(terminalLayout, X)).toBe(B);
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(C);
});

test('moving the last tab out takes its component off the grid', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] }, [X]: { tabs: [X] } });
  expect(placeTab(terminalLayout, PRIMARY_SLOT, X, 1)).toBe('moved');
  expect(takenSlots(terminalLayout)).not.toContain(X);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, X]);
});

test("the page's own component is never emptied: that move is refused", () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] }, [X]: { tabs: [X] } });
  expect(placeTab(terminalLayout, X, PRIMARY_SLOT, 0)).toBeNull();
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT]);
  expect(tabsFor(terminalLayout, X)).toEqual([X]);
});

test('the page pane tab may move while its component keeps another tab', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] }, [X]: { tabs: [X] } });
  expect(placeTab(terminalLayout, X, PRIMARY_SLOT, 1)).toBe('moved');
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([B]);
  expect(tabsFor(terminalLayout, X)).toEqual([X, PRIMARY_SLOT]);
});

test('a session from the drawer is added at the index; one already on the page is moved, never copied', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] }, [X]: { tabs: [X] } });
  expect(placeTab(terminalLayout, PRIMARY_SLOT, D, 1)).toBe('added');
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, D, B]);
  expect(placeTab(terminalLayout, X, D, 1)).toBe('moved');
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, B]);
  expect(tabsFor(terminalLayout, X)).toEqual([X, D]);
});

test('a slot that is not on the grid takes no drop', () => {
  expect(placeTab(terminalLayout, 'terminal:gone', B, 0)).toBeNull();
});
