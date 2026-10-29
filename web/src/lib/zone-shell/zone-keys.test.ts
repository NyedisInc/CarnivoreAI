/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../item-settings/store.svelte', () => ({ widgetSetting: () => true, isWidgetDisabled: () => false }));
vi.mock('../../opscenter/lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));

import KeysHarness from './fixtures/KeysHarness.svelte';

let handle: ReturnType<typeof mount> | null = null;
const keys = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>('[data-zone-item]')];
const stops = (): string[] => keys().filter((one) => one.getAttribute('tabindex') !== '-1').map((one) => one.dataset['zoneItem']!);

afterEach(() => {
  if (handle) unmount(handle);
  handle = null;
  document.body.innerHTML = '';
});

test('two zones are one strip with a single Tab stop, and the arrows move it across the sections', () => {
  handle = mount(KeysHarness, { target: document.body });
  flushSync();
  expect(keys().map((one) => one.dataset['zoneItem'])).toEqual(['k1', 'k2', 'k3']);
  expect(document.querySelectorAll('[data-rail-keys]')).toHaveLength(2);
  expect(stops()).toEqual(['k1']);
  keys()[0]!.focus();
  keys()[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
  flushSync();
  expect(document.activeElement).toBe(keys()[1]);
  expect(stops()).toEqual(['k2']);
  keys()[1]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
  flushSync();
  expect(document.activeElement).toBe(keys()[2]);
  expect(stops()).toEqual(['k3']);
  keys()[2]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
  keys()[2]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }));
  expect(document.activeElement).toBe(keys()[2]);
});

test('editing layout leaves every key a Tab stop for the layout editor, whose arrows move keys instead', () => {
  handle = mount(KeysHarness, { target: document.body, props: { editing: true } });
  flushSync();
  expect(stops()).toEqual(['k1', 'k2', 'k3']);
  keys()[0]!.focus();
  keys()[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
  expect(document.activeElement).toBe(keys()[0]);
});

test('the menu key, Shift+F10 and a right-click open that tab\'s menu through the zone, and the key shows it is open', () => {
  handle = mount(KeysHarness, { target: document.body, props: { opened: ['k2'] } });
  flushSync();
  expect(keys()[1]!.getAttribute('aria-expanded')).toBe('true');
  expect(keys()[0]!.getAttribute('aria-expanded')).toBe('false');
  keys()[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ContextMenu', bubbles: true, cancelable: true }));
  keys()[1]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true }));
  keys()[2]!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
  const harness = handle as unknown as { menus: string[] };
  expect(harness.menus).toEqual(['k1', 'k2', 'k3']);
});

test('Home and End jump to the ends of the strip', () => {
  handle = mount(KeysHarness, { target: document.body });
  flushSync();
  keys()[1]!.focus();
  keys()[1]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true, cancelable: true }));
  expect(document.activeElement).toBe(keys()[2]);
  keys()[2]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true, cancelable: true }));
  expect(document.activeElement).toBe(keys()[0]);
});

test('a zone with no menu of its own leaves the right-click and the menu key to the layout', () => {
  handle = mount(KeysHarness, { target: document.body, props: { menu: false } });
  flushSync();
  const click = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
  keys()[0]!.dispatchEvent(click);
  const menuKey = new KeyboardEvent('keydown', { key: 'ContextMenu', bubbles: true, cancelable: true });
  keys()[0]!.dispatchEvent(menuKey);
  expect(click.defaultPrevented).toBe(false);
  expect(menuKey.defaultPrevented).toBe(false);
});

test('flow lays one strip out in normal flow, toggle says pressed, and the badge draws a given count and the global mark', () => {
  handle = mount(KeysHarness, { target: document.body, props: { flow: true, toggle: true, opened: ['k2'], counts: { k1: 120, k2: null }, globals: ['k2'] } });
  flushSync();
  expect(document.querySelector('[data-rail-sections]')!.hasAttribute('data-flow')).toBe(true);
  expect(document.querySelector('[data-rail-split]')).toBeNull();
  expect(keys()[1]!.getAttribute('aria-pressed')).toBe('true');
  expect(keys()[1]!.hasAttribute('aria-expanded')).toBe(false);
  expect(keys()[0]!.querySelector('[data-rail-badge]')!.textContent).toBe('99+');
  expect(keys()[1]!.querySelector('[data-rail-badge]'), 'a null count draws no bubble').toBeNull();
  expect(keys()[1]!.querySelector('[data-widget-globe]'), 'the global mark rides the badge').not.toBeNull();
  expect(keys()[0]!.querySelector('[data-widget-globe]')).toBeNull();
});
