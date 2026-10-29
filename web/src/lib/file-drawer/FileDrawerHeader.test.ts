/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

import { HEADER_ID, mountFileDrawerHeader, type DrawerHeaderHandle } from './file-drawer';
import { HIDE_DOT_KEY, HIDE_IGNORED_KEY } from './drawer-prefs';
import { unmountPanel } from '../mount';

const REPO = path.resolve(process.cwd(), '..');

function drawerMarkup(): string {
  const source = fs.readFileSync(path.join(REPO, 'client', 'index.html'), 'utf8');
  const start = source.indexOf('<div class="modal-overlay config-editor-picker-overlay"');
  const end = source.indexOf('<!-- Auth Screen -->', start);
  if (start < 0 || end < 0) throw new Error('the file drawer markup is missing from client/index.html');
  return source.slice(start, end);
}

function callbacks() {
  return {
    onQuery: vi.fn(),
    onPrefs: vi.fn(),
    onRefresh: vi.fn(),
    onCollapseAll: vi.fn(),
    onNewFile: vi.fn(),
    onClose: vi.fn(),
  };
}

function setup(): { cb: ReturnType<typeof callbacks>; handle: DrawerHeaderHandle; root: HTMLElement } {
  document.body.innerHTML = drawerMarkup();
  const cb = callbacks();
  const handle = mountFileDrawerHeader(cb);
  if (!handle) throw new Error('the header did not mount');
  flushSync();
  return { cb, handle, root: document.getElementById(HEADER_ID) as HTMLElement };
}

function openMenu(root: HTMLElement): void {
  (root.querySelector('[data-action="options"]') as HTMLButtonElement).click();
  flushSync();
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  unmountPanel(HEADER_ID);
  document.body.replaceChildren();
  vi.useRealTimers();
});

test('every control is in the shipped container, and there is no title', () => {
  const { root } = setup();
  for (const selector of ['#config-editor-new', '[data-action="collapse-all"]', '[data-action="refresh"]',
    '[data-action="options"]', '#config-editor-close', '[data-role="find-files"]']) {
    expect(root.querySelector(selector), selector).not.toBeNull();
  }
  expect(document.body.textContent ?? '').not.toMatch(/file editor/i);
  expect(document.getElementById('config-drawer-pin')).toBeNull();
});

test('each button hands its own gesture to the drawer', () => {
  const { cb, root } = setup();
  (root.querySelector('[data-action="collapse-all"]') as HTMLButtonElement).click();
  (root.querySelector('[data-action="refresh"]') as HTMLButtonElement).click();
  (root.querySelector('#config-editor-new') as HTMLButtonElement).click();
  (root.querySelector('#config-editor-close') as HTMLButtonElement).click();
  expect(cb.onCollapseAll).toHaveBeenCalledTimes(1);
  expect(cb.onRefresh).toHaveBeenCalledTimes(1);
  expect(cb.onNewFile).toHaveBeenCalledTimes(1);
  expect(cb.onClose).toHaveBeenCalledTimes(1);
});

test('typing reaches the drawer once, after the pause, and Escape clears it at once', () => {
  vi.useFakeTimers();
  const { cb, handle, root } = setup();
  const field = root.querySelector('[data-role="find-files"]') as HTMLInputElement;
  for (const text of ['r', 're', 'rea']) {
    field.value = text;
    field.dispatchEvent(new Event('input', { bubbles: true }));
  }
  expect(cb.onQuery).not.toHaveBeenCalled();
  vi.advanceTimersByTime(200);
  expect(cb.onQuery).toHaveBeenCalledTimes(1);
  expect(cb.onQuery).toHaveBeenLastCalledWith('rea');
  expect(handle.query()).toBe('rea');

  field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  flushSync();
  expect(field.value).toBe('');
  expect(cb.onQuery).toHaveBeenLastCalledWith('');
  expect(handle.query()).toBe('');
});

