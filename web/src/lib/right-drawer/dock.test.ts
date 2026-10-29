/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import {
  BODY_CLASS,
  DEFAULT_WIDTH,
  MAX_WIDTH,
  MIN_WIDTH,
  WIDTH_KEY,
  WIDTH_VAR,
  clampWidth,
  closeDrawer,
  dismissDrawer,
  installGrip,
  openDrawer,
  readWidth,
  registerOccupant,
  resetRightDrawerForTest,
  rightDrawer,
  setDrawerWidth,
} from './dock.svelte';

let requestFit: ReturnType<typeof vi.fn>;

function viewport(width: number): void {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
}

function occupant(kind: 'files' | 'notes') {
  const el = document.createElement('div');
  document.body.appendChild(el);
  const close = vi.fn(() => closeDrawer(kind));
  registerOccupant(kind, { root: el, box: el, close });
  return { el, close };
}

beforeEach(() => {
  resetRightDrawerForTest();
  localStorage.clear();
  document.body.className = '';
  document.body.innerHTML = '';
  viewport(1400);
  requestFit = vi.fn();
  (window as unknown as { TerminalLayout: unknown }).TerminalLayout = { requestFit };
});

afterEach(() => {
  delete (window as unknown as { TerminalLayout?: unknown }).TerminalLayout;
  vi.restoreAllMocks();
});

test('the width is clamped to the floor, the pixel cap and the share of the viewport', () => {
  expect(clampWidth(10, 1400)).toBe(MIN_WIDTH);
  expect(clampWidth(5000, 4000)).toBe(MAX_WIDTH);
  expect(clampWidth(700, 800)).toBe(480);
  expect(clampWidth(500, 0)).toBe(500);
  expect(clampWidth(Number.NaN, 1400)).toBe(DEFAULT_WIDTH);
});

test('opening docks it wide: the body class, the width property and one refit', () => {
  occupant('files');
  expect(openDrawer('files')).toBe(true);
  expect(document.body.classList.contains(BODY_CLASS)).toBe(true);
  expect(document.documentElement.style.getPropertyValue(WIDTH_VAR)).toBe(`${DEFAULT_WIDTH}px`);
  expect(requestFit).toHaveBeenCalledWith('right-drawer');
  closeDrawer('files');
  expect(document.body.classList.contains(BODY_CLASS)).toBe(false);
  expect(requestFit).toHaveBeenCalledTimes(2);
});

test('on a phone it overlays: no body class, no padding for the page', () => {
  viewport(390);
  occupant('notes');
  expect(openDrawer('notes')).toBe(false);
  expect(document.body.classList.contains(BODY_CLASS)).toBe(false);
});

test('one slot: opening one occupant closes the other through its own close', () => {
  const files = occupant('files');
  occupant('notes');
  openDrawer('files');
  openDrawer('notes');
  expect(files.close).toHaveBeenCalledOnce();
  expect(rightDrawer.kind).toBe('notes');
  expect(document.body.classList.contains(BODY_CLASS)).toBe(true);
});

test('the width persists per device and a stored value is clamped on read', () => {
  occupant('files');
  openDrawer('files');
  setDrawerWidth(420, true);
  expect(localStorage.getItem(WIDTH_KEY)).toBe('420');
  closeDrawer('files');
  resetRightDrawerForTest();
  occupant('files');
  openDrawer('files');
  expect(rightDrawer.width).toBe(420);

  localStorage.setItem(WIDTH_KEY, '99999');
  expect(readWidth()).toBe(MAX_WIDTH);
  localStorage.setItem(WIDTH_KEY, 'garbage');
  expect(readWidth()).toBe(DEFAULT_WIDTH);
});

test('storage that throws still opens at the default and still resizes', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
  occupant('files');
  openDrawer('files');
  expect(rightDrawer.width).toBe(DEFAULT_WIDTH);
  expect(setDrawerWidth(300, true)).toBe(300);
});

test('the grip drags from the right edge within bounds and saves on release', () => {
  const { el } = occupant('files');
  openDrawer('files');
  const grip = el.querySelector('.right-drawer-grip') as HTMLElement;
  expect(grip).not.toBeNull();
  expect(installGrip(el)).toBe(grip);
  const fitsAtOpen = requestFit.mock.calls.length;
  grip.setPointerCapture = vi.fn();
  grip.dispatchEvent(new PointerEvent('pointerdown', { button: 0, pointerId: 1 }));
  grip.dispatchEvent(new PointerEvent('pointermove', { clientX: 1000, pointerId: 1 }));
  expect(rightDrawer.width).toBe(400);
  expect(localStorage.getItem(WIDTH_KEY)).toBeNull();
  expect(requestFit.mock.calls.length).toBe(fitsAtOpen);
  grip.dispatchEvent(new PointerEvent('pointermove', { clientX: 1395, pointerId: 1 }));
  expect(rightDrawer.width).toBe(MIN_WIDTH);
  grip.dispatchEvent(new PointerEvent('pointermove', { clientX: 0, pointerId: 1 }));
  expect(rightDrawer.width).toBe(MAX_WIDTH);
  const fitsBefore = requestFit.mock.calls.length;
  grip.dispatchEvent(new PointerEvent('pointerup', { pointerId: 1 }));
  expect(localStorage.getItem(WIDTH_KEY)).toBe(String(MAX_WIDTH));
  expect(requestFit.mock.calls.length).toBe(fitsBefore + 1);
  expect(grip.getAttribute('aria-valuenow')).toBe(String(MAX_WIDTH));
});

test('the grip answers the keyboard', () => {
  const { el } = occupant('notes');
  openDrawer('notes');
  const grip = el.querySelector('.right-drawer-grip') as HTMLElement;
  grip.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));
  expect(rightDrawer.width).toBe(DEFAULT_WIDTH + 16);
  grip.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home' }));
  expect(rightDrawer.width).toBe(MIN_WIDTH);
});

test('dismiss closes only the occupant holding the slot, through its own close', () => {
  const notes = occupant('notes');
  expect(dismissDrawer('notes')).toBe(false);
  openDrawer('notes');
  expect(dismissDrawer('files')).toBe(false);
  expect(dismissDrawer('notes')).toBe(true);
  expect(notes.close).toHaveBeenCalledOnce();
  expect(rightDrawer.kind).toBeNull();
});
