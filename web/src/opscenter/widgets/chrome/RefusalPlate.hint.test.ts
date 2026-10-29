/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import RefusalPlate from './RefusalPlate.svelte';
import { layoutEditor } from '../../layout-editor/editor.svelte';
import { FRAME_GUIDE_KEY, FrameGuide } from './resize-guide.svelte';
import type { FitCheck } from '../fits';

let reported = 0;

class FixedObserver {
  constructor(private readonly callback: () => void) {}
  observe(target: Element): void {
    Object.defineProperty(target, 'clientHeight', { configurable: true, get: () => reported });
    this.callback();
  }
  disconnect(): void {}
  unobserve(): void {}
}

const BELOW_FLOOR: Extract<FitCheck, { ok: false }> = { ok: false, reason: 'too-small', has: { w: 6, h: 1 }, suggest: { w: 6, h: 3 } };

let app: object | null = null;
const saved = globalThis.ResizeObserver;

beforeEach(() => {
  (globalThis as { ResizeObserver: unknown }).ResizeObserver = FixedObserver;
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  layoutEditor.active = false;
  (globalThis as { ResizeObserver: unknown }).ResizeObserver = saved;
  document.body.innerHTML = '';
});

function draw(height: number, editing: boolean, frame: FrameGuide = guided()): HTMLElement {
  reported = height;
  layoutEditor.active = editing;
  const target = document.createElement('div');
  document.body.append(target);
  app = mount(RefusalPlate, {
    target,
    props: { check: BELOW_FLOOR, onReport: async () => true },
    context: new Map([[FRAME_GUIDE_KEY, frame]]),
  });
  flushSync();
  return target.querySelector('[data-widget-unavailable]') as HTMLElement;
}

function guided(): FrameGuide {
  const frame = new FrameGuide();
  frame.guide = { w: null, h: 'grow' };
  return frame;
}

describe('the plate carries the message while the frame guide points somewhere, in every mode', () => {
  test.each([
    ['full', 200],
    ['brief', 80],
  ])('the %s step shows "resize to fit" and draws no chevron of its own', (step, height) => {
    const plate = draw(height, false);
    expect(plate.getAttribute('data-plate-step')).toBe(step);
    expect(plate.querySelector('[data-resize-hint]')?.textContent).toBe('resize to fit');
    expect(plate.querySelectorAll('[data-resize-edge]')).toHaveLength(0);
  });

  test('the icon step moves the message to the hover title', () => {
    expect(draw(40, true).getAttribute('title')).toBe('not available at this size: resize to fit');
  });

  test('with the box at a declared size the message is gone', () => {
    const frame = new FrameGuide();
    expect(draw(200, true, frame).querySelector('[data-resize-hint]')).toBeNull();
  });

  test('the plate counts itself on the frame while it is drawn, so the frame keeps the chevrons outside edit layout', () => {
    const frame = guided();
    draw(200, false, frame);
    expect(frame.plates).toBe(1);
    unmount(app!, { outro: false });
    app = null;
    flushSync();
    expect(frame.plates).toBe(0);
  });
});

