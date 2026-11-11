import { describe, expect, test } from 'vitest';

import { META } from './meta';
import { stackCell } from './stack';
import { pickTarget, type CellTarget, type RowTarget } from './pointer';
import { spanOf } from './spans';
import { computeTracks } from './tracks';
import type { Layout, SlotId } from './types';

const P = 'terminal:@primary' as SlotId;
const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;

function threeAcross(): Layout {
  return {
    v: 6,
    rows: [
      {
        id: 'r1',
        kind: 'flex',
        size: 1,
        slots: [
          { id: P, fr: 0.5 },
          { id: A, fr: 0.25 },
          { id: B, fr: 0.25 },
        ],
      },
    ],
    hidden: ['notes'],
    heroCollapsed: false,
    collapsed: [],
  };
}

function boxOf(layout: Layout, id: SlotId): { x: number; width: number; row: number; span: number } {
  const tracks = computeTracks({ rows: layout.rows, width: 1200, height: 800, gutter: 12, metas: META });
  for (let row = 0; row < tracks.rows.length; row += 1) {
    const cell = tracks.rows[row]!.cells.find((one) => one.slotId === id);
    if (cell) return { x: cell.x, width: cell.width, row, span: cell.span };
  }
  throw new Error(`${id} is not drawn`);
}

describe('stackCell', () => {
  test('below: the dropped cell takes the target column and the neighbour spans both rows', () => {
    const next = stackCell(threeAcross(), B, A, 'below');
    expect(next.rows).toHaveLength(2);
    const pane = boxOf(next, P);
    const a = boxOf(next, A);
    const b = boxOf(next, B);
    expect(pane).toMatchObject({ row: 0, span: 2 });
    expect(a.row).toBe(0);
    expect(b.row).toBe(1);
    expect(b.x).toBe(a.x);
    expect(b.width).toBe(a.width);
    expect(next.rows.reduce((sum, row) => sum + row.size, 0)).toBeCloseTo(1, 9);
  });

  test('above: the dropped cell lands over the target in its column', () => {
    const next = stackCell(threeAcross(), B, A, 'above');
    expect(next.rows).toHaveLength(2);
    const pane = boxOf(next, P);
    const a = boxOf(next, A);
    const b = boxOf(next, B);
    expect(pane).toMatchObject({ row: 0, span: 2 });
    expect(b.row).toBe(0);
    expect(a.row).toBe(1);
    expect(b.x).toBe(a.x);
    expect(b.width).toBe(a.width);
  });

  test('stacking again grows the tall neighbour by one more row', () => {
    const once = stackCell(threeAcross(), B, A, 'below');
    const withNotes: Layout = { ...once, hidden: [], rows: once.rows.map((row, at) => (at === 0 ? { ...row, slots: [...row.slots.map((s) => ({ ...s, fr: s.fr * 0.8 })), { id: 'notes', fr: 0.2 }] } : row)) };
    const twice = stackCell(withNotes, 'notes', B, 'below');
    const pane = twice.rows[0]!.slots.find((slot) => slot.id === P)!;
    expect(spanOf(pane)).toBe(3);
    expect(boxOf(twice, 'notes').x).toBe(boxOf(twice, B).x);
  });

  test('a cell cannot be stacked on itself', () => {
    const layout = threeAcross();
    expect(stackCell(layout, A, A, 'below')).toBe(layout);
  });
});

describe('pickTarget offers the stack', () => {
  const rows: RowTarget[] = [{ id: 'r1', top: 0, bottom: 600, centres: [300, 756, 1056], reserved: [] }];
  const cells: CellTarget[] = [
    { id: P, left: 0, right: 600, top: 0, bottom: 600 },
    { id: A, left: 612, right: 900, top: 0, bottom: 600 },
    { id: B, left: 912, right: 1200, top: 0, bottom: 600 },
  ];

  test('the bottom quarter of a cell is a stack below it', () => {
    expect(pickTarget(rows, cells, 520, 700, B)).toEqual({ kind: 'stack', of: A, edge: 'below' });
  });

  test('the top quarter of a cell is a stack above it', () => {
    expect(pickTarget(rows, cells, 80, 700, B)).toEqual({ kind: 'stack', of: A, edge: 'above' });
  });

  test('the middle of a cell is still a place in its row', () => {
    expect(pickTarget(rows, cells, 300, 700, B)).toEqual({ kind: 'row', row: 'r1', index: 1 });
  });

  test('the surface edge is still a full width row of its own', () => {
    expect(pickTarget(rows, cells, 597, 700, B)).toEqual({ kind: 'new', after: 'r1' });
  });

  test("the dragged cell's own vacancy is never a stack target", () => {
    expect(pickTarget(rows, cells, 520, 1000, B)?.kind).toBe('row');
  });
});

describe('stackCell past the span ceiling (#2935)', () => {
  test('cutting a 64 row window inside a row would make a 65th row: refused, the layout comes back as it was', () => {
    const C = (n: number): SlotId => `terminal:ses_c${n}` as SlotId;
    const E = 'terminal:ses_e' as SlotId;
    const rows: Layout['rows'] = Array.from({ length: 64 }, (_, n) => ({
      id: `r${n}`,
      kind: 'flex' as const,
      size: n === 30 ? 0.9 : 0.1 / 63,
      slots: [
        ...(n === 0 ? [{ id: A, fr: 0.3, span: 64 }, { id: B, fr: 0.3, span: 64 }] : []),
        { id: C(n), fr: 0.4 },
        ...(n === 30 ? [{ id: E, fr: 0.4 }] : []),
      ],
    }));
    const layout: Layout = { v: 6, rows, hidden: [], heroCollapsed: false, collapsed: [] };
    expect(stackCell(layout, E, A, 'above')).toBe(layout);
    expect(stackCell(layout, E, A, 'below')).toBe(layout);
  });
});
