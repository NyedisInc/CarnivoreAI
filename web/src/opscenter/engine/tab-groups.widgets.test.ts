/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { terminalLayout } from './layout.svelte';
import { activeTabFor, openTab, replaceTab, resetTabCache, selectTab, setGroups, tabsFor } from './tab-groups.svelte';
import { takenSlots } from './components-actions';
import { PRIMARY_SLOT } from './model';
import { displayedTabs, toServerShape } from '../layouts/shape';
import { isNonSessionTab, isWidgetTab, widgetIdOfTab, widgetTabId } from './widget-tabs';
import type { SlotId } from './types';

const TASKS = widgetTabId('core.tasks');
const TASKS_ALL = widgetTabId('core.tasks-all');
const B = 'terminal:ses_b';

afterEach(() => {
  terminalLayout.restore(terminalLayout.snapshot());
  resetTabCache();
  localStorage.clear();
});

function resetGrid(): void {
  for (const slot of takenSlots(terminalLayout)) if (slot !== PRIMARY_SLOT) terminalLayout.remove(slot as SlotId);
}

test('a widget opens as a tab beside a session tab and is shown', () => {
  resetGrid();
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] } });
  expect(openTab(terminalLayout, PRIMARY_SLOT, TASKS)).toBe(PRIMARY_SLOT);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, B, TASKS]);
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(TASKS);
});

test('the scope switch swaps the key in place and the active tab moves with it', () => {
  resetGrid();
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, TASKS, B] } });
  selectTab(terminalLayout, PRIMARY_SLOT, TASKS);
  expect(replaceTab(terminalLayout, TASKS, TASKS_ALL)).toBe(true);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, TASKS_ALL, B]);
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(TASKS_ALL);
});

test('a swap leaves another tab showing when the swapped one was in the background', () => {
  resetGrid();
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, TASKS] } });
  selectTab(terminalLayout, PRIMARY_SLOT, PRIMARY_SLOT);
  expect(replaceTab(terminalLayout, TASKS, TASKS_ALL)).toBe(true);
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(PRIMARY_SLOT);
});

test('a swap onto a key already a tab, or from a key on no group, is refused and changes nothing', () => {
  resetGrid();
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, TASKS, TASKS_ALL] } });
  expect(replaceTab(terminalLayout, TASKS, TASKS_ALL)).toBe(false);
  expect(replaceTab(terminalLayout, widgetTabId('core.nothing'), TASKS_ALL)).toBe(false);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, TASKS, TASKS_ALL]);
});

test('the server shape carries a widget tab and counts it as no member', () => {
  const grid = terminalLayout.snapshot();
  const groups = { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B, TASKS] } };
  expect(toServerShape(grid, groups, 1).groups[PRIMARY_SLOT]?.tabs).toEqual(['terminal:row:1', B, TASKS]);
  expect(displayedTabs(grid, groups)).toEqual([PRIMARY_SLOT, B]);
});

test('the parser reads exactly the keys the server accepts', () => {
  expect(widgetIdOfTab('widget:core.tasks-all')).toBe('core.tasks-all');
  for (const bad of ['widget:', 'widget:Core.Tasks', 'widget:.core', 'widget:core tasks', `widget:a${'b'.repeat(64)}`, 'terminal:row:1', 'page:0123456789abcdef']) {
    expect(isWidgetTab(bad), bad).toBe(false);
  }
  expect(isWidgetTab(`widget:a${'b'.repeat(63)}`)).toBe(true);
  expect(isNonSessionTab(TASKS)).toBe(true);
  expect(isNonSessionTab('page:0123456789abcdef')).toBe(true);
  expect(isNonSessionTab('terminal:row:7')).toBe(false);
});
