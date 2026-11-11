/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import { homeLayout } from '../engine/layout.svelte';
import { resetSurface } from '../engine/components-actions';
import { META, metaFor } from '../engine/meta';
import { resetLayout } from '../engine/model';
import { sizes } from '../engine/observe.svelte';
import type { SlotId } from '../engine/types';
import { fitsForSlot, SIZE_UNIT_PX } from '../widgets/fits';
import FrameFitBody from '../widgets/chrome/FrameFitBody.svelte';
import { blobForSend, commitDashLayout, dashItems, isDashGridPage, loadDashGrid, onGridChange } from './dash-store.svelte';
import { membershipOf } from './grid-data';
import { rowsSig } from './format/rows-sig';

let app: object | null = null;

beforeEach(() => {
  localStorage.clear();
  homeLayout.resetAll();
  loadDashGrid('home', {});
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
  localStorage.clear();
});

function wideMinSlot(): SlotId {
  const id = membershipOf(homeLayout.state.layout.rows).find((one) => (fitsForSlot(one)?.min.w ?? 0) >= 2);
  if (!id) throw new Error('no home widget with a 2 unit minimum');
  return id;
}

function draw(id: SlotId, width: number, height: number): HTMLElement {
  sizes[id] = { width, height };
  sizes['surface'] = { width: 1200, height: 800 };
  const body = createRawSnippet(() => ({ render: () => '<p data-real-body>body</p>' }));
  const host = document.createElement('div');
  document.body.append(host);
  app = mount(FrameFitBody, { target: host, props: { meta: metaFor(id, META), store: homeLayout, frame: null, titleRowPx: 0, body } });
  flushSync();
  return host;
}

test('the plate fix grows ONE grid item to the declared minimum in one write, rows and the other items untouched', () => {
  const id = wideMinSlot();
  const fits = fitsForSlot(id)!;
  const rowsBefore = homeLayout.state.layout.rows;
  const sigBefore = rowsSig(rowsBefore);
  commitDashLayout(
    homeLayout.state.layout,
    24,
    dashItems(homeLayout.state.layout, 24).map((i) => (i.id === id ? { ...i, w: 2, h: 2 } : i)),
  );
  const before = dashItems(homeLayout.state.layout, 24);
  let writes = 0;
  const off = onGridChange(() => (writes += 1));
  const host = draw(id, SIZE_UNIT_PX.w - 20, SIZE_UNIT_PX.h * 4);
  host.querySelector<HTMLElement>('[data-refusal-fix]')!.click();
  off();
  expect(writes).toBe(1);
  const after = dashItems(homeLayout.state.layout, 24);
  const grown = after.find((i) => i.id === id)!;
  expect(grown.w).toBeGreaterThan(2);
  expect(grown.h * 40 - 12).toBeGreaterThanOrEqual(fits.min.h * SIZE_UNIT_PX.h - 4);
  expect(homeLayout.state.layout.rows).toBe(rowsBefore);
  expect(rowsSig(homeLayout.state.layout.rows)).toBe(sigBefore);
  expect((blobForSend(homeLayout.state.layout) as { grid: { rowsSig: string } }).grid.rowsSig).toBe(sigBefore);
  for (const one of before) {
    if (one.id === id) continue;
    const now = after.find((i) => i.id === one.id)!;
    expect({ w: now.w, h: now.h }).toEqual({ w: one.w, h: one.h });
  }
});

test('no resize guide is drawn on a dashboard page, over the plate or a working body', () => {
  const id = wideMinSlot();
  const plate = draw(id, SIZE_UNIT_PX.w - 20, SIZE_UNIT_PX.h * 4);
  expect(plate.querySelector('[data-widget-unavailable]')).not.toBeNull();
  expect(plate.querySelector('[data-resize-guide]')).toBeNull();
  unmount(app!, { outro: false });
  app = null;
  document.body.innerHTML = '';
  const working = draw(id, SIZE_UNIT_PX.w * 5 + 17, SIZE_UNIT_PX.h * 5 + 9);
  expect(working.querySelector('[data-real-body]')).not.toBeNull();
  expect(working.querySelector('[data-resize-guide]')).toBeNull();
});

test('the home page is a grid page and the terminal page is not', () => {
  expect(isDashGridPage('home')).toBe(true);
  expect(isDashGridPage('terminal')).toBe(false);
  void resetLayout;
});

test('reset layout on the dashboard also forgets the stored arrangement, so the default shows', () => {
  const first = dashItems(homeLayout.state.layout, 24);
  commitDashLayout(homeLayout.state.layout, 24, first.map((i, k) => (k === 0 ? { ...i, w: 3, h: 3 } : i)));
  expect(dashItems(homeLayout.state.layout, 24)[0]!.w).toBe(3);
  resetSurface(homeLayout);
  expect(dashItems(homeLayout.state.layout, 24)).toEqual(first);
});
