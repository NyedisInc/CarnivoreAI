/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { freeSlot } from './tab-split';
import { terminalLayout, type DropTarget } from './layout.svelte';
import { activeTabFor, mergeComponent, resetTabCache, selectTab, setGroups, splitTabOut, tabsFor } from './tab-groups.svelte';
import { takenSlots } from './components-actions';
import { normalize } from './tabs';
import { MAX_VIEWERS, PRIMARY_SLOT, rowOfCell } from './model';
import type { SlotId } from './types';

const B = 'terminal:ses_b';
const C = 'terminal:ses_c';
const X = 'terminal:ses_x';

test('freeSlot: the tab itself when free, else the next free tab id', () => {
  expect(freeSlot([PRIMARY_SLOT], [B, C])).toBe(B);
  expect(freeSlot([PRIMARY_SLOT, B], [B, C])).toBe(C);
  expect(freeSlot([B, C], [B, C])).toBeNull();
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

test('splitOut: a tab split to an edge becomes its own component there, shown, and leaves its old strip', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B, C] }, [X]: { tabs: [X] } });
  selectTab(terminalLayout, PRIMARY_SLOT, B);
  const xRow = rowOfCell(terminalLayout.state.layout, X)!;
  const target: DropTarget = { kind: 'row', row: xRow.id, index: xRow.slots.findIndex((slot) => slot.id === X) + 1 };
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
