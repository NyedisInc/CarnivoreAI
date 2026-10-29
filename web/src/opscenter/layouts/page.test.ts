/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

const listing = vi.hoisted(() => ({
  data: [
    { session: { id: 's-a' }, session_row_id: 1, label: 'api', tmux_session: 'cloude_api' },
    { session: { id: 's-b' }, session_row_id: 2, label: 'web', tmux_session: 'cloude_web' },
  ] as unknown[],
  status: 'ok',
  refresh: async () => undefined,
}));
vi.mock('../api/sessions.svelte', () => ({ sessions: listing }));

const host = vi.hoisted(() => ({ opened: [] as [string, string][], primary: 's-z', tmux: 'cloude_z' }));

const capture = vi.hoisted(() => ({ gate: null as Promise<void> | null }));
vi.mock('../cells/terminal-live/client', () => ({
  withScrollback: async (row: unknown) => {
    if (capture.gate) await capture.gate;
    return row;
  },
}));

const bridge = vi.hoisted(() => ({ held: null as unknown }));
vi.mock('../../lib/layouts-bridge/api.svelte', () => ({ layoutByUuid: () => bridge.held }));
vi.mock('../api/host', async (actual) => ({
  ...(await actual<typeof import('../api/host')>()),
  openSession: (id: string, tmux: string) => {
    host.opened.push([id, tmux]);
    return true;
  },
  primarySessionId: () => host.primary,
  primaryTmuxName: () => host.tmux,
  primaryTmuxEpoch: () => null,
}));

const STORED = {
  layout_uuid: 'L1',
  name: 'api + web',
  position: 0,
  revision: 2,
  source_key: null,
  created_at: '',
  updated_at: '',
  members: [
    { session_row_id: 1, session_uuid: 'u1', position: 0 },
    { session_row_id: 2, session_uuid: 'u2', position: 1 },
  ],
  shape: {
    layout: {
      v: 6,
      rows: [{ id: 'r1', kind: 'flex', size: 1, slots: [{ id: 'terminal:row:1', fr: 0.5 }, { id: 'terminal:row:2', fr: 0.5 }] }],
      hidden: [],
      heroCollapsed: false,
      collapsed: [],
    },
    groups: {},
  },
};
const renew = vi.hoisted(() => vi.fn(async () => ({})));
const listed = vi.hoisted(() => ({ count: 0 }));
vi.mock('./api', async (actual) => ({
  ...(await actual<typeof import('./api')>()),
  listLayouts: async () => {
    listed.count += 1;
    return { status: 'ok', layouts: [STORED], detail: null };
  },
  renewActive: renew,
}));

const allDown = vi.hoisted(() => ({
  calls: [] as unknown[],
  resolve: false as boolean | null,
  onClose: (): void => undefined,
}));
vi.mock('../../lib/modal', () => ({
  openModal: async (_component: unknown, props: unknown) => {
    allDown.calls.push(props);
    allDown.onClose();
    return allDown.resolve;
  },
}));

import { terminalLayout } from '../engine/layout.svelte';
import { bindPrimary } from '../engine/primary-bind';
import { activeTabFor, resetTabCache, tabsFor } from '../engine/tab-groups.svelte';
import { PRIMARY_SLOT } from '../engine/model';
import { LEASE_MS, layoutPageApi, openFromUrl, openLayout, pathFor, start } from './page.svelte';
import { readLastView } from '../../lib/drawer/last-view';
import { layoutActive, layoutMode } from './mode.svelte';

const win = globalThis as unknown as Record<string, unknown>;
let generation = 0;
const rejected: string[] = [];
const entered: string[] = [];

