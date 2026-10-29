/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async () => ({ v: 1, rev: 1, window: '1h', bucket_seconds: 60, start: 1, now: 2, state: 'ok', in: [1], out: [1], totals: null, rate: null, sources: [], machines: [] }),
}));

import { widgetBars } from '../widget-bars/bar-settings.svelte';
import { RETRACT_MS } from '../widget-bars/bar-state';
import { toggleBarPin } from '../widget-bars/bar-pin-action';
import { railMenu, railMenuItems } from './rail-menu.svelte';
import { setLocale } from '../i18n/index.svelte';
import { DRAWER_LIST_ID } from '../drawer-tabs/drawer-tabs';
import { unmountRail } from './rail-layout.svelte';
import { RAIL_PINNED_BODY_CLASS, RAIL_CONTAINER_ID, setRailPinnedClass } from './rail-dom';
import { MENU_FLYOUT, SESSION_LIST_WIDGET } from './widget-ids';
import { activeFlyout, closeFlyout } from './flyout.svelte';
import { press, railBtn, railOn, settle, setupRail, teardownRail } from './fixtures/rail-harness';
import { matchGolden } from '../zone-shell/fixtures/golden';

setLocale('en');

const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

const g = globalThis as Record<string, unknown>;
let shared: Record<string, unknown>;
let writes: { field: string; value: unknown }[];

const shell = (): HTMLElement => document.querySelector<HTMLElement>(`#${RAIL_CONTAINER_ID} .sbr-shell`)!;
const stateOf = (): string | undefined => shell().dataset['railState'];
const handle = (): HTMLElement | null => shell().querySelector('.sbr-shell__handle [data-bar-handle]');
const edge = (): HTMLElement | null => shell().querySelector('.sbr-shell__edge [data-bar-handle]');
const enter = (el: Element): void => { el.dispatchEvent(Object.assign(new MouseEvent('pointerenter'), { pointerType: 'mouse' })); flushSync(); };
const leave = (el: Element): void => { el.dispatchEvent(Object.assign(new MouseEvent('pointerleave'), { pointerType: 'mouse' })); flushSync(); };
const advance = (ms: number): void => { vi.advanceTimersByTime(ms); flushSync(); };
const click = (el: Element): void => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })); flushSync(); };
const open = (): void => { enter(shell()); click(handle()!); };

function focusKey(visible: boolean): void {
  const key = handle()!;
  const matches = key.matches.bind(key);
  key.matches = (selector: string): boolean => (selector === ':focus-visible' ? visible : matches(selector));
  key.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
  flushSync();
}

beforeEach(async () => {
  shared = {};
  writes = [];
  await setupRail();
  g.PreferenceBridge = {
    read: (field: string, fallback: () => unknown) => (field in shared ? shared[field] : fallback()),
    write: async (field: string, value: unknown, local: () => void) => { writes.push({ field, value }); shared[field] = value; local(); return { status: 'committed' }; },
    follow: () => () => {},
  };
  widgetBars.reload();
});

afterEach(async () => {
  vi.useRealTimers();
  setRailPinnedClass(false);
  delete g.PreferenceBridge;
  widgetBars.reload();
  await teardownRail();
});

test('the rail starts as a handle: no icons are drawn, and the list does not hide', async () => {
  await railOn();
  expect(stateOf()).toBe('handle');
  expect(handle()).not.toBeNull();
  expect(handle()!.getAttribute('aria-label')).toBe('show the sidebar rail');
  expect(handle()!.getAttribute('aria-expanded')).toBe('false');
  expect(shell().querySelector('[data-bar-pin]'), 'no pin icon while closed').toBeNull();
  expect(document.body.classList.contains(RAIL_PINNED_BODY_CLASS)).toBe(false);
  expect(document.getElementById(DRAWER_LIST_ID)!.hidden, 'the sidebar area never hides').toBe(false);
  expect(writes, 'a default is never written').toEqual([]);
});

