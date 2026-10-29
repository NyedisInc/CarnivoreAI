/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async () => ({ v: 1, rev: 1, window: '1h', bucket_seconds: 60, start: 1, now: 2, state: 'ok', in: [1], out: [1], totals: null, rate: null, sources: [], machines: [] }),
}));

import { setLocale } from '../lib/i18n/index.svelte';
import { widgetBars } from '../lib/widget-bars/bar-settings.svelte';
import { offerStripPins } from '../lib/widget-bars/bar-pin-action';
import { railMenu, railMenuItems } from '../lib/sidebar-widgets/rail-menu.svelte';
import { RAIL_CONTAINER_ID } from '../lib/sidebar-widgets/rail-dom';
import { railOn, setupRail, teardownRail } from '../lib/sidebar-widgets/fixtures/rail-harness';
import { emptyMenu, emptyMenuNodes } from '../opscenter/layout-editor/empty-space-menu.svelte';
import { applyHarnessHostOptions } from './host-options';
import mainSource from './main.ts?raw';

setLocale('en');

const g = globalThis as Record<string, unknown>;
const shell = (): HTMLElement => document.querySelector<HTMLElement>(`#${RAIL_CONTAINER_ID} .sbr-shell`)!;
const pinItems = (nodes: { id: string }[]): string[] => nodes.map((n) => n.id).filter((id) => /pin/.test(id));

beforeEach(async () => {
  await setupRail();
  const shared: Record<string, unknown> = { widget_bars: { v: 1, rail: { mode: 'pinned' }, side: { mode: 'pinned' }, bottom: { mode: 'pinned' } } };
  g.PreferenceBridge = {
    read: (field: string, fallback: () => unknown) => (field in shared ? shared[field] : fallback()),
    write: async () => ({ status: 'committed' }),
    follow: () => () => {},
  };
  widgetBars.reload();
});
afterEach(async () => {
  offerStripPins(true);
  emptyMenu.at = null;
  railMenu.at = null;
  railMenu.keyId = null;
  delete g.PreferenceBridge;
  widgetBars.reload();
  await teardownRail();
});

test('the app offers the pin: a right-click on the real rail handle has "pin rail" and a stored pin keeps the rail out', async () => {
  await railOn();
  expect(shell().dataset['railState']).toBe('pinned');
  railMenu.keyId = null;
  expect(pinItems(railMenuItems())).toEqual(['pin-bar']);
  emptyMenu.target = 'side';
  expect(pinItems(emptyMenuNodes())).toEqual(['pin-bar']);
});

test('a Lab frame that draws the real chrome: no pin item in the rail\'s or a bar\'s own menu, and a stored pin draws nothing', async () => {
  applyHarnessHostOptions();
  await railOn();
  expect(shell().dataset['railState'], 'a stored pin does not keep the Lab rail out').toBe('handle');
  const handle = shell().querySelector<HTMLElement>('[data-bar-handle]')!;
  handle.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
  flushSync();
  expect(railMenu.keyId, 'the rail itself').toBeNull();
  expect(pinItems(railMenuItems()), 'no pin rail').toEqual([]);
  emptyMenu.target = 'side';
  expect(pinItems(emptyMenuNodes()), 'no pin bar').toEqual([]);
  handle.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 }));
  flushSync();
  expect(shell().querySelector('[data-bar-pin]'), 'no pin icon on the Lab rail').toBeNull();
});

test('every Lab frame boots through the host options before anything is drawn', () => {
  const main = mainSource;
  const call = main.indexOf('applyHarnessHostOptions();');
  expect(call, 'main.ts applies the host options').toBeGreaterThan(-1);
  for (const mount of ['mountPanel(', 'drawSidebar(']) {
    const first = main.indexOf(mount, main.indexOf('\n', main.lastIndexOf('\nimport ')));
    expect(first, `${mount} comes after the host options`).toBeGreaterThan(call);
  }
});
