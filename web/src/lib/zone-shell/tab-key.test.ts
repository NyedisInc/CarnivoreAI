/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

vi.mock('../item-settings/store.svelte', () => ({ widgetSetting: () => true, isWidgetDisabled: () => false }));

import TabKey from './TabKey.svelte';
import type { KeyFace } from './zone-types';

let handle: ReturnType<typeof mount> | null = null;
const face: KeyFace = { title: 'files', ariaLabel: 'open files', tip: 'files tip', label: 'files', icon: 'file', count: 4, chip: false, letter: '', tone: 'oc-cyan' };
const key = (): HTMLButtonElement => document.querySelector<HTMLButtonElement>('[data-zone-item]')!;

function draw(props: Record<string, unknown>): void {
  handle = mount(TabKey, {
    target: document.body,
    props: { id: 'k1', variant: 'bar', face, iconPx: 16, state: 'expanded', active: true, tabbable: true, onpress: () => {}, ...props } as never,
  });
  flushSync();
}

afterEach(() => {
  if (handle) unmount(handle);
  handle = null;
  document.body.innerHTML = '';
});

test('an icon key wears the bar look, its words, its badge and its state', () => {
  draw({});
  expect(key().className).toContain('rail__key--open');
  expect(key().getAttribute('aria-label')).toBe('open files');
  expect(key().title).toBe('files tip');
  expect(key().getAttribute('aria-expanded')).toBe('true');
  expect(key().hasAttribute('aria-pressed')).toBe(false);
  expect(key().querySelector('[data-icon="file"]')).not.toBeNull();
  expect(key().querySelector('[data-rail-badge]')!.textContent).toBe('4');
  expect(key().hasAttribute('tabindex')).toBe(false);
  expect(key().hasAttribute('role'), 'an icon key stays a plain button').toBe(false);
});

test('pressed and selected states, a quiet key and a key that is not the Tab stop', () => {
  draw({ state: 'pressed', active: false, quiet: true, tabbable: false });
  expect(key().getAttribute('aria-pressed')).toBe('false');
  expect(key().hasAttribute('aria-expanded')).toBe(false);
  expect(key().querySelector('[data-rail-badge]'), 'quiet draws no badge').toBeNull();
  expect(key().getAttribute('tabindex')).toBe('-1');
  unmount(handle!);
  draw({ state: 'selected' });
  expect(key().getAttribute('aria-selected')).toBe('true');
  expect(key().getAttribute('role'), 'a selected-state key is a tab').toBe('tab');
  unmount(handle!);
  draw({ state: null });
  expect(['aria-expanded', 'aria-pressed', 'aria-selected'].some((one) => key().hasAttribute(one))).toBe(false);
});

test('a tab shows its name between lead and tail; a tile draws its body', () => {
  const lead = createRawSnippet(() => ({ render: () => '<i data-lead></i>' }));
  const tail = createRawSnippet(() => ({ render: () => '<i data-tail></i>' }));
  draw({ shape: 'tab', lead, tail });
  expect(key().textContent).toContain('files');
  expect(key().querySelector('[data-icon]')).toBeNull();
  expect(key().firstElementChild!.hasAttribute('data-lead')).toBe(true);
  expect(key().querySelector('[data-tail]')).not.toBeNull();
  unmount(handle!);
  draw({ shape: 'tile', body: createRawSnippet(() => ({ render: () => '<b data-tile-body>3 open</b>' })) });
  expect(key().querySelector('[data-tile-body]')!.textContent).toBe('3 open');
  expect(key().querySelector('[data-icon]')).toBeNull();
});

test('right-click, the menu key and Shift+F10 open the one menu; other keys go to the strip; press, focus and drag report the id', () => {
  const menus: string[] = [];
  const keys: string[] = [];
  const seen: string[] = [];
  draw({
    onmenu: (id: string, anchor: HTMLElement) => menus.push(`${id}:${anchor.tagName}`),
    onkey: (event: KeyboardEvent, id: string) => keys.push(`${id}:${event.key}`),
    onpress: (id: string) => seen.push(`press:${id}`),
    onfocus: (id: string) => seen.push(`focus:${id}`),
    ondragstart: (_event: PointerEvent, id: string) => seen.push(`drag:${id}`),
  });
  const click = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
  key().dispatchEvent(click);
  key().dispatchEvent(new KeyboardEvent('keydown', { key: 'ContextMenu', bubbles: true, cancelable: true }));
  key().dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true }));
  key().dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
  key().click();
  key().focus();
  key().dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
  expect(click.defaultPrevented).toBe(true);
  expect(menus).toEqual(['k1:BUTTON', 'k1:BUTTON', 'k1:BUTTON']);
  expect(keys).toEqual(['k1:ArrowDown']);
  expect(seen).toEqual(['press:k1', 'focus:k1', 'drag:k1']);
});

test('a key with no menu of its own leaves the right-click and the menu key to the layout', () => {
  const keys: string[] = [];
  draw({ onkey: (event: KeyboardEvent) => keys.push(event.key) });
  const click = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
  const menuKey = new KeyboardEvent('keydown', { key: 'ContextMenu', bubbles: true, cancelable: true });
  key().dispatchEvent(click);
  key().dispatchEvent(menuKey);
  expect(click.defaultPrevented).toBe(false);
  expect(menuKey.defaultPrevented).toBe(false);
  expect(keys, 'a menu key is never the strip\'s arrows').toEqual([]);
});
