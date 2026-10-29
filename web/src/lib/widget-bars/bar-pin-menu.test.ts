/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, sessions: { data: [] }, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));
vi.mock('../../opscenter/cells/registry', async (importOriginal) => {
  const { ScopeProbe } = await import('../session-rail/test-support.svelte');
  return { ...(await importOriginal<Record<string, unknown>>()), entryFor: () => ({ component: ScopeProbe }) };
});

import { RAIL_FIELD, RAIL_SPECS } from '../session-rail/rail-model';
import { railOutSizes } from '../session-rail/rail-out-size.svelte';
import { railSlideout } from '../session-rail/slideout.svelte';
import { AUTOHIDE_BARS, BOTTOM_FIELD, follow, keyIn, mountRails, unmountRails } from '../session-rail/rail-test-harness';
import { emptyMenu, emptyMenuNodes } from '../../opscenter/layout-editor/empty-space-menu.svelte';
import { railMenu, railMenuItems } from '../sidebar-widgets/rail-menu.svelte';
import { barLead } from './bar-lead.svelte';
import { widgetBars } from './bar-settings.svelte';
import { offerStripPins } from './bar-pin-action';

// jsdom has no popover API; the cascade menu shows its levels through it.
const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

const nav = (): HTMLElement => document.getElementById(RAIL_SPECS.side.id)!;
const stateOf = (): string | undefined => nav().dataset['barState'];
const handle = (): HTMLElement => nav().querySelector<HTMLElement>('[data-bar-handle]')!;
const mouse = (type: string): Event => Object.assign(new MouseEvent(type), { pointerType: 'mouse' });
const enter = (): void => { nav().dispatchEvent(mouse('pointerenter')); flushSync(); };
const leave = (): void => { nav().dispatchEvent(mouse('pointerleave')); flushSync(); };
const advance = (ms: number): void => { vi.advanceTimersByTime(ms); flushSync(); };
/** A mouse click (detail 1: a click with no detail is the keyboard's). */
const click = (el: HTMLElement): void => { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 })); flushSync(); };
const rightClick = (el: HTMLElement): void => { el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true })); flushSync(); };
const menuIds = (): (string | undefined)[] => [...document.querySelectorAll<HTMLElement>('.acm-item')].map((el) => el.dataset['node']);

beforeEach(() => {
  vi.useFakeTimers();
  mountRails();
  localStorage.clear();
  railSlideout.reload();
  railOutSizes.reload();
  barLead.edge = null;
  follow('widget_bars', null);
  follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.changes' }, { widget: 'core.files' }] });
  follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.task-manager' }] });
  vi.spyOn(widgetBars, 'set').mockImplementation(async (edge, patch) => {
    follow('widget_bars', { ...AUTOHIDE_BARS, [edge]: { mode: 'autohide', ...patch } });
    return 'committed';
  });
});
afterEach(() => {
  emptyMenu.at = null;
  railMenu.at = null;
  railMenu.keyId = null;
  unmountRails();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test('right-click the bar strip, pin bar: the bar stays out after the pointer leaves; unpin bar: it hides again', async () => {
  rightClick(handle());
  expect(emptyMenu.target).toBe('side');
  const pin = emptyMenuNodes().find((n) => n.id === 'pin-bar');
  expect(pin?.label).toBe('pin bar');
  pin!.run!();
  await vi.waitFor(() => expect(widgetBars.view.side.mode).toBe('pinned'));
  flushSync();
  expect(stateOf()).toBe('pinned');
  enter();
  leave();
  advance(5000);
  expect(stateOf()).toBe('pinned');
  expect(nav().querySelector('[data-bar-pin]')?.getAttribute('aria-pressed'), 'the icon follows the menu').toBe('true');

  rightClick(nav());
  const unpin = emptyMenuNodes().find((n) => n.id === 'pin-bar');
  expect(unpin?.label).toBe('unpin bar');
  unpin!.run!();
  await vi.waitFor(() => expect(widgetBars.view.side.mode).toBe('autohide'));
  flushSync();
  expect(stateOf()).toBe('handle');
});

test('unpinned, a hover or a click on the handle puts the bar out and it hides about 300 ms after the pointer leaves', () => {
  expect(stateOf()).toBe('handle');
  enter();
  expect(stateOf(), 'a hover opens it').toBe('peek');
  click(handle());
  expect(stateOf(), 'a mouse click on the handle keeps it out').toBe('peek');
  expect(widgetBars.set).not.toHaveBeenCalled();
  leave();
  advance(299);
  expect(stateOf()).toBe('peek');
  advance(1);
  expect(stateOf()).toBe('handle');
});

test('Shift+F10 on the bar handle opens the strip menu with the pin', () => {
  handle().dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true }));
  flushSync();
  expect(emptyMenu.at).not.toBeNull();
  expect(emptyMenu.target).toBe('side');
  expect(emptyMenuNodes().map((n) => n.id)).toContain('pin-bar');
});

test('no icon menu offers a pin: a bar key, a rail key; the sidebar rail itself offers pin rail', () => {
  rightClick(keyIn('side', 'core.files'));
  expect(menuIds().length).toBeGreaterThan(0);
  expect(menuIds().filter((id) => /pin/.test(id ?? ''))).toEqual([]);

  railMenu.keyId = 'core.files';
  expect(railMenuItems().some((n) => /pin/.test(n.id))).toBe(false);
  railMenu.keyId = null;
  expect(railMenuItems().find((n) => n.id === 'pin-bar')?.label).toBe('pin rail');
});

const navOf = (edge: 'side' | 'bottom'): HTMLElement => document.getElementById(RAIL_SPECS[edge].id)!;

test('the pin icon is on the right and bottom bars while they are out, toggles the same pin, and follows it (Joe, 2026-10-20, item 1041)', async () => {
  for (const edge of ['side', 'bottom'] as const) {
    expect(navOf(edge).querySelector('[data-bar-pin]'), `${edge} closed: no icon`).toBeNull();
    click(navOf(edge).querySelector<HTMLElement>('[data-bar-handle]')!);
    const pin = navOf(edge).querySelector<HTMLButtonElement>('[data-bar-pin]')!;
    expect(pin, `${edge} out: the icon is drawn`).not.toBeNull();
    expect(pin.closest('.rail__pin'), 'in the end slot').not.toBeNull();
    expect(pin.getAttribute('aria-label')).toBe('pin bar');
    expect(pin.getAttribute('aria-pressed')).toBe('false');
    click(pin);
    await vi.waitFor(() => expect(widgetBars.view[edge].mode).toBe('pinned'));
    flushSync();
    expect(navOf(edge).querySelector('[data-bar-pin]')!.getAttribute('aria-pressed')).toBe('true');
    expect(navOf(edge).querySelector('[data-bar-pin]')!.getAttribute('aria-label')).toBe('unpin bar');
    click(navOf(edge).querySelector<HTMLElement>('[data-bar-pin]')!);
    await vi.waitFor(() => expect(widgetBars.view[edge].mode).toBe('autohide'));
    flushSync();
  }
});

test('on a host with no pins (the Widget Lab) the icon is not drawn', () => {
  offerStripPins(false);
  try {
    click(handle());
    expect(stateOf()).toBe('peek');
    expect(nav().querySelector('[data-bar-pin]')).toBeNull();
  } finally {
    offerStripPins(true);
  }
});
