/** @vitest-environment jsdom */
import { expect, test } from 'vitest';
import { placeUnderAnchor } from './popup-placement';

function panelOf(w: number, h: number): HTMLElement {
  const el = document.createElement('div');
  Object.defineProperty(el, 'offsetWidth', { value: w });
  Object.defineProperty(el, 'offsetHeight', { value: h });
  return el;
}

test('no panel means no placement, the caller keeps its last one', () => {
  expect(placeUnderAnchor(null, null)).toBeNull();
});

test('a panel with no anchor is placed from a zero box and stays on screen', () => {
  Object.assign(window, { innerWidth: 1200, innerHeight: 800 });
  const placed = placeUnderAnchor(null, panelOf(200, 100));
  expect(placed).not.toBeNull();
  expect(placed!.left).toBeGreaterThanOrEqual(0);
  expect(placed!.top).toBeGreaterThanOrEqual(0);
});

test('a panel under an anchor sits at the anchor left, below its bottom', () => {
  Object.assign(window, { innerWidth: 1200, innerHeight: 800 });
  const anchor = document.createElement('button');
  anchor.getBoundingClientRect = () => ({ top: 20, bottom: 40, left: 100, right: 160, width: 60, height: 20, x: 100, y: 20, toJSON: () => ({}) });
  const placed = placeUnderAnchor(anchor, panelOf(200, 100))!;
  expect(placed.left).toBe(100);
  expect(placed.top).toBeGreaterThanOrEqual(40);
});