beforeEach(() => {
  vi.useFakeTimers();
  generation = 0;
  win.NavigationGeneration = {
    begin: () => ++generation,
    current: () => generation,
    keep: (token: number) => token === generation,
  };
  win.Router = { rejectTarget: (uuid: string) => rejected.push(uuid), showError: () => undefined };
  entered.length = 0;
  win.App = {
    currentScreen: 'terminal',
    returnToExistingTerminal: (row: { session?: { id?: string } }) => entered.push(row.session?.id ?? ''),
  };
  capture.gate = null;
  bridge.held = null;
  listed.count = 0;
  host.opened.length = 0;
  host.primary = 's-z';
  host.tmux = 'cloude_z';
  rejected.length = 0;
  renew.mockClear();
  allDown.calls.length = 0;
  allDown.resolve = false;
  allDown.onClose = () => undefined;
  listing.data = [
    { session: { id: 's-a' }, session_row_id: 1, label: 'api', tmux_session: 'cloude_api' },
    { session: { id: 's-b' }, session_row_id: 2, label: 'web', tmux_session: 'cloude_web' },
  ];
  start();
  terminalLayout.bindSession('cloude_z', null);
});

afterEach(() => {
  generation += 1;
  bindPrimary(terminalLayout, 's-z', 'cloude_z', null);
  vi.useRealTimers();
  terminalLayout.bindSession('');
  resetTabCache();
  localStorage.clear();
});

async function openAndArrive(): Promise<void> {
  await openLayout('L1');
  expect(entered).toEqual(['s-a']);
  expect(layoutMode.holding).toBe(true);
  host.primary = 's-a';
  host.tmux = 'cloude_api';
  expect(pathFor('cloude_api')).toBe('/layout/L1');
  bindPrimary(terminalLayout, 's-a', 'cloude_api', null);
  expect(layoutMode.holding).toBe(false);
}

test('opening draws the Layout, then enters the first live member into its cell', async () => {
  await openAndArrive();
  expect(host.opened).toEqual([]);
  expect(layoutActive()).toBe(true);
  expect(terminalLayout.session).toBe('layout:L1');
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT]);
  expect(tabsFor(terminalLayout, 'terminal:row:2')).toEqual(['terminal:row:2']);
  expect(location.pathname).toBe('/layout/L1');
});

test('the anchor rebinding under the same navigation keeps the Layout (a reconnect)', async () => {
  await openAndArrive();
  bindPrimary(terminalLayout, 's-a', 'cloude_api', null);
  expect(layoutActive()).toBe(true);
  expect(terminalLayout.session).toBe('layout:L1');
});

test('a newer navigation to the anchor alone leaves the Layout: the agent shows alone', async () => {
  await openAndArrive();
  generation += 1;
  expect(pathFor('cloude_api')).toBeNull();
  expect(layoutActive()).toBe(false);
  expect(terminalLayout.session).toBe('cloude_api');
});

test('a bind of another session under a newer navigation leaves the Layout', async () => {
  await openAndArrive();
  generation += 1;
  bindPrimary(terminalLayout, 's-b', 'cloude_web', null);
  expect(layoutActive()).toBe(false);
  expect(terminalLayout.session).toBe('cloude_web');
});

test('the grid is drawn BEFORE the anchor is entered: no single-session step (issue #835)', async () => {
  let release: () => void = () => undefined;
  capture.gate = new Promise<void>((resolve) => (release = resolve));
  const opening = openLayout('L1');
  await vi.advanceTimersByTimeAsync(0);
  expect(terminalLayout.session).toBe('layout:L1');
  expect(tabsFor(terminalLayout, 'terminal:row:2')).toEqual(['terminal:row:2']);
  expect(layoutMode.holding).toBe(true);
  expect(entered).toEqual([]);
  release();
  await opening;
  expect(entered).toEqual(['s-a']);
});

test('while holding, a bind of the session the pane is leaving keeps the grid and every member cell', async () => {
  host.primary = 's-b';
  host.tmux = 'cloude_web';
  terminalLayout.bindSession('cloude_web', null);
  await openLayout('L1');
  bindPrimary(terminalLayout, 's-b', 'cloude_web', null);
  expect(terminalLayout.session).toBe('layout:L1');
  expect(tabsFor(terminalLayout, 'terminal:row:2')).toEqual(['terminal:row:2']);
  expect(layoutMode.holding).toBe(true);
});

test('a newer navigation while the anchor capture is in flight enters nothing', async () => {
  let release: () => void = () => undefined;
  capture.gate = new Promise<void>((resolve) => (release = resolve));
  const opening = openLayout('L1');
  await vi.advanceTimersByTimeAsync(0);
  generation += 1;
  release();
  await opening;
  expect(entered).toEqual([]);
});

