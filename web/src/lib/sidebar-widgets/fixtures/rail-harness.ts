import fs from 'node:fs';
import path from 'node:path';
import { vi } from 'vitest';
import { flushSync, tick } from 'svelte';
import * as Search from '../../drawer/search';
import { setDrawerEnv } from '../../drawer/env';
import { mountDrawerHeader } from '../../drawer/header-mount';
import { setViewClassSource } from '../../drawer/view-class';
import { init as initStats } from '../../drawer/stats-visibility.svelte';
import { approvals } from '../../approvals/approvals.svelte';
import { registerTab, tabRegistry } from '../../dynamic-tabs/registry';
import { agentsTab, menuTab, questionsTab } from '../../drawer-tabs/core-tabs';
import { DRAWER_SEARCH_ID, DRAWER_STATS_ID } from '../../drawer-tabs/drawer-tabs';
import { unmountPanel } from '../../mount';
import { registerCoreSidebarWidgets } from '../core-widgets';
import { registerSwarmFlyout } from '../../../cplugs/huddle/swarm-flyout';
import { widgetBars } from '../../widget-bars/bar-settings.svelte';
import { mountRail, unmountRail } from '../rail-layout.svelte';
import { FLYOUT_CONTAINER_ID, RAIL_CONTAINER_ID } from '../rail-dom';
import { pressRail } from '../flyout.svelte';
import { MENU_FLYOUT } from '../widget-ids';
import FlyoutBodyFixture from './FlyoutBodyFixture.svelte';
import MainViewFixture from './MainViewFixture.svelte';
import FlyoutActionsFixture from './FlyoutActionsFixture.svelte';
import { tabFlags } from './tab-flags.svelte';

export const REPO = path.resolve(process.cwd(), '..');
export const HUDDLE = 'huddle';

export function drawerMarkup(): string {
  const source = fs.readFileSync(path.join(REPO, 'client', 'index.html'), 'utf8');
  const start = source.indexOf('<aside id="session-sidebar-panel"');
  const end = source.indexOf('</aside>', start);
  return source.slice(start, end + '</aside>'.length);
}

export async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await tick();
    flushSync();
    await new Promise((r) => setTimeout(r, 5));
  }
}

export function bridge(store: Record<string, unknown>) {
  return {
    PreferenceBridge: {
      read: (field: string, fallback: () => unknown) => (field in store ? store[field] : fallback()),
      write: async (field: string, value: unknown, local: () => void) => { store[field] = value; local(); },
    },
  };
}

export const rail = (): HTMLElement => document.getElementById(RAIL_CONTAINER_ID)!;
export const railBtn = (id: string): HTMLButtonElement => rail().querySelector<HTMLButtonElement>(`[data-rail-widget="${id}"]`)!;
export const flyout = (): HTMLElement => document.querySelector<HTMLElement>(`#${FLYOUT_CONTAINER_ID} .sbr-flyout`)!;

export async function press(id: string): Promise<void> {
  if (id === MENU_FLYOUT) {
    pressRail(MENU_FLYOUT);
    await settle();
    return;
  }
  const key = rail().querySelector<HTMLButtonElement>(`[data-rail-widget="${id}"]`);
  if (key) key.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 }));
  else pressRail(id);
  await settle();
}

export const prefs: { store: Record<string, unknown> } = { store: {} };

