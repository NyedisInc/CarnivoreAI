/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { pev } from '../../../lib/motion-grid/motion-test-kit';

const commitTabDrop = vi.hoisted(() => vi.fn(() => true));
const carryTab = vi.hoisted(() => vi.fn(() => true));
vi.mock('../tab-drag', () => ({ commitTabDrop, carryTab }));
import { mountStrip, stripOf, type StripMotion } from './strip-motion';

const SLOT = 'terminal:@primary';
let strip: StripMotion;
let track: HTMLElement;
let wraps: HTMLElement[];

const box = (left: number, top: number, width: number, height: number) =>
  ({ left, top, right: left + width, bottom: top + height, width, height, x: left, y: top, toJSON() {} }) as DOMRect;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'setTimeout', 'clearTimeout', 'performance'] });
  commitTabDrop.mockClear();
  carryTab.mockClear();
  document.body.innerHTML = '<div class="oc-frame-strip"><div class="oc-tabs"><div class="oc-tabs-track" data-tab-track></div></div></div>';
  track = document.querySelector('[data-tab-track]') as HTMLElement;
  track.closest('.oc-frame-strip')!.getBoundingClientRect = () => box(0, 0, 400, 30);
  track.getBoundingClientRect = () => box(0, 0, 300, 30);
  wraps = ['a', 'b', 'c'].map((id, i) => {
    const wrap = document.createElement('div');
    wrap.className = 'oc-tabwrap';
    wrap.innerHTML = `<button data-tab="${id}" title="${id}"></button>`;
    wrap.getBoundingClientRect = () => box(i * 101, 0, 100, 30);
    track.appendChild(wrap);
    return wrap;
  });
  strip = mountStrip(track, SLOT);
});
afterEach(() => {
  strip.destroy();
  vi.useRealTimers();
  document.body.innerHTML = '';
});

const fire = (type: string, x: number, y: number) => document.body.dispatchEvent(pev(type, x, y));
const frames = (ms = 100) => vi.advanceTimersByTime(ms);

function dragA(x: number, y = 15) {
  const button = wraps[0]!.querySelector('button')!;
  expect(strip.press(button, pev('pointerdown', 50, 15), 'a')).toBe(true);
  fire('pointermove', 50, 15);
  fire('pointermove', x - 1, y);
  fire('pointermove', x, y);
  frames();
}

test('stripOf finds the strip from a tab button', () => {
  expect(stripOf(wraps[0]!.querySelector('button')!)).toBe(strip);
});

test('a reorder keeps the same tab elements and commits once at the previewed index', () => {
  dragA(280);
  expect(track.classList.contains('oc-tabs-live')).toBe(true);
  fire('pointerup', 280, 15);
  frames(2000);
  expect(commitTabDrop).toHaveBeenCalledExactlyOnceWith('a', { kind: 'strip', slot: SLOT, index: 2 });
  expect([...track.children].filter((el) => el.classList.contains('oc-tabwrap'))).toEqual(wraps);
  expect(track.classList.contains('oc-tabs-live')).toBe(false);
  expect(wraps[0]!.style.transform).toBe('');
});

test('Escape cancels: nothing is committed and the strip is given back', () => {
  dragA(250);
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }));
  frames(2000);
  expect(commitTabDrop).not.toHaveBeenCalled();
  expect(track.classList.contains('oc-tabs-live')).toBe(false);
});

test('a press that never travels is a click: no drag starts', () => {
  const button = wraps[0]!.querySelector('button')!;
  strip.press(button, pev('pointerdown', 50, 15), 'a');
  fire('pointermove', 52, 15);
  fire('pointerup', 52, 15);
  frames();
  expect(track.classList.contains('oc-tabs-live')).toBe(false);
  expect(commitTabDrop).not.toHaveBeenCalled();
});

test('dragged out of the strip, the tab is handed to the page once and the strip commits nothing', () => {
  dragA(150, 200);
  expect(carryTab).toHaveBeenCalledTimes(1);
  expect((carryTab.mock.calls as unknown as string[][])[0]![0]).toBe('a');
  fire('pointerup', 150, 200);
  frames(2000);
  expect(commitTabDrop).not.toHaveBeenCalled();
  expect(track.classList.contains('oc-tabs-live')).toBe(false);
});

test('the close key never starts a drag', () => {
  const x = document.createElement('button');
  x.setAttribute('data-tab-close', 'a');
  wraps[0]!.appendChild(x);
  expect(strip.press(x, pev('pointerdown', 50, 15), 'a')).toBe(false);
});

test('touch: a long press lifts, a reorder commits once, and leaving the strip hands nothing off', () => {
  strip.destroy();
  strip = mountStrip(track, SLOT, { touch: true });
  const button = wraps[0]!.querySelector('button')!;
  const t = { pointerType: 'touch' };
  expect(strip.press(button, pev('pointerdown', 50, 15, t), 'a')).toBe(true);
  frames(200);
  expect(track.classList.contains('oc-tabs-live')).toBe(false);
  frames(200);
  expect(track.classList.contains('oc-tabs-live')).toBe(true);
  fire('pointermove', 270, 15);
  fire('pointermove', 280, 15);
  fire('pointermove', 280, 200);
  frames();
  expect(carryTab).not.toHaveBeenCalled();
  fire('pointermove', 280, 15);
  frames();
  fire('pointerup', 280, 15);
  frames(2000);
  expect(carryTab).not.toHaveBeenCalled();
  expect(commitTabDrop).toHaveBeenCalledExactlyOnceWith('a', { kind: 'strip', slot: SLOT, index: 2 });
});

test('touch: a move past 10 px before the hold is a scroll and nothing lifts', () => {
  strip.destroy();
  strip = mountStrip(track, SLOT, { touch: true });
  strip.press(wraps[0]!.querySelector('button')!, pev('pointerdown', 50, 15, { pointerType: 'touch' }), 'a');
  fire('pointermove', 70, 15);
  frames(1000);
  expect(track.classList.contains('oc-tabs-live')).toBe(false);
  fire('pointerup', 70, 15);
  expect(commitTabDrop).not.toHaveBeenCalled();
});

test('touch: Escape after the lift restores the order', () => {
  strip.destroy();
  strip = mountStrip(track, SLOT, { touch: true });
  strip.press(wraps[0]!.querySelector('button')!, pev('pointerdown', 50, 15, { pointerType: 'touch' }), 'a');
  frames(400);
  fire('pointermove', 250, 15);
  frames();
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }));
  frames(2000);
  expect(commitTabDrop).not.toHaveBeenCalled();
  expect(track.classList.contains('oc-tabs-live')).toBe(false);
});
