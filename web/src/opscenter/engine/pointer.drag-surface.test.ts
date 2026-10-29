/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import type { Snippet } from 'svelte';

import GridSurface from './GridSurface.svelte';
import { homeLayout, terminalLayout, type LayoutStore } from './layout.svelte';
import { beginCellDrag } from './pointer';
import { sizes, surfaceKeyOf } from './observe.svelte';
import type { RowModel, Slot, SlotId } from './types';

const HOME_BAND = { top: 0, bottom: 100 };

const TERMINAL_BAND = { top: 500, bottom: 600 };

const mounted: { app: object; target: HTMLElement }[] = [];

function bandRect(top: number, bottom: number): DOMRect {
  return {
    x: 0,
    y: top,
    top,
    bottom,
    left: 0,
    right: 400,
    width: 400,
    height: bottom - top,
    toJSON: () => ({}),
  } as DOMRect;
}

function mountSurface(store: LayoutStore): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const renderCell = createRawSnippet(() => ({
    render: () => '<header class="oc-frame-title">grip</header>',
  })) as unknown as Snippet<[Slot, RowModel, number]>;
  sizes[surfaceKeyOf(store.page)] = { width: 1200, height: 800 };
  const app = mount(GridSurface, { target, props: { store, renderCell } });
  flushSync();
  mounted.push({ app, target });
  return target;
}

function placeRows(
  container: HTMLElement,
  band: { top: number; bottom: number },
  rowId: string,
  extra: Record<string, { top: number; bottom: number }> = {},
): void {
  const named = container.querySelector<HTMLElement>(`.oc-row[data-row="${rowId}"]`);
  expect(named).not.toBe(null);
  let parked = 3000;
  for (const row of container.querySelectorAll<HTMLElement>('.oc-row[data-row]')) {
    const id = row.dataset['row'] ?? '';
    const where = id === rowId ? band : (extra[id] ?? { top: parked, bottom: parked + 40 });
    if (id !== rowId && !extra[id]) parked += 60;
    row.getBoundingClientRect = () => bandRect(where.top, where.bottom);
    for (const slot of row.querySelectorAll<HTMLElement>('.oc-cellslot')) {
      slot.getBoundingClientRect = () => bandRect(where.top, where.bottom);
    }
  }
}

function targetRow(store: LayoutStore): string | null {
  const target = store.drag.target;
  return target && target.kind === 'row' ? target.row : null;
}

function makeScroller(container: HTMLElement): (to: number) => void {
  const scroller = document.createElement('main');
  scroller.className = 'oc-content';
  container.parentElement?.insertBefore(scroller, container);
  scroller.appendChild(container);
  let position = 0;
  Object.defineProperty(scroller, 'scrollTop', {
    configurable: true,
    get: () => position,
    set: (value: number) => {
      position = value;
    },
  });
  scroller.getBoundingClientRect = () => bandRect(0, 800);
  return (to: number) => {
    position = to;
  };
}

/** A pointer event jsdom can carry: a MouseEvent wearing the two pointer members. */
function pointerEvent(type: string, x: number, y: number): PointerEvent {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 });
  Object.defineProperty(event, 'pointerId', { value: 1 });
  Object.defineProperty(event, 'pointerType', { value: 'mouse' });
  return event as PointerEvent;
}

function dragGripTo(container: HTMLElement, id: SlotId, store: LayoutStore, atY: number): void {
  const grip = container.querySelector<HTMLElement>('.oc-frame-title');
  expect(grip).not.toBe(null);
  const down = pointerEvent('pointerdown', 100, atY);
  expect(beginCellDrag(grip!, down, id, store)).toBe(true);
  grip!.dispatchEvent(pointerEvent('pointermove', 240, atY));
}

function endDrag(): void {
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
}

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});

beforeEach(() => {
  const layout = homeLayout.state.layout;
  homeLayout.adopt({ ...layout, rows: layout.rows.map((row, at) => ({ ...row, id: `r${at + 1}` as RowModel['id'] })) });
});

afterEach(() => {
  endDrag();
  for (const entry of mounted.reverse()) {
    unmount(entry.app, { outro: false });
    entry.target.remove();
  }
  mounted.length = 0;
  terminalLayout.clearDrag();
  homeLayout.clearDrag();
  terminalLayout.resetAll();
  homeLayout.resetAll();
  document.body.innerHTML = '';
  localStorage.clear();
});

