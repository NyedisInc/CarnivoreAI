/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { flushSync } from 'svelte';
import { unmountPanel } from '../mount';
import { setLocale } from '../i18n/index.svelte';
import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import { DRAWER_TAB_STORAGE_KEY, DRAWER_TABBODY_ID } from '../drawer-tabs/drawer-tabs';
import { FLOW_TAB, prefs, settle, setupRail, teardownRail } from '../sidebar-widgets/fixtures/rail-harness';
import { tabFlags } from '../sidebar-widgets/fixtures/tab-flags.svelte';
import { mountDrawerLayout } from './mount-drawer-layout';
import { ROOT_ZONE_KEY, SESSION_LIST_TAB } from './root-zone.svelte';

setLocale('en');

const bodyRegion = (): HTMLElement => document.getElementById(DRAWER_TABBODY_ID)!;
const pane = (key: string): HTMLElement | null => bodyRegion().querySelector<HTMLElement>(`[data-zone-pane="${key}"]`);

beforeEach(async () => {
  await setupRail();
  sidebarTabs.reload();
  sidebarTabs.leave();
});

afterEach(async () => {
  for (const id of [DRAWER_TABBODY_ID, 'session-sidebar-area-bar', 'session-sidebar-ledger', 'session-sidebar-rail']) unmountPanel(id);
  tabFlags.flow = false;
  sidebarTabs.leave();
  await teardownRail();
});

test('the layout declares the root zone and the left rail zone', () => {
  const layout = mountDrawerLayout();
  expect(layout.root.spec.key).toBe(ROOT_ZONE_KEY);
  expect(layout.leftRail.spec.key).toBe('rail:left');
  expect(layout.root.tabs.map((tab) => tab.key)).toEqual([SESSION_LIST_TAB]);
});

test('a dynamic tab joins the root zone, drawn in the tab body region; the session list is drawn by its own mount', async () => {
  const { root } = mountDrawerLayout();
  tabFlags.flow = true;
  await settle();
  expect(root.tabs.map((tab) => tab.key)).toEqual([SESSION_LIST_TAB, FLOW_TAB]);
  expect(pane(FLOW_TAB), 'the dynamic tab has a pane').not.toBeNull();
  expect(pane(SESSION_LIST_TAB), 'the session list has none here (it is mounted into #session-sidebar-list)').toBeNull();
});

test('switching tabs changes only the per-device active tab, the toolbar and the visibility follow it, and nothing synced is written', async () => {
  const { root } = mountDrawerLayout();
  tabFlags.flow = true;
  await settle();
  expect(root.active?.key).toBe(SESSION_LIST_TAB);
  expect(root.toolbar?.hostId).toBe(`${ROOT_ZONE_KEY}#${SESSION_LIST_TAB}`);
  expect(root.visibility(SESSION_LIST_TAB)).toBe('shown');
  expect(root.visibility(FLOW_TAB)).toBe('hidden');
  expect(pane(FLOW_TAB)!.classList.contains('zone-pane--gone'), 'an inactive pane takes no room').toBe(true);

  sidebarTabs.select(FLOW_TAB);
  await settle();
  flushSync();
  expect(root.active?.key).toBe(FLOW_TAB);
  expect(root.toolbar?.hostId).toBe(`${ROOT_ZONE_KEY}#${FLOW_TAB}`);
  expect(root.visibility(SESSION_LIST_TAB), 'the session list reads hidden while a dynamic tab shows').toBe('hidden');
  expect(root.visibility(FLOW_TAB)).toBe('shown');
  expect(pane(FLOW_TAB)!.classList.contains('zone-pane--gone')).toBe(false);

  sidebarTabs.leave();
  await settle();
  expect(root.active?.key).toBe(SESSION_LIST_TAB);
  expect(root.visibility(SESSION_LIST_TAB), 'and shown again after').toBe('shown');

  expect(localStorage.getItem(DRAWER_TAB_STORAGE_KEY)).toBeNull();
  expect(Object.keys(prefs.store)).not.toContain('drawer_arrangement');
});
