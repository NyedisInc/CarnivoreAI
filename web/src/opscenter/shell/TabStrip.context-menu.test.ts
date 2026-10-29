/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TabStrip, { type TabItem } from './TabStrip.svelte';

const ITEMS: TabItem[] = [
  { id: 'terminal:a', name: 'a', family: null },
  { id: 'terminal:b', name: 'b', family: null },
];

let app: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

function draw(onTabMenu: (id: string, anchor: HTMLElement, point: { x: number; y: number } | null) => boolean): HTMLElement {
  const target = document.body.appendChild(document.createElement('div'));
  app = mount(TabStrip, { target, props: { items: ITEMS, active: 'terminal:a', onSelect: () => {}, onClose: () => {}, onIconClick: () => {}, onTabMenu } });
  flushSync();
  return target;
}

const tabOf = (root: HTMLElement, id: string): HTMLElement => root.querySelector<HTMLElement>(`[data-tab="${id}"]`)!;
const rightClick = (x = 120, y = 14): MouseEvent => new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: x, clientY: y });

test('a right click on a tab opens that tab\'s menu at the pointer and swallows the browser menu', () => {
  const onTabMenu = vi.fn(() => true);
  const root = draw(onTabMenu);
  const event = rightClick(340, 18);
  tabOf(root, 'terminal:b').dispatchEvent(event);
  expect(onTabMenu).toHaveBeenCalledWith('terminal:b', tabOf(root, 'terminal:b'), { x: 340, y: 18 });
  expect(event.defaultPrevented).toBe(true);
});

test('a tab with nothing to act on leaves the browser menu alone', () => {
  const root = draw(() => false);
  const event = rightClick();
  tabOf(root, 'terminal:a').dispatchEvent(event);
  expect(event.defaultPrevented).toBe(false);
});

test('the icon and the "x" keep their own right click', () => {
  const onTabMenu = vi.fn(() => true);
  const root = draw(onTabMenu);
  root.querySelector('.oc-tab-icon--action')!.dispatchEvent(rightClick());
  root.querySelector('.oc-tab-x')!.dispatchEvent(rightClick());
  expect(onTabMenu).not.toHaveBeenCalled();
});

test('the Menu key and Shift+F10 on a focused tab open its menu beneath the tab (no point)', () => {
  const onTabMenu = vi.fn(() => true);
  const root = draw(onTabMenu);
  const tab = tabOf(root, 'terminal:a');
  const menuKey = new KeyboardEvent('keydown', { key: 'ContextMenu', bubbles: true, cancelable: true });
  tab.dispatchEvent(menuKey);
  const shiftF10 = new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true });
  tab.dispatchEvent(shiftF10);
  expect(onTabMenu).toHaveBeenCalledTimes(2);
  expect(onTabMenu).toHaveBeenNthCalledWith(1, 'terminal:a', tab, null);
  expect(menuKey.defaultPrevented && shiftF10.defaultPrevented).toBe(true);
});

test('a plain F10 is not ours', () => {
  const onTabMenu = vi.fn(() => true);
  const root = draw(onTabMenu);
  tabOf(root, 'terminal:a').dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', bubbles: true, cancelable: true }));
  expect(onTabMenu).not.toHaveBeenCalled();
});
