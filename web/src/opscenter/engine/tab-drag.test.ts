/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { terminalLayout } from './layout.svelte';
import { activeTabFor, placeTab, resetTabCache, selectTab, setGroups, tabsFor } from './tab-groups.svelte';
import { takenSlots } from './components-actions';
import { PRIMARY_SLOT } from './model';

const B = 'terminal:ses_b';
const C = 'terminal:ses_c';
const D = 'terminal:ses_d';

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