export async function setupRail(viewClass: 'desktop' | 'mobile' = 'desktop'): Promise<Record<string, unknown>> {
  document.body.innerHTML = `${drawerMarkup()}<main id="main-pane"><button type="button" id="main-target">open</button></main><div id="plugin-main-view"></div>`;
  mountDrawerHeader();
  localStorage.clear();
  Search.setQuery('');
  (globalThis as Record<string, unknown>).SessionSidebarSearch = { getQuery: Search.getQuery, setQuery: Search.setQuery, matchesRow: Search.matchesRow, matchesLabel: Search.matchesLabel, noMatchesHtml: Search.noMatchesHtml, normalize: Search.normalize };
  class FakeObserver { observe(): void {} disconnect(): void {} unobserve(): void {} }
  vi.stubGlobal('VisibilityObserver', FakeObserver);
  vi.stubGlobal('ResizeObserver', FakeObserver);
  setViewClassSource(() => viewClass);
  prefs.store = {};
  setDrawerEnv(bridge(prefs.store));
  approvals.items = [];
  tabFlags.flow = false;
  tabFlags.closable = false;
  closedTabs.length = 0;
  if (!tabRegistry.get(HUDDLE)) {
    registerTab({ id: HUDDLE, labelKey: 'cplug.huddle.tab', icon: 'swarm', order: 35, persist: false, widgetArea: 'glance', body: { component: FlyoutBodyFixture, titleActions: FlyoutActionsFixture } });
  }
  for (const def of [menuTab, agentsTab, questionsTab]) if (!tabRegistry.get(def.id)) registerTab(def);
  registerTestTabs();
  registerCoreSidebarWidgets();
  registerSwarmFlyout();
  (globalThis as Record<string, unknown>).PreferenceBridge = {
    read: (field: string, fallback: () => unknown) => (field === 'widget_bars' ? { v: 1, rail: { mode: 'pinned' } } : fallback()),
    write: async (_field: string, _value: unknown, local: () => void) => { local(); return { status: 'committed' }; },
    follow: () => () => {},
  };
  widgetBars.reload();
  initStats();
  await settle();
  return prefs.store;
}

export async function teardownRail(): Promise<void> {
  unmountRail();
  for (const id of [DRAWER_SEARCH_ID, DRAWER_STATS_ID, 'session-sidebar-topbar-controls']) unmountPanel(id);
  await settle();
  document.body.replaceChildren();
  document.body.className = '';
  delete (globalThis as Record<string, unknown>).PreferenceBridge;
  widgetBars.reload();
  setDrawerEnv(null);
  setViewClassSource(null);
  vi.unstubAllGlobals();
}

export async function askOne(): Promise<void> {
  approvals.items = [{ id: 'q1', session_id: 's1', title: 'deploy?', created_at: new Date().toISOString() } as never];
  await settle();
}

export async function unpinRail(): Promise<void> {
  (globalThis as Record<string, unknown>).PreferenceBridge = {
    read: (field: string, fallback: () => unknown) => (field === 'widget_bars' ? { v: 1, rail: { mode: 'autohide' } } : fallback()),
    write: async (_field: string, _value: unknown, local: () => void) => { local(); return { status: 'committed' }; },
    follow: () => () => {},
  };
  widgetBars.reload();
  await settle();
}

export async function railOn(): Promise<void> {
  mountRail();
  await settle();
}


export const FLOW_TAB = 'flow';
export const CLOSABLE_TAB = 'closable-test';

export function registerTestTabs(): void {
  if (!tabRegistry.get(FLOW_TAB)) {
    registerTab({ id: FLOW_TAB, labelKey: 'drawer.tabs.edit_layout', icon: 'activity', order: 38, persist: false, present: () => tabFlags.flow, focusOnAppear: false, widgetArea: 'closed', mainView: MainViewFixture, body: { component: FlyoutBodyFixture, titleKey: 'drawer.tabs.edit_layout' } });
  }
  if (!tabRegistry.get(CLOSABLE_TAB)) {
    registerTab({
      id: CLOSABLE_TAB, labelKey: 'drawer.tabs.edit_layout', icon: 'layout', order: 41, persist: false, present: () => tabFlags.closable,
      focusOnAppear: false, widgetArea: 'full', close: () => { tabFlags.closable = false; closedTabs.push(CLOSABLE_TAB); }, body: { component: FlyoutBodyFixture },
    });
  }
}

export const closedTabs: string[] = [];
