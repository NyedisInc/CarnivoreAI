/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { terminalLayout } from './layout.svelte';
import {
  activeTabFor, adoptGroups, groupsFor, openTab, placeTab, removeTab, resetTabCache, setGroups, splitTabOut, tabsFor,
} from './tab-groups.svelte';
import { takenSlots } from './components-actions';
import { PRIMARY_SLOT } from './model';
import { pageSlotFor, pageTabId } from './page-tabs';
import { fromServerShape, toServerShape } from '../layouts/shape';
import type { SlotId } from './types';

const PAGE = pageTabId('0123456789abcdef');
const FILE = pageTabId('fedcba9876543210');
const B = 'terminal:ses_b';

afterEach(() => {
  terminalLayout.restore(terminalLayout.snapshot());
  resetTabCache();
  localStorage.clear();
});

function resetGrid(): void {
  for (const slot of takenSlots(terminalLayout)) if (slot !== PRIMARY_SLOT) terminalLayout.remove(slot as SlotId);
}

test('a page opens as a tab beside a session tab and is shown', () => {
  resetGrid();
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] } });
  expect(openTab(terminalLayout, PRIMARY_SLOT, PAGE)).toBe(PRIMARY_SLOT);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, B, PAGE]);
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(PAGE);
  openTab(terminalLayout, PRIMARY_SLOT, PAGE);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, B, PAGE]);
});

test('a page tab reorders in its strip', () => {
  resetGrid();
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, PAGE, FILE] } });
  expect(placeTab(terminalLayout, PRIMARY_SLOT, FILE, 1)).toBe('moved');
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, FILE, PAGE]);
});

test('a page splits out into a component of its own, beside the page pane, and stays a group of one', () => {
  resetGrid();
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, PAGE] } });
  const result = splitTabOut(terminalLayout, PAGE, { kind: 'stack', of: PRIMARY_SLOT as SlotId, edge: 'below' });
  expect(result).toBe('split');
  const slot = pageSlotFor(PAGE, [])!;
  expect(takenSlots(terminalLayout)).toContain(slot);
  expect(tabsFor(terminalLayout, slot)).toEqual([PAGE]);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT]);
  expect(placeTab(terminalLayout, PRIMARY_SLOT, PAGE, 1)).toBe('moved');
  expect(takenSlots(terminalLayout)).not.toContain(slot);
});

test('a split-out page persists: the stored groups survive a reload and the server round trip', () => {
  resetGrid();
  const was = terminalLayout.session;
  terminalLayout.bindKey('cloude_pages:1758000000', terminalLayout.snapshot());
  try {
    persistRoundTrip();
  } finally {
    terminalLayout.bindKey(was, terminalLayout.snapshot());
  }
});

function persistRoundTrip(): void {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, PAGE, FILE] } });
  splitTabOut(terminalLayout, PAGE, { kind: 'stack', of: PRIMARY_SLOT as SlotId, edge: 'below' });
  const key = terminalLayout.session;
  const sent = JSON.parse(JSON.stringify(groupsFor(key)));
  const slot = pageSlotFor(PAGE, [])!;
  expect(sent[slot]).toEqual({ tabs: [PAGE] });
  expect(sent[PRIMARY_SLOT].tabs).toEqual([PRIMARY_SLOT, FILE]);
  resetTabCache();
  expect(tabsFor(terminalLayout, slot)).toEqual([PAGE]);
  adoptGroups(key, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] }, [slot]: { tabs: [PAGE, FILE] } });
  expect(tabsFor(terminalLayout, slot)).toEqual([PAGE, FILE]);
}

test('closing a page tab leaves the grid; the emptied page component goes with it', () => {
  resetGrid();
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, PAGE] } });
  splitTabOut(terminalLayout, PAGE, { kind: 'stack', of: PRIMARY_SLOT as SlotId, edge: 'below' });
  const slot = pageSlotFor(PAGE, [])!;
  expect(removeTab(terminalLayout, PAGE)).toBe(slot);
  expect(takenSlots(terminalLayout)).not.toContain(slot);
});

test('a saved Layout takes a page tab like a session tab', () => {
  const grid = terminalLayout.snapshot();
  const was = terminalLayout.session;
  terminalLayout.bindKey('layout:5f0c0000-0000-0000-0000-000000000000', grid);
  try {
    expect(placeTab(terminalLayout, PRIMARY_SLOT, PAGE, 0)).toBe('added');
    expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toContain(PAGE);
  } finally {
    terminalLayout.bindKey(was, grid);
  }
});

test('turning a grid into a Layout carries its page tabs and page components, and reading it back restores them', () => {
  resetGrid();
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B, FILE] } });
  openTab(terminalLayout, PRIMARY_SLOT, PAGE);
  splitTabOut(terminalLayout, PAGE, { kind: 'stack', of: PRIMARY_SLOT as SlotId, edge: 'below' });
  const groups = groupsFor(terminalLayout.session);
  const shape = toServerShape(terminalLayout.snapshot(), groups, 7);
  expect(shape.groups[PRIMARY_SLOT]?.tabs).toEqual(['terminal:row:7', B, FILE]);
  const pageSlot = pageSlotFor(PAGE, [])!;
  expect(shape.groups[pageSlot]?.tabs).toEqual([PAGE]);
  const back = fromServerShape(shape, 7)!;
  expect(back.groups[pageSlot]?.tabs).toEqual([PAGE]);
  expect(back.groups[PRIMARY_SLOT]?.tabs).toEqual([PRIMARY_SLOT, B, FILE]);
  expect(back.layout!.rows.flatMap((row) => row.slots.map((s) => s.id as string))).toContain(pageSlot);
});
