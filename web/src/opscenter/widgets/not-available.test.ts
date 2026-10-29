/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

vi.mock('./fit-declarations', async (importOriginal) => {
  const real = await importOriginal<typeof import('./fit-declarations')>();
  return {
    ...real,
    FIT_DECLARATIONS: { ...real.FIT_DECLARATIONS, 'stat-running': { sizes: ['small', 'wide'], anySize: false } },
  };
});

import { META } from '../engine/meta';
import { createLayoutStore } from '../engine/layout.svelte';
import { sizes } from '../engine/observe.svelte';
import { checkFit, fitsForSlot, testedBox, testedEnvelope, TESTED_TOLERANCE } from './fits';
import FrameFitBody from './chrome/FrameFitBody.svelte';

let app: object | null = null;

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  delete sizes['stat-running'];
  document.body.innerHTML = '';
});

function drawAt(width: number, height: number): HTMLElement {
  sizes['stat-running'] = { width, height };
  const body = createRawSnippet(() => ({ render: () => '<p data-real-body>body</p>' }));
  const host = document.createElement('div');
  document.body.append(host);
  app = mount(FrameFitBody, {
    target: host,
    props: { meta: META['stat-running'], store: createLayoutStore('home'), frame: null, titleRowPx: 0, body },
  });
  flushSync();
  return host;
}

describe('the tested span', () => {
  test('is what the list spans, a quarter wider each way, on width, height and aspect', () => {
    expect(TESTED_TOLERANCE).toBe(0.25);
    const span = testedEnvelope([{ w: 1, h: 1 }, { w: 2, h: 1 }]);
    expect(span.width).toEqual([72, 240]);
    expect(span.height).toEqual([48, 80]);
    expect(span.aspect[0]).toBeCloseTo(1.5 / 1.25);
    expect(span.aspect[1]).toBeCloseTo(3 * 1.25);
  });

  test('anySize means every box is tested; named sizes alone refuse a box by size and by aspect alone', () => {
    expect(testedBox({ sizes: ['small'], anySize: true }, { width: 5000, height: 40 })).toBe(true);
    const fits = { sizes: ['small', 'wide'] as const, anySize: false };
    expect(testedBox(fits, { width: 150, height: 60 })).toBe(true);
    expect(testedBox(fits, { width: 400, height: 60 })).toBe(false);
    expect(testedBox(fits, { width: 75, height: 78 })).toBe(false);
  });
});

describe('a widget placed in a box', () => {
  test('a tested size draws the widget itself', () => {
    const host = drawAt(150, 60);
    expect(host.querySelector('[data-real-body]')).not.toBeNull();
    expect(host.querySelector('[data-widget-unavailable]')).toBeNull();
  });

  test('an untested size draws the generic icon and "not available at this size", never the body', () => {
    const host = drawAt(900, 400);
    expect(host.querySelector('[data-real-body]')).toBeNull();
    const plate = host.querySelector<HTMLElement>('[data-widget-unavailable]')!;
    expect(plate).not.toBeNull();
    expect(plate.dataset['widgetRefusal']).toBe('untested');
    expect(plate.querySelector('.oc-refusal-icon svg')).not.toBeNull();
    expect(plate.querySelector('.oc-refusal-title')?.textContent).toBe('not available at this size');
    expect(plate.querySelector('.oc-refusal-detail')?.textContent).toBe('made for small, wide');
    expect(plate.textContent).not.toMatch(/\d/);
  });

  test('an untested aspect draws the plate too, though both sides are in range', () => {
    const host = drawAt(75, 78);
    expect(host.querySelector('[data-widget-refusal="untested"]')).not.toBeNull();
    expect(checkFit(fitsForSlot('stat-running')!, { width: 75, height: 78 })).toMatchObject({ ok: false, reason: 'untested' });
  });
});
