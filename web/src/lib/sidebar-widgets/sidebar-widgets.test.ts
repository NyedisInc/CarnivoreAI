/** @vitest-environment jsdom */
import { mountDrawerHeader } from '../drawer/header-mount';
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, tick } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async () => ({ v: 1, rev: 1, window: '1h', bucket_seconds: 60, start: 1, now: 2, state: 'ok', in: [1], out: [1], totals: null, rate: null, sources: [], machines: [] }),
}));

import * as Search from '../drawer/search';
import { unmountPanel } from '../mount';
import { setDrawerEnv } from '../drawer/env';
import { setViewClassSource } from '../drawer/view-class';
import { init, PREFERENCE_FIELD } from '../drawer/stats-visibility.svelte';
import { setLocale } from '../i18n/index.svelte';
import { applyDrawerTab, DRAWER_LIST_ID, DRAWER_SEARCH_ID, DRAWER_STATS_ID } from '../drawer-tabs/drawer-tabs';
import { BUILTIN_TABS } from '../dynamic-tabs/builtin';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { SidebarWidgetRegistry } from './registry';
import { registerCoreSidebarWidgets, sessionListWidget } from './core-widgets';
import { MENU_FLYOUT, QUESTIONS_FLYOUT, SESSION_LIST_WIDGET, SIDEBAR_STATS_WIDGET } from './widget-ids';
import { RAIL_LAYOUT, SIDEBAR_TOPBAR_CONTROLS_ID, mountSidebarLayout } from './host';
import { applyRailDom, REGION_ID } from './rail-dom';

setLocale('en');

const REPO = path.resolve(process.cwd(), '..');

function drawerMarkup(): string {
  const source = fs.readFileSync(path.join(REPO, 'client', 'index.html'), 'utf8');
  const start = source.indexOf('<aside id="session-sidebar-panel"');
  const end = source.indexOf('</aside>', start);
  if (start < 0 || end < 0) throw new Error('the drawer markup is missing from client/index.html');
  return source.slice(start, end + '</aside>'.length);
}

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
    await tick();
    flushSync();
    await new Promise((r) => setTimeout(r, 5));
  }
}

function bridge(store: Record<string, unknown>) {
  return {
    PreferenceBridge: {
      read: (field: string, fallback: () => unknown) => (field in store ? store[field] : fallback()),
      write: async (field: string, value: unknown, local: () => void) => { store[field] = value; local(); },
    },
  };
}

const win = globalThis as unknown as Record<string, unknown>;

beforeEach(() => {
  document.body.innerHTML = drawerMarkup();
  mountDrawerHeader();
  localStorage.clear();
  Search.setQuery('');
  win.SessionSidebarSearch = { getQuery: Search.getQuery, setQuery: Search.setQuery, matchesRow: Search.matchesRow, matchesLabel: Search.matchesLabel, noMatchesHtml: Search.noMatchesHtml, normalize: Search.normalize };
  class FakeObserver { observe(): void {} disconnect(): void {} unobserve(): void {} }
  vi.stubGlobal('VisibilityObserver', FakeObserver);
  vi.stubGlobal('ResizeObserver', FakeObserver);
  setViewClassSource(() => 'desktop');
});
afterEach(() => {
  for (const id of [DRAWER_SEARCH_ID, DRAWER_STATS_ID, SIDEBAR_TOPBAR_CONTROLS_ID]) unmountPanel(id);
  document.body.replaceChildren();
  document.body.className = '';
  delete win.SessionSidebarSearch;
  setDrawerEnv(null);
  setViewClassSource(null);
  vi.unstubAllGlobals();
});

function coreRegistry(): SidebarWidgetRegistry {
  const registry = new SidebarWidgetRegistry();
  registerCoreSidebarWidgets(registry);
  registerCoreSidebarWidgets(registry);
  return registry;
}