test('a hover peeks it out and it goes back 300 ms after the pointer leaves; the pin lives in the footer, not the peek', async () => {
  await railOn();
  vi.useFakeTimers();
  enter(shell());
  expect(stateOf(), 'a hover opens it').toBe('peek');
  click(handle()!);
  expect(stateOf()).toBe('peek');
  expect(handle()!.getAttribute('aria-expanded')).toBe('true');
  expect(shell().querySelector('[data-bar-pin]'), 'an unpinned peek draws no icons and no pin of its own (#2047)').toBeNull();
  leave(shell());
  advance(RETRACT_MS - 10);
  expect(stateOf(), 'still out until the retract delay passes').toBe('peek');
  advance(20);
  expect(stateOf()).toBe('handle');
});

test('Enter on the handle peeks the rail and brings the menu out; Escape sends it back to the handle', async () => {
  await railOn();
  handle()!.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 0 }));
  await settle();
  vi.useFakeTimers();
  expect(stateOf()).toBe('peek');
  expect(activeFlyout(), 'the menu is what the peek shows').toBe(MENU_FLYOUT);
  (document.activeElement ?? document.body).dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  flushSync();
  advance(RETRACT_MS + 10);
  expect(stateOf()).toBe('handle');
});

test('a peek floats over the list: the drawer reserves only the handle track, in flow, unchanged by the peek', async () => {
  await railOn();
  expect(document.body.classList.contains(RAIL_PINNED_BODY_CLASS)).toBe(false);
  open();
  expect(stateOf()).toBe('peek');
  expect(document.body.classList.contains(RAIL_PINNED_BODY_CLASS), 'a peek never claims the column').toBe(false);
});

test('pin rail in the rail\'s own right-click menu writes widget_bars.rail.mode, keeps the rail out in its own column, and survives a reload', async () => {
  await railOn();
  handle()!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
  flushSync();
  expect(railMenu.keyId, 'the rail itself, not a key').toBeNull();
  const pin = railMenuItems().find((n) => n.id === 'pin-bar')!;
  expect(pin.label).toBe('pin rail');
  pin.run!();
  await settle();
  expect(writes).toEqual([{ field: 'widget_bars', value: { v: 1, rail: { mode: 'pinned' } } }]);
  expect(stateOf()).toBe('pinned');
  expect(handle(), 'a pinned rail has no handle').toBeNull();
  expect(railMenuItems().find((n) => n.id === 'pin-bar')!.label).toBe('unpin rail');
  expect(document.body.classList.contains(RAIL_PINNED_BODY_CLASS)).toBe(true);
  leave(shell());
  expect(stateOf()).toBe('pinned');

  unmountRail();
  widgetBars.reload();
  await railOn();
  expect(widgetBars.rail.mode).toBe('pinned');
  expect(stateOf()).toBe('pinned');
  expect(document.body.classList.contains(RAIL_PINNED_BODY_CLASS)).toBe(true);
});

test('unpinning sends the rail back to a handle; the rail has no close strip, so nothing on its edge hides or unpins it', async () => {
  await railOn();
  await toggleBarPin('rail');
  await settle();
  expect(stateOf()).toBe('pinned');
  await toggleBarPin('rail');
  await settle();
  expect(stateOf()).toBe('handle');
  expect(document.body.classList.contains(RAIL_PINNED_BODY_CLASS)).toBe(false);

  open();
  expect(stateOf()).toBe('peek');
  expect(edge(), 'no close strip down the rail edge').toBeNull();

  await toggleBarPin('rail');
  await settle();
  expect(stateOf()).toBe('pinned');
  expect(widgetBars.rail.mode).toBe('pinned');
});

test('a pinned rail still opens a slide-out over the list; the list stays mounted', async () => {
  shared['widget_bars'] = { v: 1, rail: { mode: 'pinned' } };
  widgetBars.reload();
  await railOn();
  await press(MENU_FLYOUT);
  expect(stateOf()).toBe('pinned');
  expect(document.getElementById(DRAWER_LIST_ID)).not.toBeNull();
});

test('one leave is one hide: the blur the browser fires when the layer hides does not peek the rail out again', async () => {
  await railOn();
  vi.useFakeTimers();
  open();
  focusKey(false);
  leave(shell());
  advance(RETRACT_MS + 10);
  expect(stateOf()).toBe('handle');
  handle()!.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: null }));
  flushSync();
  expect(stateOf(), 'no re-show').toBe('handle');
  advance(RETRACT_MS + 10);
  expect(stateOf()).toBe('handle');
});

