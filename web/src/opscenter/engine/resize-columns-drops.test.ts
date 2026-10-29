import { describe, expect, it } from 'vitest';
import { settleDrop } from './compact';
import { COL_MIN } from './floors';
import { moveCell, moveCellToNewRow, resizeColumns } from './model';
import { computeTracks, GUTTER } from './tracks';
import type { Layout, SlotId } from './types';

const W = 1407;
const H = 827;
const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
const C = 'terminal:ses_c' as SlotId;
const D = 'terminal:ses_d' as SlotId;
const P = 'terminal:@primary' as SlotId;

function layoutOf(rows: any[]): Layout {
  return { v: 6, rows, hidden: [], heroCollapsed: false, collapsed: [] } as any;
}

function drag(layout: Layout, index: number, dx: number): { next: Layout; widths: number[]; before: number[] } {
  const draw = (l: Layout) => computeTracks({ rows: l.rows, width: W, height: H, gutter: GUTTER });
  const row = draw(layout).rows[0]!;
  const seam = row.seams.find((one) => one.index === index)!;
  const next = resizeColumns(layout, 'r1', index, dx, seam.space, seam.leftMinPx, seam.leftMaxPx);
  const px = (l: Layout) => draw(l).rows[0]!.cells.filter((c) => c.slotId).map((c) => c.width);
  return { next, widths: px(next), before: px(layout) };
}

describe('column seam cascade (#2278)', () => {
  const three = (a: number, b: number, c: number) =>
    layoutOf([{ id: 'r1', kind: 'flex', size: 1, slots: [{ id: A, fr: a }, { id: B, fr: b }, { id: C, fr: c }] }]);

  it('takes from the next cell once the neighbour is at the floor', () => {
    const { widths, before } = drag(three(0.4, 0.3, 0.3), 0, 300);
    expect(widths[1]).toBe(COL_MIN);
    expect(widths[2]!).toBeLessThan(before[2]! - 100);
    expect(Math.abs(widths[0]! - before[0]! - 300)).toBeLessThanOrEqual(2);
    expect(widths.reduce((a, b) => a + b, 0)).toBeCloseTo(before.reduce((a, b) => a + b, 0), -1);
  });

  it('cascades leftwards too', () => {
    const { widths, before } = drag(three(0.3, 0.3, 0.4), 1, -300);
    expect(widths[1]).toBe(COL_MIN);
    expect(widths[0]!).toBeLessThan(before[0]! - 100);
  });

  it('lets a cell already under the floor grow from its own width', () => {
    const { widths, before } = drag(three(0.1, 0.45, 0.45), 0, 50);
    expect(before[0]!).toBeLessThan(COL_MIN);
    expect(Math.abs(widths[0]! - before[0]! - 50)).toBeLessThanOrEqual(2);
  });
});

describe('drops keep sizes (#2278)', () => {
  it('a new row on a flex page scales the others instead of resetting to equal', () => {
    const l = layoutOf([
      { id: 'r1', kind: 'flex', size: 0.5, slots: [{ id: A, fr: 0.5 }, { id: B, fr: 0.5 }] },
      { id: 'r2', kind: 'flex', size: 0.3, slots: [{ id: C, fr: 1 }] },
      { id: 'r3', kind: 'flex', size: 0.2, slots: [{ id: D, fr: 1 }] },
    ]);
    const out = moveCellToNewRow(l, B, 'r3');
    const size = (id: string) => out.rows.find((r) => r.id === id)!.size;
    expect(out.rows).toHaveLength(4);
    expect(size('r1')).toBeCloseTo(0.375, 9);
    expect(size('r2')).toBeCloseTo(0.225, 9);
    expect(size('r3')).toBeCloseTo(0.15, 9);
    expect(out.rows.reduce((a, r) => a + r.size, 0)).toBeCloseTo(1, 9);
  });

  it('a drop that merges two rows keeps the existing widths', () => {
    const Q = 'terminal:ses_q' as SlotId;
    const before = layoutOf([
      { id: 'r1', kind: 'flex', size: 0.5, slots: [{ id: P, fr: 0.5, span: 2 }, { id: Q, fr: 0.5 }] },
      { id: 'r2', kind: 'flex', size: 0.5, slots: [{ id: A, fr: 0.5 }, { id: B, fr: 0.5 }], reserved: [{ of: P, at: 0 }] },
    ]);
    const settled = settleDrop(before, moveCell(before, Q, 'r2', 2), Q)!;
    expect(settled.layout.rows).toHaveLength(1);
    const fr = settled.layout.rows[0]!.slots.map((s) => s.fr);
    expect(fr[0]!).toBeGreaterThan(0.3);
    expect(fr.reduce((a, b) => a + b, 0)).toBeCloseTo(1, 9);
  });
});