describe('a cell drag captures rows from the surface it was started on', () => {
  test('a drag on the TERMINAL surface finds the terminal row, with home mounted first', () => {
    const home = mountSurface(homeLayout);
    const terminal = mountSurface(terminalLayout);
    placeRows(home, HOME_BAND, 'r1');
    placeRows(terminal, TERMINAL_BAND, 'r1');

    dragGripTo(terminal, 'terminal:@primary' as SlotId, terminalLayout, 550);

    expect(targetRow(terminalLayout)).toBe('r1');
    expect(homeLayout.drag.id).toBe(null);
    expect(targetRow(homeLayout)).toBe(null);
  });

  test('a drag on the HOME surface finds the home row, with the terminal mounted first', () => {
    // too rather than
    const terminal = mountSurface(terminalLayout);
    const home = mountSurface(homeLayout);
    placeRows(terminal, TERMINAL_BAND, 'r1');
    placeRows(home, HOME_BAND, 'r1');

    const first = homeLayout.state.layout.rows[0]?.slots[0]?.id;
    expect(first).not.toBe(undefined);
    dragGripTo(home, first as SlotId, homeLayout, 50);

    expect(targetRow(homeLayout)).toBe('r1');
    expect(terminalLayout.drag.id).toBe(null);
    expect(targetRow(terminalLayout)).toBe(null);
  });
});

describe('a cell drag follows the page when it scrolls', () => {
  test('a pointer held still lands in a different row once the page has moved', () => {
    const home = mountSurface(homeLayout);
    const scrollTo = makeScroller(home);
    placeRows(home, { top: 0, bottom: 100 }, 'r1', { r2: { top: 200, bottom: 300 } });

    const first = homeLayout.state.layout.rows[0]?.slots[0]?.id;
    dragGripTo(home, first as SlotId, homeLayout, 50);
    expect(targetRow(homeLayout)).toBe('r1');

    scrollTo(200);
    const grip = home.querySelector<HTMLElement>('.oc-frame-title');
    grip!.dispatchEvent(pointerEvent('pointermove', 240, 50));
    expect(targetRow(homeLayout)).toBe('r2');
  });

  test('asks for a row of its own between two rows, and below the last', () => {
    const home = mountSurface(homeLayout);
    makeScroller(home);
    placeRows(home, { top: 0, bottom: 100 }, 'r1', { r2: { top: 200, bottom: 300 } });

    const first = homeLayout.state.layout.rows[0]?.slots[0]?.id;
    dragGripTo(home, first as SlotId, homeLayout, 150);
    expect(homeLayout.drag.target).toEqual({ kind: 'new', after: 'r1' });

    const grip = home.querySelector<HTMLElement>('.oc-frame-title');
    grip!.dispatchEvent(pointerEvent('pointermove', 240, 9000));
    expect(homeLayout.drag.target?.kind).toBe('new');
    expect((homeLayout.drag.target as { after: string }).after).toBe(
      homeLayout.state.layout.rows[homeLayout.state.layout.rows.length - 1]?.id,
    );
  });

  test('asks for a row of its own above the first row', () => {
    const home = mountSurface(homeLayout);
    makeScroller(home);
    placeRows(home, { top: 400, bottom: 500 }, 'r1');

    const first = homeLayout.state.layout.rows[0]?.slots[0]?.id;
    dragGripTo(home, first as SlotId, homeLayout, 10);
    expect(homeLayout.drag.target).toEqual({ kind: 'new', after: null });
  });
});

