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
import { closeRailMenu } from './rail-menu.svelte';
import { railBtn, railOn, setupRail, teardownRail } from './fixtures/rail-harness';

setLocale('en');

const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

const g = globalThis as Record<string, unknown>;
let shared: Record<string, unknown>;

const shell = (): HTMLElement => document.querySelector<HTMLElement>('.sbr-shell')!;
const menuItems = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>('.acm-menu [role^="menuitem"]')];
const labels = (): string[] => menuItems().map((el) => el.querySelector('.acm-label')?.textContent?.trim() ?? el.textContent?.trim() ?? '');

function rightClick(el: Element): boolean {
  const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 12, clientY: 20 });
  el.dispatchEvent(event);
  flushSync();
  return !event.defaultPrevented;
}

const realSeams = { ...editorSeams };

beforeEach(async () => {
  shared = {};
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

afterEach(async () => {
  Object.assign(editorSeams, realSeams);
  closeRailMenu();
  setRailPinnedClass(false);
  delete g.PreferenceBridge;
  widgetBars.reload();
  await teardownRail();
});

test('the builder: pin rail first on the rail itself, edit layout, a hairline, close last and dangerous; a key has no pin', () => {
  const nodes = railMenuNodes({ editing: false, toggleEdit: () => {}, close: { label: 'close tab', run: () => {} }, onClose: () => {} });
  expect(nodes.map((n) => n.id)).toEqual(['edit-layout', 'close-tab']);
  expect(nodes.map((n) => !!n.sep)).toEqual([false, true]);
  expect(nodes[1]!.danger).toBe(true);
  const own = railMenuNodes({ pin: { pinned: false, toggle: () => {} }, editing: false, toggleEdit: () => {}, onClose: () => {} });
  expect(own.map((n) => n.id)).toEqual(['pin-bar', 'edit-layout']);
  expect(own[0]!.label).toBe('pin rail');
  expect(railMenuNodes({ pin: { pinned: true, toggle: () => {} }, editing: false, toggleEdit: null, onClose: () => {} })[0]!.label).toBe('unpin rail');
  const plain = railMenuNodes({ editing: true, toggleEdit: null, onClose: () => {} });
  expect(plain.map((n) => n.id), 'no editor on this page: nothing to offer').toEqual([]);
});

test('a right-click on the rail itself opens the menu and swallows the browser menu', async () => {
  await railOn();
  expect(rightClick(shell()), 'the browser menu is prevented').toBe(false);
  expect(document.querySelector('.acm-menu')).not.toBeNull();
  expect(menuItems().length).toBeGreaterThanOrEqual(1);
  expect(labels()).toContain('pin rail');
});

test('a right-click on a rail key opens the same menu', async () => {
  shared['widget_bars'] = { v: 1, rail: { mode: 'pinned' } };
  widgetBars.reload();
  await railOn();
  rightClick(railBtn(SESSION_LIST_WIDGET));
  expect(document.querySelector('.acm-menu')).not.toBeNull();
  expect(labels().join(' ')).not.toContain('pin');
});

test('a page that cannot edit its layout: the rail itself offers only its pin, and a plain key has nothing, so no empty menu opens (the browser menu is still swallowed)', async () => {
  editorSeams.page = () => null;
  shared['widget_bars'] = { v: 1, rail: { mode: 'pinned' } };
  widgetBars.reload();
  await railOn();
  expect(rightClick(shell())).toBe(false);
  expect(labels()).toEqual(['unpin rail']);
  closeRailMenu();
  flushSync();
  expect(rightClick(railBtn(SESSION_LIST_WIDGET))).toBe(false);
  expect(labels().filter((label) => /pin/.test(label))).toEqual([]);
});

test('a press outside closes it', async () => {
  await railOn();
  rightClick(shell());
  expect(document.querySelector('.acm-menu')).not.toBeNull();
  document.body.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }));
  flushSync();
  expect(document.querySelector('.acm-menu')).toBeNull();
});
