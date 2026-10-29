/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import DrawerMenu from './DrawerMenu.svelte';
import { setLocale } from '../i18n/index.svelte';
import { cplugEnablement } from '../../cplugs/host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };
setLocale('en');

type Win = Record<string, unknown>;
const win = globalThis as unknown as Win;
const mounted: ReturnType<typeof mount>[] = [];
const openPluginsScreen = vi.fn();
const openSettingsScreen = vi.fn();
const openWrappersScreen = vi.fn();
const openHostsScreen = vi.fn();
const showLaunchpad = vi.fn();

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(1_000_000);
  win.CloudeWeb = { openPluginsScreen, openSettingsScreen, openWrappersScreen, openHostsScreen };
  win.App = { showLaunchpad };
});

afterEach(async () => {
  vi.useRealTimers();
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  for (const f of [openPluginsScreen, openSettingsScreen, openWrappersScreen, openHostsScreen, showLaunchpad]) f.mockClear();
  delete win.App;
  delete win.CloudeWeb;
});

function render(): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(DrawerMenu, { target }));
  flushSync();
  return target;
}

function press(el: Element, key: string, init: KeyboardEventInit = {}): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  el.dispatchEvent(event);
  return event;
}

const inMenu = (root: HTMLElement) => root.querySelector('[data-rail-item="dashboards"]')!;

test('row order is the one the team set on 2026-10-13, dashboards first, with no quick links heading and help before documentation and changelog', () => {
  const root = render();
  const ids = [...root.querySelectorAll<HTMLElement>('[data-rail-item]')].map((b) => b.dataset.railItem);
  expect(ids).toEqual([
    'dashboards', 'sessions', 'automations', 'warez', 'widgets', 'blueprints',
    'providers', 'hosts', 'docs', 'changelog', 'settings',
  ]);
  const heads = [...root.querySelectorAll('h2.oc-sidebar-head')].map((h) => h.textContent?.trim());
  expect(heads).toEqual(['help']);
  const help = root.querySelector('h2.oc-sidebar-head')!;
  const after = [...root.querySelectorAll<HTMLElement>('[data-rail-item]')].filter(
    (b) => help.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING,
  );
  expect(after.map((b) => b.dataset.railItem)).toEqual(['docs', 'changelog', 'settings']);
});

test('backtick, l and h open settings, launch profiles and pack while focus is in the menu (l has no row: it opens a Settings section)', () => {
  const root = render();
  const el = inMenu(root);
  expect(press(el, '`').defaultPrevented).toBe(true);
  expect(openSettingsScreen).toHaveBeenCalledTimes(1);
  press(el, 'l');
  expect(openWrappersScreen).toHaveBeenCalledTimes(1);
  press(el, 'h');
  expect(openHostsScreen).toHaveBeenCalledTimes(1);
  expect(root.querySelector('[data-rail-item="wrappers"]')).toBeNull();
});

test('two dots within 600ms open home, two dots a second apart do not', () => {
  const el = inMenu(render());
  press(el, '.');
  vi.advanceTimersByTime(300);
  press(el, '.');
  expect(showLaunchpad).toHaveBeenCalledTimes(1);
  vi.advanceTimersByTime(5000);
  press(el, '.');
  vi.advanceTimersByTime(1000);
  press(el, '.');
  expect(showLaunchpad).toHaveBeenCalledTimes(1);
});

test('a modifier, a text field target, or focus outside the menu does nothing', () => {
  const root = render();
  const el = inMenu(root);
  expect(press(el, 'h', { metaKey: true }).defaultPrevented).toBe(false);
  press(el, 'h', { ctrlKey: true });
  press(el, 'h', { altKey: true });
  const input = document.createElement('input');
  root.querySelector('nav')!.append(input);
  press(input, 'h');
  const outside = document.createElement('div');
  document.body.append(outside);
  expect(press(outside, 'h').defaultPrevented).toBe(false);
  expect(openHostsScreen).not.toHaveBeenCalled();
});