describe('a drop on the bottom quarter of a cell stacks under it', () => {
  test('|P|A|B| becomes P full height beside A over B', () => {
    const A = 'terminal:ses_a' as SlotId;
    const B = 'terminal:ses_b' as SlotId;
    expect(terminalLayout.add('terminal', 'ses_a')).toBeNull();
    expect(terminalLayout.add('terminal', 'ses_b')).toBeNull();
    const terminal = mountSurface(terminalLayout);
    const row = terminal.querySelector<HTMLElement>('.oc-row[data-row="r1"]')!;
    row.getBoundingClientRect = () => bandRect(0, 600);
    const columns: Record<string, [number, number]> = {
      'terminal:@primary': [0, 400],
      [A]: [400, 800],
      [B]: [800, 1200],
    };
    for (const slot of row.querySelectorAll<HTMLElement>('.oc-cellslot[data-slot]')) {
      const [left, right] = columns[slot.dataset['slot'] ?? ''] ?? [0, 0];
      slot.getBoundingClientRect = () =>
        ({ ...bandRect(0, 600), x: left, left, right, width: right - left }) as DOMRect;
    }

    const grip = terminal.querySelector<HTMLElement>(`[data-slot="${B}"] .oc-frame-title`)!;
    expect(beginCellDrag(grip, pointerEvent('pointerdown', 1000, 300), B, terminalLayout)).toBe(true);
    grip.dispatchEvent(pointerEvent('pointermove', 600, 560));
    flushSync();
    expect(terminalLayout.drag.target).toEqual({ kind: 'stack', of: A, edge: 'below' });
    expect(terminal.querySelector(`[data-slot="${A}"]`)?.classList.contains('oc-stack-below')).toBe(true);

    grip.dispatchEvent(pointerEvent('pointerup', 600, 560));
    const rows = terminalLayout.state.layout.rows;
    expect(rows.map((one) => one.slots.map((slot) => slot.id))).toEqual([['terminal:@primary', A], [B]]);
    expect(rows[0]!.slots[0]!.span).toBe(2);
  });
});

describe('a drop between two full height columns spans the full height', () => {
  test('|P|A|B/C| with B dropped between P and A gives P, B, A all two rows tall', () => {
    const P = 'terminal:@primary' as SlotId;
    const A = 'terminal:ses_a' as SlotId;
    const B = 'terminal:ses_b' as SlotId;
    const C = 'terminal:ses_c' as SlotId;
    expect(terminalLayout.add('terminal', 'ses_a')).toBeNull();
    expect(terminalLayout.add('terminal', 'ses_b')).toBeNull();
    expect(terminalLayout.add('terminal', 'ses_c')).toBeNull();
    expect(terminalLayout.moveTo(C, { kind: 'stack', of: B, edge: 'below' })).toBe(true);
    const shaped = terminalLayout.state.layout.rows;
    expect(shaped.map((one) => one.slots.map((slot) => [slot.id, slot.span ?? 1]))).toEqual([
      [[P, 2], [A, 2], [B, 1]],
      [[C, 1]],
    ]);

    const terminal = mountSurface(terminalLayout);
    flushSync();
    const boxes: Record<string, [number, number, number, number][]> = {
      r1: [
        [0, 400, 0, 600],
        [412, 800, 0, 600],
        [812, 1200, 0, 300],
      ],
      r2: [
        [0, 400, 312, 600],
        [412, 800, 312, 600],
        [812, 1200, 312, 600],
      ],
    };
    const bands: Record<string, [number, number]> = { r1: [0, 300], r2: [312, 600] };
    for (const row of terminal.querySelectorAll<HTMLElement>('.oc-row[data-row]')) {
      const id = row.dataset['row'] ?? '';
      const [top, bottom] = bands[id]!;
      row.getBoundingClientRect = () => bandRect(top, bottom);
      row.querySelectorAll<HTMLElement>('.oc-cellslot').forEach((slot, at) => {
        const [left, right, boxTop, boxBottom] = boxes[id]![at]!;
        slot.getBoundingClientRect = () =>
          ({ ...bandRect(boxTop, boxBottom), x: left, left, right, width: right - left }) as DOMRect;
      });
    }

    const grip = terminal.querySelector<HTMLElement>(`[data-slot="${B}"] .oc-frame-title`)!;
    expect(beginCellDrag(grip, pointerEvent('pointerdown', 1000, 150), B, terminalLayout)).toBe(true);
    grip.dispatchEvent(pointerEvent('pointermove', 406, 450));
    flushSync();
    expect(terminalLayout.drag.target).toMatchObject({ kind: 'column', row: 'r1', left: P, right: A, rows: 2 });
    expect(terminal.querySelector('.oc-insert-column')).not.toBe(null);
    expect(terminal.querySelector('.oc-insert')).toBe(null);

    grip.dispatchEvent(pointerEvent('pointerup', 406, 450));
    const rows = terminalLayout.state.layout.rows;
    expect(rows.map((one) => one.slots.map((slot) => [slot.id, slot.span ?? 1]))).toEqual([
      [[P, 1], [B, 1], [A, 1], [C, 1]],
    ]);
  });
});

