/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../widgets/fits', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../widgets/fits')>();
  return {
    ...actual,
    fitsForSlot: (id: string) =>
      id === 'ledger'
        ? { min: { w: 2, h: 2 }, sizes: ['medium', 'large'], anySize: false }
        : actual.fitsForSlot(id as never),
  };
});

import CellMenu from './CellMenu.svelte';
import { homeLayout } from './layout.svelte';
import { layoutEditor } from '../layout-editor/editor.svelte';
import { drawerZone } from '../../lib/drawer-zone/zone-store.svelte';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

let app: ReturnType<typeof mount> | null = null;

function open(id: string): void {
  app = mount(CellMenu, { target: document.body, props: { id: id as never, anchor: null, onClose: () => {}, store: homeLayout } });
  flushSync();
}

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  layoutEditor.active = true;
  layoutEditor.page = 'home';
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  layoutEditor.active = false;
  layoutEditor.page = null;
  vi.restoreAllMocks();
});

const row = (slots: string[]) => ({
  v: 6,
  rows: [{ id: 'r1', kind: 'px', size: 128, slots: slots.map((id) => ({ id, fr: 1 / slots.length })) }],
  hidden: [],
  heroCollapsed: false,
  collapsed: [],
});

test('move to the drawer area adds the widget to the zone store', () => {
  const add = vi.spyOn(drawerZone, 'add').mockReturnValue(true);
  open('activity-log');
  document.querySelector<HTMLElement>('[data-node="move-to-drawer"]')!.click();
  expect(add).toHaveBeenCalledWith('core.activity-log');
  document.body.innerHTML = '';
  open('ledger');
  expect(document.querySelector('[data-node="move-to-drawer"]')).toBeNull();
});

test('normal view (no edit layout): the menu lists no fold and no size items (Alex (Example-owner), 2026-10-12)', () => {
  layoutEditor.active = false;
  homeLayout.state.layout = row(['ledger', 'notes']) as never;
  open('ledger');
  expect(document.querySelector('[data-menu-size]')).toBeNull();
  expect(document.querySelector('[data-menu-reset-size], [data-menu-info], [data-menu-report]')).toBeNull();
  expect(document.querySelector('[data-menu-phone-fold]')).toBeNull();
});

test('settings... on a chart opens its settings directly, in edit layout only (item 685, Q3 b: edit mode is arranging plus settings)', async () => {
  const { configureSheet, closeConfigure } = await import('../widgets/chrome/configure.svelte');
  const slot = 'analytics:11111111-1111-4111-8111-111111111111';
  homeLayout.state.layout = row([slot, 'notes']) as never;
  layoutEditor.active = false;
  open(slot);
  expect(document.querySelector('[data-node="settings"]')).toBeNull();
  unmount(app!);
  app = null;
  document.body.innerHTML = '';
  layoutEditor.active = true;
  open(slot);
  document.querySelector<HTMLElement>('[data-node="settings"]')!.click();
  flushSync();
  expect(layoutEditor.active).toBe(true);
  expect(configureSheet).toMatchObject({ slot, kind: 'settings' });
  closeConfigure();
});

test('a plugin widget slot offers pop out and opens its own widget window (S2d, docs/cplugs.md 2.7)', async () => {
  layoutEditor.active = false;
  const { registerCplugWidgets } = await import('../../cplugs/host/widgets');
  const { huddleCplug } = await import('../../cplugs/huddle');
  registerCplugWidgets(huddleCplug);
  const slot = 'huddle.chat:agent:7';
  homeLayout.state.layout = row([slot, 'notes']) as never;
  const opened = vi.spyOn(window, 'open').mockReturnValue(null);
  open(slot);
  const popOut = document.querySelector<HTMLElement>('[data-node="pop-out"]');
  expect(popOut).not.toBeNull();
  popOut!.click();
  expect(opened).toHaveBeenCalledTimes(1);
  expect(String(opened.mock.calls[0]?.[0])).toContain(`widget=${encodeURIComponent(slot)}`);
});