test('a peek brings the menu out with it, the menu counts as the rail, and Escape ends both', async () => {
  await railOn();
  vi.useFakeTimers();
  open();
  expect(stateOf()).toBe('peek');
  expect(activeFlyout(), 'the menu slides out with the rail').toBe(MENU_FLYOUT);
  expect(document.body.classList.contains('sidebar-rail-peeking'), 'the old strip no longer peeks out').toBe(false);
  const slot = document.getElementById('session-sidebar-flyout')!;
  leave(shell());
  slot.dispatchEvent(Object.assign(new MouseEvent('pointerenter'), { pointerType: 'mouse' }));
  flushSync();
  advance(RETRACT_MS + 10);
  expect(stateOf()).toBe('peek');
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  flushSync();
  expect(activeFlyout(), 'an Escape from the page hides the unpinned rail and its menu').toBeNull();
  expect(stateOf()).toBe('handle');
  open();
  expect(activeFlyout()).toBe(MENU_FLYOUT);
  slot.querySelector('.sbr-flyout')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  flushSync();
  expect(activeFlyout()).toBeNull();
  expect(stateOf()).toBe('handle');
  open();
  expect(activeFlyout()).toBe(MENU_FLYOUT);
  leave(shell());
  advance(RETRACT_MS + 10);
  expect(stateOf()).toBe('handle');
  expect(activeFlyout()).toBeNull();
});

test('a menu row picked with a mouse closes the menu and it stays closed: the late pointer leave only retracts, it never peeks the menu out again', async () => {
  await railOn();
  vi.useFakeTimers();
  open();
  expect(activeFlyout(), 'the menu rides the peek').toBe(MENU_FLYOUT);
  closeFlyout();
  flushSync();
  expect(stateOf()).toBe('handle');
  leave(shell());
  expect(activeFlyout(), 'a leave is a retract, never a peek start').toBeNull();
  advance(RETRACT_MS + 10);
  expect(stateOf()).toBe('handle');
  expect(activeFlyout()).toBeNull();
});

test('the menu flyout has no title row and the rail no keys while auto-hiding; a pinned rail has icon keys, no menu key, and the title row on a slide-out (#1801, #2047)', async () => {
  const titleRow = (): Element | null => document.querySelector('#session-sidebar-flyout [data-flyout="core.menu"] .sbr-flyout__title');
  await railOn();
  vi.useFakeTimers();
  open();
  expect(activeFlyout(), 'the menu rides the peek').toBe(MENU_FLYOUT);
  flushSync();
  expect(titleRow(), 'no title row').toBeNull();
  expect(document.querySelector('#session-sidebar-flyout [data-flyout="core.menu"] .sbr-flyout__body')).not.toBeNull();
  expect(railBtn(MENU_FLYOUT), 'no menu key').toBeNull();
  expect(railBtn(SESSION_LIST_WIDGET), 'an unpinned rail draws no keys').toBeNull();
  vi.useRealTimers();
  shared['widget_bars'] = { v: 1, rail: { mode: 'pinned' } };
  widgetBars.reload();
  await settle();
  expect(railBtn(MENU_FLYOUT), 'the menu has no key').toBeNull();
  expect(railBtn(SESSION_LIST_WIDGET), 'the icon keys are drawn').not.toBeNull();
  await press(MENU_FLYOUT);
  expect(titleRow(), 'the title row is back').not.toBeNull();
});

test('a pinned rail wears the pin icon last in its column; it toggles pin rail and follows the mode', async () => {
  shared['widget_bars'] = { v: 1, rail: { mode: 'pinned' } };
  widgetBars.reload();
  await railOn();
  const icon = (): HTMLButtonElement | null => shell().querySelector<HTMLButtonElement>('[data-bar-pin]');
  expect(icon()!.getAttribute('aria-label')).toBe('unpin rail');
  expect(icon()!.getAttribute('aria-pressed')).toBe('true');
  click(icon()!);
  await settle();
  expect(widgetBars.rail.mode).toBe('autohide');
  expect(icon(), 'an unpinned rail draws no pin of its own').toBeNull();
});

test('the rail handle draws the same DOM before and after the zone handle (golden, wrapper bar-handle rows)', async () => {
  await railOn();
  matchGolden('handle.rail', shell().querySelector('.sbr-shell__handle'));
});