test('the drawer widgets register once, with their kinds, and are not grid widgets', () => {
  const registry = coreRegistry();
  expect(registry.all().map((w) => w.id)).toEqual([SIDEBAR_STATS_WIDGET, MENU_FLYOUT, SESSION_LIST_WIDGET, QUESTIONS_FLYOUT]);
  expect(registry.get(SESSION_LIST_WIDGET)?.kind).toBe('system');
  expect(registry.get(SIDEBAR_STATS_WIDGET)?.kind).toBe('registered');
  expect(CORE_MANIFESTS[SESSION_LIST_WIDGET]).toBeUndefined();
  expect(CORE_MANIFESTS[SIDEBAR_STATS_WIDGET]).toBeUndefined();
});

test('the rail layout mounts into the drawer\'s containers, the controls in the top bar, stats hidden when sidebar_show_stats is off', async () => {
  setDrawerEnv(bridge({ [PREFERENCE_FIELD]: false }));
  init();
  expect(applyRailDom()).toBe(true);
  const report = mountSidebarLayout(RAIL_LAYOUT, coreRegistry());
  await settle();
  expect(report.mounted).toEqual([`${SIDEBAR_STATS_WIDGET}.bar`, `${SESSION_LIST_WIDGET}.search`, `${SESSION_LIST_WIDGET}.controls`]);
  expect(document.querySelector(`#${SIDEBAR_TOPBAR_CONTROLS_ID} [data-action="density"]`)).not.toBeNull();
  expect(report.painted).toEqual([`${SESSION_LIST_WIDGET}.tree`]);
  expect(report.missing).toEqual([]);
  expect(document.querySelector(`#${DRAWER_SEARCH_ID} input`)).not.toBeNull();
  expect(document.getElementById(DRAWER_LIST_ID)?.childElementCount).toBe(0);
  expect(document.querySelector(`#${DRAWER_STATS_ID} .dst-row`)).toBeNull();
  expect(document.getElementById(DRAWER_STATS_ID)?.nextElementSibling?.id).toBe(REGION_ID);
  const order = [...document.querySelectorAll('.session-sidebar-scroll > [id]')].map((el) => el.id);
  expect(order).toEqual([DRAWER_SEARCH_ID, DRAWER_LIST_ID]);
});

test('stats shows when sidebar_show_stats is on, and the menu tab still hides the list widget and the stats', async () => {
  setDrawerEnv(bridge({ [PREFERENCE_FIELD]: true }));
  init();
  applyRailDom();
  mountSidebarLayout(RAIL_LAYOUT, coreRegistry());
  await settle();
  expect(document.querySelector(`#${DRAWER_STATS_ID} .dst-row`)).not.toBeNull();
  applyDrawerTab('menu', BUILTIN_TABS);
  for (const id of [DRAWER_STATS_ID, DRAWER_SEARCH_ID, DRAWER_LIST_ID]) expect(document.getElementById(id)?.hidden).toBe(true);
  applyDrawerTab('agents', BUILTIN_TABS);
  for (const id of [DRAWER_STATS_ID, DRAWER_SEARCH_ID, DRAWER_LIST_ID]) expect(document.getElementById(id)?.hidden).toBe(false);
});

test('the contract refuses a slide-out with no tint, a tint off a slide-out, and a duplicate id', () => {
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
  const registry = coreRegistry();
  const parts = { body: { paintedBy: 'drawer-list' as const } };
  expect(registry.register({ id: 'x.flyout', titleKey: 'k', icon: 'bot', kind: 'registered', surface: 'flyout', order: 1, parts })).toEqual({ ok: false, reason: 'tint-required' });
  expect(registry.register({ id: 'x.strip', titleKey: 'k', icon: 'bot', kind: 'registered', surface: 'strip', tint: '--oc-yellow', order: 1, parts })).toEqual({ ok: false, reason: 'tint-not-allowed' });
  expect(registry.register(sessionListWidget)).toEqual({ ok: false, reason: 'duplicate-id' });
  expect(registry.register({ id: 'x.questions', titleKey: 'k', icon: 'question', kind: 'registered', surface: 'flyout', tint: '--oc-yellow', order: 30, parts })).toEqual({ ok: true });
  warn.mockRestore();
});
