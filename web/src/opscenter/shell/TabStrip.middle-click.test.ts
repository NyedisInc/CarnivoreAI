/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TabStrip, { type TabItem } from './TabStrip.svelte';

const ITEMS: TabItem[] = [
  { id: 'terminal:a', name: 'a', family: null },
  { id: 'terminal:b', name: 'b', family: null },
];

let app: ReturnType<typeof mount> | null = null;
const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

function draw(onClose?: (id: string) => void): (id: string) => HTMLElement {
  const target = document.body.appendChild(document.createElement('div'));
  app = mount(TabStrip, { target, props: { items: ITEMS, active: 'terminal:a', onSelect: () => {}, onClose } });
  flushSync();
  return (id) => target.querySelector<HTMLElement>(`[data-tab="${id}"]`)!;
}

const middle = (type: string): MouseEvent => new MouseEvent(type, { button: 1, bubbles: true, cancelable: true });

test('a middle click opens the confirm with ok focused; ok closes that tab', async () => {
  const onClose = vi.fn();
  const tab = draw(onClose);
  const press = middle('mousedown');
  tab('terminal:b').dispatchEvent(press);
  expect(press.defaultPrevented).toBe(true);
  tab('terminal:b').dispatchEvent(middle('auxclick'));
  await flush();
  const ok = document.querySelector<HTMLButtonElement>('[data-confirm-ok-go]')!;
  expect(document.activeElement).toBe(ok);
  expect(onClose).not.toHaveBeenCalled();
  ok.click();
  await flush();
  expect(onClose).toHaveBeenCalledWith('terminal:b');
});

test('Escape cancels and closes nothing', async () => {
  const onClose = vi.fn();
  draw(onClose)('terminal:a').dispatchEvent(middle('auxclick'));
  await flush();
  document.querySelector('.modal-overlay')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await flush();
  expect(onClose).not.toHaveBeenCalled();
  expect(document.querySelector('.modal-overlay')).toBeNull();
});

test('a strip with no close action ignores the middle click', async () => {
  draw()('terminal:a').dispatchEvent(middle('auxclick'));
  await flush();
  expect(document.querySelector('.modal-overlay')).toBeNull();
});
