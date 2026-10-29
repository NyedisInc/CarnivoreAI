/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { terminalLayout } from './layout.svelte';
import { activeTabFor, openTab, resetTabCache, setGroups, tabsFor } from './tab-groups.svelte';
import { takenSlots } from './components-actions';
import { PRIMARY_SLOT } from './model';

const B = 'terminal:ses_b';
const C = 'terminal:ses_c';

afterEach(() => {
  resetTabCache();
  localStorage.clear();
});

test('the page component is on the grid, so the case below is the real one', () => {
  expect(takenSlots(terminalLayout)).toContain(PRIMARY_SLOT);
});

test('opening a session in a component on the grid keeps the tabs it already has', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] } });
  expect(openTab(terminalLayout, PRIMARY_SLOT, C)).toBe(PRIMARY_SLOT);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, B, C]);
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(C);
});

test('opening a session already in the group focuses it, never a second copy', () => {
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] } });
  openTab(terminalLayout, PRIMARY_SLOT, B);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, B]);
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(B);
});
