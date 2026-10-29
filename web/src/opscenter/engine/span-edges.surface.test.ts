/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import type { Snippet } from 'svelte';
import { readFileSync } from 'node:fs';

import GridSurface from './GridSurface.svelte';
import { terminalLayout } from './layout.svelte';
import { META } from './meta';
import { sizes, surfaceKeyOf } from './observe.svelte';
import { computeTracks, GUTTER } from './tracks';
import { edgeBox, spanCorners, spanEdges } from './span-edges';
import type { RowModel, Slot, SlotId } from './types';

const P = 'terminal:@primary' as SlotId;

const WIDTH = 1200;
const HEIGHT = 900;

let app: object | null = null;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  (globalThis as { matchMedia?: unknown }).matchMedia ??= (query: string) => ({
    matches: true,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  });
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  terminalLayout.resetAll();
  document.body.innerHTML = '';
  localStorage.clear();
});

function mountSurface(): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const renderCell = createRawSnippet(() => ({
    render: () => '<header class="oc-frame-title">grip</header>',
  })) as unknown as Snippet<[Slot, RowModel, number]>;
  app = mount(GridSurface, { target, props: { store: terminalLayout, renderCell } });
  flushSync();
  sizes[surfaceKeyOf(terminalLayout.page)] = { width: WIDTH, height: HEIGHT };
  flushSync();
  return target;
}

function pointer(type: string, x: number, y: number): PointerEvent {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 });
  Object.defineProperty(event, 'pointerId', { value: 1 });
  Object.defineProperty(event, 'pointerType', { value: 'mouse' });
  return event as PointerEvent;
}

function stackRows(count: number): void {
  for (let n = 0; n < count + 1; n += 1) expect(terminalLayout.add('terminal', `ses_${n}`)).toBeNull();
  for (let n = 1; n <= count; n += 1) {
    const rows = terminalLayout.state.layout.rows;
    expect(terminalLayout.moveTo(`terminal:ses_${n}` as SlotId, { kind: 'new', after: rows[rows.length - 1]!.id })).toBe(true);
  }
}

function threeRowSpanner(extraRows = 0): void {
  stackRows(2 + extraRows);
  terminalLayout.spanUp(P);
  expect(terminalLayout.spanDown(P, WIDTH, GUTTER)).toBe(true);
  expect(terminalLayout.spanDown(P, WIDTH, GUTTER)).toBe(true);
}

