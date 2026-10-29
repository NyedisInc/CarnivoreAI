/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../opscenter/api', () => ({
  isDemo: () => false,
  auth: { state: 'signed-in' },
  initAuth: () => {},
  startEvents: () => {},
  sessions: { status: 'idle', data: null },
  transport: { state: 'unknown' },
}));

import SingleWidget from './SingleWidget.svelte';
import CellMenu from '../opscenter/engine/CellMenu.svelte';
import { homeLayout } from '../opscenter/engine/layout.svelte';
import { CORE_MANIFESTS } from '../opscenter/widgets/core-manifests';
import { installPopoverPolyfill } from '../lib/popover-jsdom-polyfill';
import {
  POPOUT_MIN,
  WIDGET_WINDOW_CAP,
  isWidgetId,
  openWidgetPopout,
  widgetFromSearch,
  placementFromSearch,
  widgetPath,
  widgetWindowName,
  widgetWindowSize,
} from './popout';

installPopoverPolyfill();

let app: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  localStorage.clear();
  vi.restoreAllMocks();
});

test('the url names one core widget and refuses anything else', () => {
  expect(widgetFromSearch('?widget=core.machine-stats')).toBe('core.machine-stats');
  expect(widgetFromSearch('?widget=../../etc')).toBeNull();
  expect(widgetFromSearch('?widget=analytics:chart')).toBeNull();
  expect(widgetFromSearch('')).toBeNull();
  expect(isWidgetId('core.')).toBe(false);
  expect(widgetPath('core.notes')).toBe('/static/popout.html?widget=core.notes');
});

test('a pop-out carries the session, view and options of the placement it came from (B4), and drops a hand-edited url', () => {
  const path = widgetPath('core.tasks', { sessionId: 'ses_1', view: 'all', options: { density: 'compact', show_header: true } });
  expect(placementFromSearch(path.slice(path.indexOf('?')))).toEqual({ sessionId: 'ses_1', view: 'all', options: { density: 'compact', show_header: true } });
  expect(placementFromSearch('?widget=core.tasks&options=%7Bnope&view=NOT%20A%20VIEW')).toEqual({});
  expect(placementFromSearch('?options=%5B1%5D')).toEqual({});
});

test('the window opens at the declared size, held between the minimum and the cap', () => {
  const fits = CORE_MANIFESTS['core.machine-stats']!.fits;
  const size = widgetWindowSize(fits);
  expect(size.width).toBeGreaterThanOrEqual(POPOUT_MIN.width);
  expect(size.width).toBeLessThanOrEqual(WIDGET_WINDOW_CAP.width);
  expect(size.height).toBeGreaterThanOrEqual(POPOUT_MIN.height);
  expect(widgetWindowSize({ min: { w: 2, h: 2 }, sizes: ['medium'], anySize: true })).toEqual({ ...WIDGET_WINDOW_CAP });
  expect(widgetWindowSize({ min: { w: 2, h: 2 }, sizes: ['medium', 'full'], anySize: false }).width).toBe(WIDGET_WINDOW_CAP.width);
});

test('opening names a window per widget and refuses a bad id', () => {
  const win = { open: vi.fn(() => ({ focus: vi.fn() })) } as unknown as Window;
  const fits = CORE_MANIFESTS['core.machine-stats']!.fits;
  expect(openWidgetPopout('core.machine-stats', fits, win)).not.toBeNull();
  const call = (win.open as unknown as ReturnType<typeof vi.fn>).mock.calls[0]!;
  expect(call[0]).toBe('/static/popout.html?widget=core.machine-stats');
  expect(call[1]).toBe(widgetWindowName('core.machine-stats'));
  expect(call[2]).toContain('popup=yes');
  expect(openWidgetPopout('nope', fits, win)).toBeNull();
  expect((win.open as unknown as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(1);
});

test('the grid icon menu offers pop out and it opens that widget', () => {
  const open = vi.spyOn(window, 'open').mockReturnValue({ focus: () => {} } as unknown as Window);
  app = mount(CellMenu, { target: document.body, props: { id: 'machine-stats' as never, anchor: null, onClose: () => {}, store: homeLayout } });
  flushSync();
  const item = document.querySelector<HTMLButtonElement>('[data-node="pop-out"]');
  expect(item).not.toBeNull();
  item!.click();
  expect(open).toHaveBeenCalledOnce();
  expect(String(open.mock.calls[0]![0])).toContain('widget=core.machine-stats');
});

test('the page shows one widget alone, and a notice for one it cannot show', () => {
  const target = document.createElement('div');
  document.body.append(target);
  app = mount(SingleWidget, { target, props: { widget: 'core.machine-stats' } });
  flushSync();
  expect(target.querySelector('[data-popout-widget="core.machine-stats"]')).not.toBeNull();
  const pane = target.querySelector('[data-zone-pane="core.machine-stats"]');
  expect(pane).not.toBeNull();
  expect(pane!.getAttribute('data-zone-visible')).toBe('shown');
  expect(pane!.querySelector('[data-popout-widget]')).not.toBeNull();
  unmount(app);
  app = mount(SingleWidget, { target, props: { widget: 'core.no-such-widget' } });
  flushSync();
  expect(target.querySelector('[data-widget-unavailable]')).not.toBeNull();
  expect(target.querySelector('[data-popout-widget]')).toBeNull();
});

test('the window wears the one widget header: the icon that opens the menu, the catalog name, and a close x', () => {
  const target = document.createElement('div');
  document.body.append(target);
  app = mount(SingleWidget, { target, props: { widget: 'core.machine-stats' } });
  flushSync();
  const head = target.querySelector('[data-popout-widget="core.machine-stats"] > [data-widget-head]')!;
  expect(head).not.toBeNull();
  expect(head.querySelector('.oc-frame-name')?.textContent).toBe('this machine');
  expect(head.firstElementChild?.matches('.oc-frame-cornerwrap')).toBe(true);
  expect(head.querySelector('button[data-corner]')).not.toBeNull();
  expect(head.querySelector('[data-head-close]')).not.toBeNull();
  expect(target.querySelector('.sw-head')).toBeNull();
});

test('the icon opens the same menu (no pop out, focus main window when there is one) and close widget and the x close the window', () => {
  const close = vi.spyOn(window, 'close').mockImplementation(() => {});
  const focus = vi.fn();
  Object.defineProperty(window, 'opener', { value: { closed: false, focus }, configurable: true });
  const target = document.createElement('div');
  document.body.append(target);
  app = mount(SingleWidget, { target, props: { widget: 'core.machine-stats' } });
  flushSync();
  const icon = target.querySelector<HTMLButtonElement>('button[data-corner]')!;
  icon.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
  flushSync();
  const ids = [...document.querySelectorAll<HTMLElement>('.acm-item')].map((el) => el.dataset.node);
  expect(ids).toEqual(['focus-main-window', 'close-widget']);
  expect(ids).not.toContain('pop-out');
  document.querySelector<HTMLElement>('[data-node="focus-main-window"]')!.click();
  expect(focus).toHaveBeenCalledOnce();
  flushSync();
  icon.click();
  flushSync();
  document.querySelector<HTMLElement>('[data-node="close-widget"]')!.click();
  expect(close).toHaveBeenCalledOnce();
  target.querySelector<HTMLElement>('[data-head-close]')!.click();
  expect(close).toHaveBeenCalledTimes(2);
  Object.defineProperty(window, 'opener', { value: null, configurable: true });
});
