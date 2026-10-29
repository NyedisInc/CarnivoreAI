import { describe, expect, test } from 'vitest';

import { applyDrop, columnDropAt, moveCellToColumn } from './drop';
import { META } from './meta';
import { repairSpans, spanOf } from './spans';
import { stackCell } from './stack';
import { computeTracks } from './tracks';
import type { Layout, SlotId } from './types';

const P = 'terminal:@primary' as SlotId;
const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
const C = 'terminal:ses_c' as SlotId;
const D = 'terminal:ses_d' as SlotId;

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

function twoTall(): Layout {
  return stackCell(page([P, A, B, C]), C, B, 'below');
}

function boxOf(layout: Layout, id: SlotId): { x: number; width: number; row: number; span: number } {
  const tracks = computeTracks({ rows: layout.rows, width: 1200, height: 800, gutter: 12, metas: META });
  for (let row = 0; row < tracks.rows.length; row += 1) {
    const cell = tracks.rows[row]!.cells.find((one) => one.slotId === id);
    if (cell) return { x: cell.x, width: cell.width, row, span: cell.span };
  }
  throw new Error(`${id} is not drawn`);
}

function shape(layout: Layout): [SlotId, number][][] {
  return layout.rows.map((row) => row.slots.map((slot) => [slot.id, spanOf(slot)] as [SlotId, number]));
}

describe('columnDropAt', () => {
  test('the gap between two tall columns is a column drop from either row', () => {
    const layout = twoTall();
    expect(shape(layout)).toEqual([[[P, 2], [A, 2], [B, 1]], [[C, 1]]]);
    const want = { kind: 'column', row: 'r1', left: P, right: A, rows: 2 };
    expect(columnDropAt(layout, 'r1', 1, B)).toMatchObject({ ...want, at: 'r1', index: 1 });
    expect(columnDropAt(layout, 'r2', 1, B)).toMatchObject({ ...want, at: 'r2', index: 1 });
  });

  test('a gap beside a short cell, or an edge beside one, is a plain row drop', () => {
    const layout = twoTall();
    expect(columnDropAt(layout, 'r1', 2, C)).toBeNull();
    expect(columnDropAt(layout, 'r1', 3, C)).toBeNull();
  });

  test('an edge beside a tall column is a column that tall (issue #414)', () => {
    const layout = twoTall();
    expect(columnDropAt(layout, 'r1', 0, B)).toMatchObject({ kind: 'column', row: 'r1', rows: 2, left: null, right: P });
    expect(columnDropAt(layout, 'r2', 0, B)).toMatchObject({ kind: 'column', row: 'r1', rows: 2, left: null, right: P });
  });

  test("the dragged cell's own vacancy is not a neighbour", () => {
    const layout = twoTall();
    const drop = columnDropAt(layout, 'r1', 1, P);
    expect(drop).toMatchObject({ kind: 'column', rows: 2, left: null, right: A });
    const same = applyDrop(layout, P, drop!);
    expect(shape(same)).toEqual(shape(layout));
    expect(boxOf(same, P)).toEqual(boxOf(layout, P));
  });

  test('neighbours covering different rows say nothing about the gap', () => {
    const three = stackCell(stackCell(page([P, A, B, C, D]), C, B, 'below'), D, C, 'below');
    const uneven: Layout = repairSpans({
      ...three,
      rows: three.rows.map((row) => ({ ...row, slots: row.slots.map((slot) => (slot.id === A ? { ...slot, span: 2 } : slot)) })),
    });
    expect(columnDropAt(uneven, 'r1', 1, B)).toMatchObject({ kind: 'column', row: 'r1', rows: 2 });
  });
});

