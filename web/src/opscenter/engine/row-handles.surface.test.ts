/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import type { Snippet } from 'svelte';

import GridSurface from './GridSurface.svelte';
import { terminalLayout } from './layout.svelte';
import { META } from './meta';
import { sizes, surfaceKeyOf } from './observe.svelte';
import { computeTracks, GUTTER } from './tracks';
import type { RowModel, Slot, SlotId } from './types';

const P = 'terminal:@primary' as SlotId;
const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
const C = 'terminal:ses_c' as SlotId;
const X = 'terminal:ses_x' as SlotId;

const WIDTH = 1200;
const HEIGHT = 600;

let app: object | null = null;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
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

function handles(container: HTMLElement): [number, number][] {
  return [...container.querySelectorAll<HTMLElement>('.oc-gutter-slice')].map((slice) => {
    const left = parseFloat(slice.style.left);
    return [left, left + parseFloat(slice.style.width)];
  });
}

function rangeOf(rowAt: number, id: SlotId | null, nth = 0): [number, number] {
  const tracks = computeTracks({ rows: terminalLayout.state.layout.rows, width: WIDTH, height: HEIGHT, gutter: GUTTER, metas: META });
  const cells = tracks.rows[rowAt]!.cells.filter((cell) => cell.slotId === id);
  const cell = cells[nth]!;
  return [cell.x, cell.x + cell.width];
}

describe('row boundary handles', () => {
  test('sit between the two stacked cells, never under a cell with nothing below it', () => {
    for (const session of ['ses_a', 'ses_b', 'ses_c', 'ses_x']) {
      expect(terminalLayout.add('terminal', session)).toBeNull();
    }
    expect(terminalLayout.moveTo(X, { kind: 'row', row: 'r1', index: 1 })).toBe(true);
    expect(terminalLayout.moveTo(C, { kind: 'stack', of: B, edge: 'below' })).toBe(true);
    terminalLayout.spanUp(X);
    const rows = terminalLayout.state.layout.rows;
    expect(rows.map((one) => one.slots.map((slot) => [slot.id, slot.span ?? 1]))).toEqual([
      [[P, 2], [X, 1], [A, 2], [B, 1]],
      [[C, 1]],
    ]);

    const surface = mountSurface();
    const drawn = handles(surface);
    const stacked = rangeOf(0, B);
    const short = rangeOf(0, X);
    expect(drawn.length).toBe(1);
    const [left, right] = drawn[0]!;
    expect(left).toBeLessThanOrEqual(stacked[0]);
    expect(right).toBeGreaterThanOrEqual(stacked[1]);
    expect(right <= short[0] || left >= short[1]).toBe(true);

    const handle = surface.querySelector<HTMLElement>('.oc-gutter-slice [role="separator"]')!;
    const before = terminalLayout.state.layout.rows[0]!.size;
    handle.dispatchEvent(pointer('pointerdown', 1000, 300));
    handle.dispatchEvent(pointer('pointermove', 1000, 400));
    handle.dispatchEvent(pointer('pointerup', 1000, 400));
    const grown = terminalLayout.state.layout.rows;
    expect(grown[0]!.size).toBeGreaterThan(before);
    handle.dispatchEvent(pointer('pointerdown', 1000, 300));
    handle.dispatchEvent(pointer('pointermove', 1000, 5000));
    handle.dispatchEvent(pointer('pointerup', 1000, 5000));
    const clamped = terminalLayout.state.layout.rows;
    expect(clamped[1]!.size).toBeGreaterThan(0);
    expect(clamped[0]!.size + clamped[1]!.size).toBeCloseTo(before + rows[1]!.size, 9);
  });

  test('two plain rows still get one handle across the whole width', () => {
    expect(terminalLayout.add('terminal', 'ses_a')).toBeNull();
    expect(terminalLayout.moveTo(A, { kind: 'new', after: 'r1' })).toBe(true);
    const drawn = handles(mountSurface());
    expect(drawn).toEqual([[0, WIDTH]]);
  });
});
