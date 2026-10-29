import { describe, expect, test } from 'vitest';

import { columnDropAt, moveCellToColumn } from './drop';
import { moveCell, rowOf } from './model';
import { pickTarget, type CellTarget, type RowTarget } from './pointer';
import { repairSpans } from './spans';
import type { Layout, SlotId } from './types';

const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
const C = 'terminal:ses_c' as SlotId;
const D = 'terminal:ses_d' as SlotId;
const P = 'terminal:@primary' as SlotId;

/** A page of flex rows holding the given cells, evenly shared. */
function page(...rows: SlotId[][]): Layout {
  return {
    v: 6,
    rows: rows.map((ids, at) => ({
      id: `r${at + 1}`,
      kind: 'flex',
      size: 1 / rows.length,
      slots: ids.map((id) => ({ id, fr: 1 / ids.length })),
    })),
    hidden: ['notes'],
    heroCollapsed: false,
    collapsed: [],
  };
}

const rows: RowTarget[] = [{ id: 'r1', top: 0, bottom: 600, centres: [200, 600, 1000], reserved: [] }];
const cells: CellTarget[] = [
  { id: A, left: 0, right: 400, top: 0, bottom: 600 },
  { id: B, left: 400, right: 800, top: 0, bottom: 600 },
  { id: C, left: 800, right: 1200, top: 0, bottom: 600 },
];

function dropAt(id: SlotId, x: number): SlotId[] {
  const target = pickTarget(rows, cells, 300, x, id);
  if (target?.kind !== 'row') throw new Error(`expected a row drop, got ${JSON.stringify(target)}`);
  const next = moveCell(page([A, B, C]), id, target.row, target.index);
  return (rowOf(next, 'r1')?.slots ?? []).map((slot) => slot.id);
}

describe('a drop inside the row the cell already lives in', () => {
  test('A dragged rightward into the B | C gap lands between them', () => {
    expect(dropAt(A, 800)).toEqual([B, A, C]);
  });

  test('C dragged leftward into the A | B gap lands between them', () => {
    expect(dropAt(C, 400)).toEqual([A, C, B]);
  });

  test('the first cell dragged past the last lands at the end', () => {
    expect(dropAt(A, 1150)).toEqual([B, C, A]);
  });

  test('the last cell dragged before the first lands at the start', () => {
    expect(dropAt(C, 50)).toEqual([C, A, B]);
  });

  test('a cell dropped on its own place, either side of its centre, stays put', () => {
    expect(dropAt(B, 500)).toEqual([A, B, C]);
    expect(dropAt(B, 700)).toEqual([A, B, C]);
  });

  test('moveCell reads the index against the row as drawn, the moving cell counted', () => {
    const layout = page([A, B, C, D]);
    const order = (next: Layout): SlotId[] => (rowOf(next, 'r1')?.slots ?? []).map((slot) => slot.id);
    expect(order(moveCell(layout, A, 'r1', 2))).toEqual([B, A, C, D]);
    expect(order(moveCell(layout, A, 'r1', 3))).toEqual([B, C, A, D]);
    expect(order(moveCell(layout, A, 'r1', 4))).toEqual([B, C, D, A]);
    expect(order(moveCell(layout, D, 'r1', 1))).toEqual([A, D, B, C]);
    expect(order(moveCell(layout, D, 'r1', 0))).toEqual([D, A, B, C]);
    expect(order(moveCell(layout, B, 'r1', 3))).toEqual([A, C, B, D]);
    expect(order(moveCell(layout, C, 'r1', 1))).toEqual([A, C, B, D]);
  });

  test('the row keeps its total share after a rightward reorder', () => {
    const next = moveCell(page([A, B, C]), A, 'r1', 2);
    expect(rowOf(next, 'r1')?.slots.reduce((sum, slot) => sum + slot.fr, 0)).toBeCloseTo(1, 10);
  });
});

describe('a column drop moving rightward inside its home row', () => {
  function tallPair(): Layout {
    const base = page([D, P, A], [C]);
    return repairSpans({
      ...base,
      rows: base.rows.map((row, at) =>
        at === 0
          ? { ...row, slots: row.slots.map((slot) => (slot.id === D ? slot : { ...slot, span: 2 })) }
          : { ...row, reserved: [{ of: P, at: 0 }, { of: A, at: 0 }] },
      ),
    });
  }

  test('D dragged into the P | A gap lands between them', () => {
    const layout = tallPair();
    const drop = columnDropAt(layout, 'r1', 2, D);
    expect(drop).toMatchObject({ kind: 'column', row: 'r1', left: P, right: A, rows: 2 });
    const next = moveCellToColumn(layout, D, drop!.left!, drop!.right!);
    expect(next.rows[0]!.slots.map((slot) => slot.id)).toEqual([P, D, A, C]);
  });
});
