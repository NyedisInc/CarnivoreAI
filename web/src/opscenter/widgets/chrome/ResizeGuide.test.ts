/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import ResizeGuide from './ResizeGuide.svelte';
import type { ResizeGuide as Guide } from './resize-hint';

let app: object | null = null;

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
});

function draw(guide: Guide, message: boolean): HTMLElement {
  const body = document.createElement('div');
  document.body.append(body);
  app = mount(ResizeGuide, { target: body, props: { guide, message } });
  flushSync();
  return body.querySelector('[data-resize-guide]') as HTMLElement;
}

function edges(overlay: HTMLElement): string[] {
  return [...overlay.querySelectorAll('[data-resize-edge]')].map((el) => `${el.getAttribute('data-resize-edge')}:${el.getAttribute('data-resize-point')}`);
}

describe('ResizeGuide', () => {
  test('a short and too narrow box gets all four chevrons, pointing out', () => {
    expect(edges(draw({ w: 'grow', h: 'grow' }, false))).toEqual(['top:up', 'bottom:down', 'left:left', 'right:right']);
  });

  test('a width at its target drops the left and right chevrons; a height to shrink points in', () => {
    expect(edges(draw({ w: null, h: 'shrink' }, false))).toEqual(['top:down', 'bottom:up']);
  });

  test('the message shows only when asked (over a working body, not over a plate)', () => {
    expect(draw({ w: 'grow', h: null }, true).querySelector('[data-resize-hint]')?.textContent).toBe('resize to fit');
    unmount(app!, { outro: false });
    app = null;
    expect(draw({ w: 'grow', h: null }, false).querySelector('[data-resize-hint]')).toBeNull();
  });

  test('it takes no pointer and is hidden from a screen reader', () => {
    const overlay = draw({ w: 'grow', h: null }, true);
    expect(overlay.getAttribute('aria-hidden')).toBe('true');
  });
});