describe('a multi row widget resizes along its whole span', () => {
  test('the geometry names an edge that reaches the last covered row, with corners', () => {
    threeRowSpanner();
    const rows = terminalLayout.state.layout.rows;
    const tracks = computeTracks({ rows, width: WIDTH, height: HEIGHT, gutter: GUTTER, metas: META });
    const ids = rows.map((row) => row.id);
    const reach = rows[0]!.slots.find((slot) => slot.id === P)?.span ?? 1;
    expect(reach).toBe(3);

    const edges = spanEdges(tracks, ids);
    expect(edges.length).toBeGreaterThan(0);
    for (const edge of edges) {
      expect(edge.rowAt).toBe(0);
      expect(edge.lastAt).toBe(2);
      const box = edgeBox(tracks, edge);
      const home = tracks.rows[0]!;
      const last = tracks.rows[2]!;
      expect(box.top).toBe(home.top + home.height);
      expect(box.top + box.height).toBe(last.top + last.height);
    }
    const corners = spanCorners(tracks, ids, edges);
    for (const corner of corners) expect(corner.seamRow).toBe(ids[0]);
  });

  test('a widget that spans one row has no extra edge', () => {
    const rows = terminalLayout.state.layout.rows;
    const flat = rows.map((row) => ({ ...row, slots: row.slots.map((slot) => ({ ...slot, span: 1, })) }));
    const tracks = computeTracks({ rows: flat, width: WIDTH, height: HEIGHT, gutter: GUTTER, metas: META });
    expect(spanEdges(tracks, flat.map((row) => row.id))).toEqual([]);
  });

  test('the surface draws the full height edge and dragging it moves the home divider', () => {
    threeRowSpanner();
    const surface = mountSurface();
    const edges = [...surface.querySelectorAll<HTMLElement>('[data-span-edge]')];
    expect(edges.length).toBeGreaterThan(0);
    const rows = terminalLayout.state.layout.rows;
    const tracks = computeTracks({ rows, width: WIDTH, height: HEIGHT, gutter: GUTTER, metas: META });
    const bottom = tracks.rows[2]!.top + tracks.rows[2]!.height;
    for (const edge of edges) {
      expect(parseFloat(edge.style.top) + parseFloat(edge.style.height)).toBe(bottom);
    }

    const mirror = edges[0]!.querySelector<HTMLElement>('[role="separator"]')!;
    expect(mirror.getAttribute('tabindex')).toBe('-1');
    expect(mirror.getAttribute('aria-hidden')).toBe('true');
    const homeDivider = surface.querySelector<HTMLElement>('.oc-row .oc-gutter-col:not([data-mirror])')!;
    expect(homeDivider.getAttribute('tabindex')).toBe('0');

    const before = terminalLayout.state.layout.rows[0]!.slots.map((slot) => slot.fr);
    mirror.dispatchEvent(pointer('pointerdown', 400, 800));
    mirror.dispatchEvent(pointer('pointermove', 340, 800));
    mirror.dispatchEvent(pointer('pointerup', 340, 800));
    const after = terminalLayout.state.layout.rows[0]!.slots.map((slot) => slot.fr);
    expect(after).not.toEqual(before);
    expect(after.reduce((sum, fr) => sum + fr, 0)).toBeCloseTo(before.reduce((sum, fr) => sum + fr, 0), 9);
  });

  test('a corner moves the column divider and the row boundary together', () => {
    threeRowSpanner(1);
    const surface = mountSurface();
    const corner = surface.querySelector<HTMLElement>('.oc-intersection[data-boundary]');
    expect(corner).not.toBeNull();
    const boundary = corner!.dataset['boundary']!;
    const rowsBefore = terminalLayout.state.layout.rows;
    const heightBefore = rowsBefore.find((row) => row.id === boundary)!.size;
    const frBefore = rowsBefore[0]!.slots.map((slot) => slot.fr);
    corner!.dispatchEvent(pointer('pointerdown', 400, 700));
    corner!.dispatchEvent(pointer('pointermove', 370, 740));
    corner!.dispatchEvent(pointer('pointerup', 370, 740));
    const rowsAfter = terminalLayout.state.layout.rows;
    expect(rowsAfter.find((row) => row.id === boundary)!.size).not.toBe(heightBefore);
    expect(rowsAfter[0]!.slots.map((slot) => slot.fr)).not.toEqual(frBefore);
  });

  test('every piece of a spanning seam lights as one line, and the line runs the full edge', () => {
    threeRowSpanner();
    const surface = mountSurface();
    const mirror = surface.querySelector<HTMLElement>('[data-span-edge] .oc-gutter-col')!;
    const home = surface.querySelector<HTMLElement>('.oc-row .oc-gutter-col:not([data-mirror])')!;
    expect(home.dataset['index']).toBe(mirror.dataset['index']);
    const lit = () => [home, mirror].map((piece) => piece.getAttribute('data-lit'));

    mirror.dispatchEvent(new MouseEvent('pointerenter'));
    expect(lit()).toEqual(['hover', 'hover']);
    mirror.dispatchEvent(new MouseEvent('pointerleave'));
    expect(lit()).toEqual([null, null]);
    home.dispatchEvent(pointer('pointerdown', 400, 100));
    expect(lit()).toEqual(['active', 'active']);
    home.dispatchEvent(pointer('pointerup', 400, 100));
    expect(lit()).not.toContain('active');

    const css = readFileSync('src/opscenter/engine/grid.css', 'utf8');
    expect(css).toMatch(/\.oc-gutter-col::before \{\s*inset: var\(--oc-space-1\) 45%/);
    expect(css).toMatch(/\.oc-span-edge > \.oc-gutter-col::before \{\s*top: calc\(-1 \* var\(--oc-space-1\)\)/);
  });
});
