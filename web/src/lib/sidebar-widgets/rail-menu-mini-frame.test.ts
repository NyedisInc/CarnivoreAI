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
import { editorSeams } from '../../opscenter/layout-editor/editor.svelte';
import { setRailPinnedClass } from './rail-dom';
import { setLocale } from '../i18n/index.svelte';
import { SESSION_LIST_WIDGET } from './widget-ids';
import { railMenuNodes } from '../widget-menu/rail-menu';
import { mount, unmount } from 'svelte';
import MiniRail from '../mini-rail/MiniRail.svelte';
import { closeRailMenu } from './rail-menu.svelte';
import { railBtn, railOn, setupRail, teardownRail } from './fixtures/rail-harness';
import { registerSwarmFlyout } from '../../cplugs/huddle/swarm-flyout';

// The swarm slide-out is the Task Manager plugin's, so the test registers it; the harness no longer does.
registerSwarmFlyout();

setLocale('en');

// jsdom has no popover API; the cascade menu shows its levels through it.
const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

const g = globalThis as Record<string, unknown>;
let shared: Record<string, unknown>;

const shell = (): HTMLElement => document.querySelector<HTMLElement>('.sbr-shell')!;
const menuItems = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>('.acm-menu [role^="menuitem"]')];
const labels = (): string[] => menuItems().map((el) => el.querySelector('.acm-label')?.textContent?.trim() ?? el.textContent?.trim() ?? '');

/** Dispatch a contextmenu event on an element; returns whether the default (the browser's menu) was left alone. */
function rightClick(el: Element): boolean {
  const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 12, clientY: 20 });
  el.dispatchEvent(event);
  flushSync();
  return !event.defaultPrevented;
}

const realSeams = { ...editorSeams };

beforeEach(async () => {
  shared = {};
  // A page whose layout can be edited, so the menu has its edit layout item.
  editorSeams.wide = () => true;
  editorSeams.page = () => ({}) as never;
  editorSeams.store = () => ({}) as never;
  await setupRail();
  g.PreferenceBridge = {
    read: (field: string, fallback: () => unknown) => (field in shared ? shared[field] : fallback()),
    write: async (field: string, value: unknown, local: () => void) => { shared[field] = value; local(); return { status: 'committed' }; },
    follow: () => () => {},
  };
  widgetBars.reload();
});

let frame: Record<string, unknown> | null = null;

afterEach(async () => {
  if (frame) await unmount(frame);
  frame = null;
  Object.assign(editorSeams, realSeams);
  closeRailMenu();
  setRailPinnedClass(false);
  delete g.PreferenceBridge;
  widgetBars.reload();
  await teardownRail();
});

test('one right-click on the pinned rail leaves exactly one menu open, with edit layout', async () => {
  shared['widget_bars'] = { v: 1, rail: { mode: 'pinned' } };
  widgetBars.reload();
  await railOn();
  rightClick(shell());
  expect(document.querySelectorAll('.acm-menu').length).toBe(1);
  expect(labels()).toContain('edit layout');
});

test('a right-click on a pinned rail key leaves one menu open too', async () => {
  shared['widget_bars'] = { v: 1, rail: { mode: 'pinned' } };
  widgetBars.reload();
  await railOn();
  rightClick(railBtn(SESSION_LIST_WIDGET));
  expect(document.querySelectorAll('.acm-menu').length).toBe(1);
  expect(labels()).toContain('edit layout');
});

test('the pinned rail (drawer open) draws no footer, no meters and no account chip: those are the closed rail\'s', async () => {
  shared['widget_bars'] = { v: 1, rail: { mode: 'pinned' } };
  widgetBars.reload();
  await railOn();
  const nav = document.querySelector('.sbr-rail')!;
  expect(nav).not.toBeNull();
  expect(nav.querySelector('.mr-usage')).toBeNull();
  expect(nav.querySelector('.mr-footer')).toBeNull();
});
