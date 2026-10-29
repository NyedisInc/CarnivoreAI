/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import MediaLightbox from './MediaLightbox.svelte';
import { clampRect, loadRect, stepRect, STORAGE_KEY, MIN_W } from './lightbox-geometry';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');
const VP = { w: 1000, h: 800 };
let comp: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  localStorage.clear();
  Object.assign(window, { innerWidth: VP.w, innerHeight: VP.h });
});
afterEach(() => {
  if (comp) unmount(comp);
  comp = null;
  document.body.innerHTML = '';
});

function open(): HTMLElement {
  comp = mount(MediaLightbox, { target: document.body, props: { src: 'blob:x', alt: 'a', caption: 'shot.png', onClose: vi.fn() } });
  flushSync();
  return document.querySelector('.sidebar-help__lightbox-body') as HTMLElement;
}
const px = (el: HTMLElement, p: 'left' | 'top' | 'width' | 'height') => parseInt(el.style[p], 10);

function pointer(type: string, target: Element, x: number, y: number): void {
  const ev = new MouseEvent(type, { clientX: x, clientY: y, button: 0, bubbles: true }) as MouseEvent & { pointerId: number };
  Object.defineProperty(ev, 'pointerId', { value: 1 });
  target.dispatchEvent(ev);
}

test('dragging the title strip moves the window and remembers it', () => {
  const body = open();
  const x0 = px(body, 'left'), y0 = px(body, 'top');
  const bar = body.querySelector('.sidebar-help__lightbox-bar') as HTMLElement;
  pointer('pointerdown', bar, 100, 100);
  pointer('pointermove', bar, 130, 90);
  flushSync();
  expect(px(body, 'left')).toBe(x0 + 30);
  expect(px(body, 'top')).toBe(y0 - 10);
  pointer('pointerup', bar, 130, 90);
  flushSync();
  expect(loadRect()?.x).toBe(x0 + 30);
});

test('the corner grip resizes and the window never leaves the screen', () => {
  const body = open();
  const w0 = px(body, 'width');
  const grip = body.querySelector('.sidebar-help__lightbox-grip') as HTMLElement;
  pointer('pointerdown', grip, 500, 500);
  pointer('pointermove', grip, 540, 530);
  flushSync();
  expect(px(body, 'width')).toBe(Math.min(w0 + 40, VP.w - px(body, 'left')));
  pointer('pointermove', grip, 5000, 5000);
  flushSync();
  expect(px(body, 'left') + px(body, 'width')).toBeLessThanOrEqual(VP.w);
  expect(px(body, 'top') + px(body, 'height')).toBeLessThanOrEqual(VP.h);
  pointer('pointerup', grip, 5000, 5000);
});

test('arrows move and shift+arrows resize, and the size is restored on the next open', () => {
  let body = open();
  const x0 = px(body, 'left'), h0 = px(body, 'height');
  body.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
  body.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', shiftKey: true, bubbles: true }));
  flushSync();
  expect(px(body, 'left')).toBe(x0 - 20);
  expect(px(body, 'height')).toBe(h0 - 20);
  unmount(comp!);
  comp = null;
  document.body.innerHTML = '';
  body = open();
  expect(px(body, 'left')).toBe(x0 - 20);
  expect(px(body, 'height')).toBe(h0 - 20);
});

test('geometry clamps a stale or oversized rectangle and survives blocked storage', () => {
  expect(clampRect({ x: -50, y: 900, w: 9999, h: 10 }, VP)).toEqual({ x: 0, y: 640, w: VP.w, h: 160 });
  expect(stepRect({ x: 0, y: 0, w: MIN_W, h: 300 }, 'ArrowLeft', true, VP)?.w).toBe(MIN_W);
  expect(stepRect({ x: 0, y: 0, w: 300, h: 300 }, 'a', false, VP)).toBeNull();
  localStorage.setItem(STORAGE_KEY, '{not json');
  expect(loadRect()).toBeNull();
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
  expect(loadRect()).toBeNull();
  vi.restoreAllMocks();
});
