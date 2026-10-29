/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import PopupProbe from './fixtures/PopupProbe.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();

let app: ReturnType<typeof mount> | null = null;
let anchor: HTMLButtonElement;

beforeEach(() => {
  Object.assign(window, { innerWidth: 1200, innerHeight: 800 });
  anchor = document.createElement('button');
  anchor.textContent = 'open';
  document.body.append(anchor);
  anchor.focus();
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.replaceChildren();
});

function open(props: Record<string, unknown> = {}): HTMLElement {
  app = mount(PopupProbe, { target: document.body, props: { anchor, ...props } });
  flushSync();
  return document.querySelector<HTMLElement>('[data-probe]')!;
}

function anchorAt(top: number, bottom: number): void {
  anchor.getBoundingClientRect = () => ({ top, bottom, left: 40, right: 140, width: 100, height: bottom - top, x: 40, y: top, toJSON: () => ({}) });
}

test('the frame carries the role, the name, the shared look and the caller\'s classes and attributes', () => {
  const pop = open({ class: 'my-pop', role: 'alertdialog' });
  expect(pop.getAttribute('role')).toBe('alertdialog');
  expect(pop.getAttribute('aria-label')).toBe('probe');
  expect([...pop.classList]).toEqual(expect.arrayContaining(['oc-anchored', 'popup-focus', 'my-pop']));
  expect(pop.hasAttribute('popover')).toBe(false);
});

test('below places it under the anchor, and flips above when the room is below the anchor is short', () => {
  anchorAt(100, 130);
  expect(open().getAttribute('style')).toContain('top: 134px');
  unmount(app!);
  anchorAt(700, 730);
  expect(open().getAttribute('style')).toContain('bottom: 104px');
});

test('manual takes the caller\'s style and asks the caller to place on open and on a resize', () => {
  const onPlace = vi.fn();
  const pop = open({ placement: 'manual', style: 'left: 5px; top: 6px;', onPlace });
  expect(pop.getAttribute('style')).toBe('left: 5px; top: 6px;');
  expect(onPlace).toHaveBeenCalledTimes(1);
  window.dispatchEvent(new Event('resize'));
  expect(onPlace).toHaveBeenCalledTimes(2);
});

test('focus goes to the first control, or the named one, and back to the anchor on close', () => {
  open();
  expect(document.activeElement?.hasAttribute('data-first')).toBe(true);
  unmount(app!);
  app = null;
  expect(document.activeElement).toBe(anchor);
  open({ initialFocus: '[data-second]' });
  expect(document.activeElement?.hasAttribute('data-second')).toBe(true);
});

test('Escape closes and stops at the popup; onEscape replaces it; a closed guard keeps the popup up and still takes the key', () => {
  const onClose = vi.fn();
  const below = vi.fn();
  document.addEventListener('keydown', below);
  const pop = open({ onClose });
  pop.querySelector('button')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(below, 'the page under the popup never sees the key').not.toHaveBeenCalled();
  unmount(app!);
  const onEscape = vi.fn();
  open({ onClose, onEscape }).dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  expect(onEscape).toHaveBeenCalledTimes(1);
  expect(onClose).toHaveBeenCalledTimes(1);
  unmount(app!);
  open({ onClose, dismissable: () => false }).dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(below).not.toHaveBeenCalled();
  document.removeEventListener('keydown', below);
});

test('escape on the document hears the key from anywhere and leaves it to the target', () => {
  const onClose = vi.fn();
  open({ onClose, escape: 'document' });
  const field = document.createElement('select');
  document.body.append(field);
  const seen = vi.fn();
  field.addEventListener('keydown', seen);
  field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(seen).toHaveBeenCalledTimes(1);
});

test('a press outside closes; a press inside or on the anchor does not; outside none ignores it', () => {
  const onClose = vi.fn();
  const pop = open({ onClose });
  pop.querySelector('button')!.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  anchor.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  expect(onClose).not.toHaveBeenCalled();
  document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  expect(onClose).toHaveBeenCalledTimes(1);
  unmount(app!);
  open({ onClose, outside: 'none' });
  document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  expect(onClose).toHaveBeenCalledTimes(1);
});

test('topLayer promotes it with popover="manual"', () => {
  const show = vi.spyOn(window.HTMLElement.prototype, 'showPopover');
  const pop = open({ topLayer: true });
  expect(pop.getAttribute('popover')).toBe('manual');
  expect(show.mock.contexts).toContain(pop);
  show.mockRestore();
});

test('the caller\'s own key handler hears every key but the Escape the frame took', () => {
  const onkeydown = vi.fn();
  const onClose = vi.fn();
  const pop = open({ onkeydown, onClose });
  pop.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  pop.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  expect(onkeydown.mock.calls.map(([event]) => (event as KeyboardEvent).key)).toEqual(['Enter']);
  expect(onClose).toHaveBeenCalledTimes(1);
});