test('the drawer\'s held Layout is drawn with no round trip', async () => {
  bridge.held = STORED;
  const opening = openLayout('L1');
  expect(terminalLayout.session).toBe('layout:L1');
  await opening;
  expect(entered).toEqual(['s-a']);
});

test('the anchor already on the terminal screen: drawn in place, nothing entered', async () => {
  host.primary = 's-a';
  host.tmux = 'cloude_api';
  await openLayout('L1');
  expect(entered).toEqual([]);
  expect(layoutMode.holding).toBe(false);
  expect(terminalLayout.session).toBe('layout:L1');
});

test('an unknown Layout link goes through rejectTarget and opens nothing', async () => {
  await openFromUrl('nope');
  expect(rejected).toEqual(['nope']);
  expect(entered).toEqual([]);
  expect(layoutActive()).toBe(false);
});

test('no live member: the all-down modal is offered instead of a bare error, and opens nothing on cancel', async () => {
  listing.data = [];
  allDown.resolve = false;
  await openLayout('L1');
  expect(allDown.calls).toEqual([{ layout: STORED }]);
  expect(entered).toEqual([]);
  expect(layoutActive()).toBe(false);
});

test('no live member: a revival in the modal re-opens the Layout for real', async () => {
  const original = listing.data;
  listing.data = [];
  allDown.resolve = true;
  allDown.onClose = () => {
    listing.data = original;
  };
  await openLayout('L1');
  expect(entered).toEqual(['s-a']);
});

test('while open, the active lease is renewed at once and every minute; closed, never', async () => {
  await openAndArrive();
  expect(renew).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(LEASE_MS);
  expect(renew).toHaveBeenCalledTimes(2);
  expect(renew).toHaveBeenLastCalledWith('L1');
  generation += 1;
  pathFor('cloude_web');
  await vi.advanceTimersByTimeAsync(LEASE_MS * 2);
  expect(renew).toHaveBeenCalledTimes(2);
  expect(layoutMode.uuid).toBe('');
});

test('opening a Layout at a member focuses that member\'s background tab; a second member only moves the tab (#1266)', async () => {
  const tabbed = structuredClone(STORED);
  tabbed.shape = {
    ...tabbed.shape,
    layout: { ...tabbed.shape.layout, rows: [{ id: 'r1', kind: 'flex', size: 1, slots: [{ id: 'terminal:row:1', fr: 1 }] }] },
    groups: { 'terminal:row:1': { tabs: ['terminal:row:1', 'terminal:row:2'] } },
  } as typeof STORED.shape;
  bridge.held = tabbed;
  await openLayout('L1');
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(PRIMARY_SLOT);
  const before = generation;
  await openLayout('L1', false, 'u2');
  expect(generation).toBe(before);
  expect(layoutActive()).toBe(true);
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe('terminal:row:2');
  await openLayout('L1', false, 'u1');
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(PRIMARY_SLOT);
});

function raiseSettingsPage(): HTMLElement {
  const container = document.createElement('div');
  container.id = 'settings-screen';
  container.appendChild(document.createElement('div'));
  document.body.appendChild(container);
  win.CloudeWeb = { ...(win.CloudeWeb as object), closeSettingsScreen: () => container.replaceChildren() };
  return container;
}

test('clicking the open Layout, or a session in it, while a menu page is up takes the page down without re-opening it', async () => {
  const tabbed = structuredClone(STORED);
  bridge.held = tabbed;
  await openAndArrive();
  const before = entered.length;
  const page = raiseSettingsPage();
  await openLayout('L1');
  expect(page.firstElementChild).toBeNull();
  page.remove();
  const again = raiseSettingsPage();
  await openLayout('L1', false, 'u2');
  expect(again.firstElementChild).toBeNull();
  expect(entered.length).toBe(before);
  page.remove();
  again.remove();
});

test('opening a Layout records it as the last view, and it holds its anchor but not a stranger (#1542)', async () => {
  await openAndArrive();
  expect(readLastView()).toEqual({ kind: 'layout', uuid: 'L1' });
  expect(layoutPageApi.holds('s-a', 'cloude_api')).toBe(true);
  expect(layoutPageApi.holds('s-q', 'cloude_other')).toBe(false);
});
