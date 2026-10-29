/** @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { innerBox, innerX, innerY, isDrawn, overflowOf, shared } from './box-geometry';

function boxed(style: string, rect: { left: number; top: number; width: number; height: number }): HTMLElement {
  const el = document.createElement('div');
  el.setAttribute('style', style);
  document.body.append(el);
  el.getBoundingClientRect = (): DOMRect => new DOMRect(rect.left, rect.top, rect.width, rect.height);
  return el;
}

describe('box geometry', () => {
  it('names how an axis overflows', () => {
    const el = boxed('overflow-x: auto; overflow-y: hidden', { left: 0, top: 0, width: 10, height: 10 });
    expect(overflowOf(el, 'x')).toBe('scroll');
    expect(overflowOf(el, 'y')).toBe('clip');
    expect(overflowOf(boxed('', { left: 0, top: 0, width: 10, height: 10 }), 'x')).toBeNull();
  });

  it('measures inside the borders', () => {
    const el = boxed('border: 2px solid; border-left-width: 4px', { left: 10, top: 20, width: 100, height: 50 });
    expect(innerX(el)).toEqual({ left: 14, right: 108 });
    expect(innerY(el)).toEqual({ top: 22, bottom: 68 });
    expect(innerBox(el)).toMatchObject({ x: 14, y: 22, width: 94, height: 46 });
  });

  it('measures what two rects share, negative when apart', () => {
    expect(shared(new DOMRect(0, 0, 10, 10), new DOMRect(5, 8, 10, 10))).toEqual({ x: 5, y: 2 });
    expect(shared(new DOMRect(0, 0, 10, 10), new DOMRect(20, 0, 5, 5)).x).toBe(-10);
  });

  it('calls a 1px box not drawn, and applies the clip-path rule only when asked', () => {
    expect(isDrawn(boxed('', { left: 0, top: 0, width: 1, height: 40 }))).toBe(false);
    const cut = boxed('position: absolute; clip-path: inset(50%)', { left: 0, top: 0, width: 30, height: 30 });
    expect(isDrawn(cut)).toBe(true);
    expect(isDrawn(cut, true)).toBe(false);
  });
});