describe('moveCellToColumn', () => {
  test('a cell from another row lands between the neighbours, as tall as they are', () => {
    const layout: Layout = repairSpans({
      ...page([P, A, B], [C], [D]),
      rows: page([P, A, B], [C], [D]).rows.map((row, at) =>
        at === 0
          ? { ...row, slots: row.slots.map((slot) => (slot.id === B ? slot : { ...slot, span: 2 })) }
          : at === 1
            ? { ...row, reserved: [{ of: P, at: 0 }, { of: A, at: 0 }] }
            : row,
      ),
    });
    expect(shape(layout)).toEqual([[[P, 2], [A, 2], [B, 1]], [[C, 1]], [[D, 1]]]);
    const next = moveCellToColumn(layout, D, P, A);
    expect(shape(next)).toEqual([[[P, 2], [D, 2], [A, 2], [B, 1]], [[C, 1]]]);
    for (const slot of next.rows[0]!.slots) expect(slot.fr).toBeCloseTo(0.25, 9);
    const p = boxOf(next, P);
    const d = boxOf(next, D);
    const a = boxOf(next, A);
    expect(d.row).toBe(0);
    expect(d.span).toBe(2);
    expect(d.x).toBeGreaterThan(p.x + p.width);
    expect(d.x + d.width).toBeLessThan(a.x);
  });

  test("the owner's drop: the stacked cell's partner moves into the gap", () => {
    const next = moveCellToColumn(twoTall(), B, P, A);
    expect(shape(next)).toEqual([[[P, 1], [B, 1], [A, 1], [C, 1]]]);
    expect(next.rows[0]!.slots.reduce((sum, slot) => sum + slot.fr, 0)).toBeCloseTo(1, 9);
    expect(next.rows.reduce((sum, row) => sum + row.size, 0)).toBeCloseTo(1, 9);
    for (const id of [P, B, A, C]) expect(boxOf(next, id).width).toBeGreaterThan(0);
  });

  test('neighbours named out of order are refused', () => {
    const next = moveCellToColumn(twoTall(), B, P, A);
    const again = moveCellToColumn(next, B, A, P);
    expect(again).toBe(next);
  });

  test('a covered row with a cell left of the columns pins the arrival beside them', () => {
    const base = twoTall();
    const moved: Layout = repairSpans({
      ...base,
      rows: base.rows.map((row, at) => (at === 1 ? { ...row, reserved: (row.reserved ?? []).map((one) => ({ ...one, at: 1 })) } : row)),
    });
    const next = moveCellToColumn(moved, B, P, A);
    expect(shape(next)).toEqual([[[C, 1], [P, 1], [B, 1], [A, 1]]]);
  });

  test('refuses a neighbour as the moving cell', () => {
    const layout = twoTall();
    expect(moveCellToColumn(layout, P, P, A)).toBe(layout);
    expect(moveCellToColumn(layout, A, P, A)).toBe(layout);
  });
});

/** A small seeded generator, so a failure names the case that made it. */
function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

describe('random stacks, then every column drop the layout offers', () => {
  test('every result is consistent, holds every cell once, and the arrival sits between its neighbours', () => {
    const ids = [P, A, B, C, D];
    let offered = 0;
    for (let seed = 1; seed <= 200; seed += 1) {
      const random = seeded(seed);
      let layout = page(ids);
      for (let step = 0; step < 4; step += 1) {
        const id = ids[Math.floor(random() * ids.length)]!;
        const of = ids[Math.floor(random() * ids.length)]!;
        layout = applyDrop(layout, id, { kind: 'stack', of, edge: random() < 0.5 ? 'above' : 'below' });
      }
      for (const row of layout.rows) {
        const drawn = row.slots.length + (row.reserved?.length ?? 0);
        for (let index = 0; index <= drawn; index += 1) {
          for (const dragged of ids) {
            const drop = columnDropAt(layout, row.id, index, dragged);
            if (!drop) continue;
            offered += 1;
            const next = applyDrop(layout, dragged, drop);
            const label = `seed ${seed} row ${row.id} index ${index} dragged ${dragged}`;
            expect(next, label).not.toBe(layout);
            expect(repairSpans(next), label).toBe(next);
            const placed = next.rows.flatMap((one) => one.slots.map((slot) => slot.id)).sort();
            expect(placed, label).toEqual([...ids].sort());
            const arrival = boxOf(next, dragged);
            expect(arrival.width, label).toBeGreaterThan(0);
            if (drop.left) expect(arrival.x, label).toBeGreaterThan(boxOf(next, drop.left).x);
            if (drop.right) expect(arrival.x, label).toBeLessThan(boxOf(next, drop.right).x);
          }
        }
      }
    }
    expect(offered).toBeGreaterThan(100);
  });
});