describe('a stacked cell dragged beside a tall one becomes a third full height column', () => {
  const S = 'terminal:@primary' as SlotId;
  const R = 'terminal:ses_rename' as SlotId;
  const U = 'terminal:ses_ui' as SlotId;

  function screenshot(): HTMLElement {
    expect(terminalLayout.add('terminal', 'ses_rename')).toBeNull();
    expect(terminalLayout.add('terminal', 'ses_ui')).toBeNull();
    expect(terminalLayout.moveTo(U, { kind: 'stack', of: R, edge: 'below' })).toBe(true);
    expect(terminalLayout.state.layout.rows.map((one) => one.slots.map((slot) => [slot.id, slot.span ?? 1]))).toEqual([
      [[S, 2], [R, 1]],
      [[U, 1]],
    ]);
    const terminal = mountSurface(terminalLayout);
    flushSync();
    const boxes: Record<string, [number, number, number, number][]> = {
      r1: [
        [0, 594, 0, 600],
        [606, 1200, 0, 300],
      ],
      r2: [
        [0, 594, 312, 600],
        [606, 1200, 312, 600],
      ],
    };
    const bands: Record<string, [number, number]> = { r1: [0, 300], r2: [312, 600] };
    for (const row of terminal.querySelectorAll<HTMLElement>('.oc-row[data-row]')) {
      const id = row.dataset['row'] ?? '';
      const [top, bottom] = bands[id]!;
      row.getBoundingClientRect = () => bandRect(top, bottom);
      row.querySelectorAll<HTMLElement>('.oc-cellslot').forEach((slot, at) => {
        const [left, right, boxTop, boxBottom] = boxes[id]![at]!;
        slot.getBoundingClientRect = () =>
          ({ ...bandRect(boxTop, boxBottom), x: left, left, right, width: right - left }) as DOMRect;
      });
    }
    return terminal;
  }

  test('the gutter beside Share is a full height column and lands three columns', () => {
    const terminal = screenshot();
    const grip = terminal.querySelector<HTMLElement>(`[data-slot="${R}"] .oc-frame-title`)!;
    expect(beginCellDrag(grip, pointerEvent('pointerdown', 900, 20), R, terminalLayout)).toBe(true);
    grip.dispatchEvent(pointerEvent('pointermove', 600, 150));
    flushSync();
    expect(terminalLayout.drag.target).toMatchObject({ kind: 'column', row: 'r1', rows: 2, left: S });
    const mark = terminal.querySelector<HTMLElement>('.oc-insert-column');
    expect(mark).not.toBe(null);
    expect(mark!.style.top).toBe('0px');

    grip.dispatchEvent(pointerEvent('pointerup', 600, 150));
    const rows = terminalLayout.state.layout.rows;
    expect(rows.map((one) => one.slots.map((slot) => [slot.id, slot.span ?? 1]))).toEqual([[[S, 1], [R, 1], [U, 1]]]);
  });

  test('Escape mid-drag leaves the layout exactly as it was', () => {
    const terminal = screenshot();
    const before = terminalLayout.state.layout;
    const grip = terminal.querySelector<HTMLElement>(`[data-slot="${R}"] .oc-frame-title`)!;
    expect(beginCellDrag(grip, pointerEvent('pointerdown', 900, 20), R, terminalLayout)).toBe(true);
    grip.dispatchEvent(pointerEvent('pointermove', 600, 450));
    flushSync();
    expect(terminalLayout.drag.target?.kind).toBe('column');
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    grip.dispatchEvent(pointerEvent('pointerup', 600, 450));
    flushSync();
    expect(terminalLayout.state.layout).toBe(before);
    expect(terminalLayout.drag.id).toBe(null);
    expect(terminalLayout.drag.target).toBe(null);
  });
});