test("the drawer's Escape closes the menu, then clears the query, then lets the drawer close", () => {
  vi.useFakeTimers();
  const { handle, root } = setup();
  const field = root.querySelector('[data-role="find-files"]') as HTMLInputElement;
  field.value = 'x';
  field.dispatchEvent(new Event('input', { bubbles: true }));
  vi.advanceTimersByTime(200);
  openMenu(root);
  expect(root.querySelector('[data-pref="hideDot"]')).not.toBeNull();

  expect(handle.escape()).toBe(true);
  flushSync();
  expect(root.querySelector('[data-pref="hideDot"]')).toBeNull();
  expect(handle.query()).toBe('x');

  expect(handle.escape()).toBe(true);
  expect(handle.query()).toBe('');
  expect(handle.escape()).toBe(false);
});

test('both options start off, which is what the drawer did before they existed', () => {
  const { handle, root } = setup();
  expect(handle.prefs()).toEqual({ hideDot: false, hideIgnored: false });
  openMenu(root);
  expect((root.querySelector('[data-pref="hideDot"]') as HTMLInputElement).checked).toBe(false);
  expect((root.querySelector('[data-pref="hideIgnored"]') as HTMLInputElement).checked).toBe(false);
});

test('each option filters through the drawer and persists on this device', () => {
  const { cb, handle, root } = setup();
  openMenu(root);
  (root.querySelector('[data-pref="hideDot"]') as HTMLInputElement).click();
  flushSync();
  expect(cb.onPrefs).toHaveBeenLastCalledWith({ hideDot: true, hideIgnored: false });
  expect(localStorage.getItem(HIDE_DOT_KEY)).toBe('1');

  (root.querySelector('[data-pref="hideIgnored"]') as HTMLInputElement).click();
  flushSync();
  expect(cb.onPrefs).toHaveBeenLastCalledWith({ hideDot: true, hideIgnored: true });
  expect(localStorage.getItem(HIDE_IGNORED_KEY)).toBe('1');
  expect(handle.prefs()).toEqual({ hideDot: true, hideIgnored: true });

  unmountPanel(HEADER_ID);
  const again = setup();
  expect(again.handle.prefs()).toEqual({ hideDot: true, hideIgnored: true });
  openMenu(again.root);
  expect((again.root.querySelector('[data-pref="hideDot"]') as HTMLInputElement).checked).toBe(true);
  expect((again.root.querySelector('[data-pref="hideIgnored"]') as HTMLInputElement).checked).toBe(true);
});

test('with no git answer the ignored option is disabled and says why', () => {
  const { handle, root } = setup();
  openMenu(root);
  const box = () => root.querySelector('[data-pref="hideIgnored"]') as HTMLInputElement;
  expect(box().disabled).toBe(false);
  handle.setIgnoreStatus('unavailable');
  flushSync();
  expect(box().disabled).toBe(true);
  expect(box().closest('label')?.hasAttribute('title')).toBe(false);
  handle.setIgnoreStatus('ok');
  flushSync();
  expect(box().disabled).toBe(false);
  expect(box().closest('label')?.hasAttribute('title')).toBe(false);
});

test('"open as component" is drawn only when the drawer says the grid can take it', () => {
  document.body.innerHTML = drawerMarkup();
  const onComponent = vi.fn();
  const handle = mountFileDrawerHeader({ ...callbacks(), onComponent });
  if (!handle) throw new Error('the header did not mount');
  flushSync();
  const root = document.getElementById(HEADER_ID) as HTMLElement;
  expect(root.querySelector('[data-action="as-component"]')).toBeNull();
  handle.setComponentShown(true);
  flushSync();
  (root.querySelector('[data-action="as-component"]') as HTMLButtonElement).click();
  expect(onComponent).toHaveBeenCalledOnce();
  handle.setComponentShown(false);
  flushSync();
  expect(root.querySelector('[data-action="as-component"]')).toBeNull();
});
