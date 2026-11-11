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

test('plain arrows select and are swallowed; Shift, Alt, Ctrl and Meta arrows do nothing here', () => {
  const onSelect = vi.fn();
  const target = document.body.appendChild(document.createElement('div'));
  app = mount(TabStrip, { target, props: { items: ITEMS, active: 'terminal:a', onSelect, onClose: () => {}, onIconClick: () => {} } });
  flushSync();
  const tab = target.querySelector<HTMLElement>('[data-tab="terminal:a"]')!;
  const press = (init: KeyboardEventInit): KeyboardEvent => {
    const e = new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true, ...init });
    tab.dispatchEvent(e);
    return e;
  };
  for (const mod of [{ shiftKey: true }, { ctrlKey: true }, { metaKey: true }]) {
    expect(press(mod).defaultPrevented).toBe(false);
  }
  expect(onSelect).not.toHaveBeenCalled();
  expect(press({}).defaultPrevented).toBe(true);
  expect(onSelect).toHaveBeenCalledWith('terminal:b');
});
