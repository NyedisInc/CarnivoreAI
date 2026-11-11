import { expect, test } from 'vitest';
import { foldLifted } from './compact';
import { META } from './meta';
import { normalizeRow, removeCell, rowOfCell, withoutCell } from './model';
import { layoutGeometry, uncoveredFraction } from './rects/layout-rects';
import { clearSpan, repairSpans } from './spans';
import type { Layout, SlotId } from './types';

const id = (n: number): SlotId => `terminal:row:${n}` as SlotId;
const [P, M, R, S, Q, T] = [1, 2, 3, 4, 5, 6].map(id);
const EXAMPLE: Layout = {
  v: 6,
  hidden: [],
  heroCollapsed: false,
  collapsed: [],
  rows: [
    { id: 'r1', kind: 'flex', size: 0.25, slots: [{ id: P, fr: 0.3, span: 2 }, { id: M, fr: 0.4, span: 4 }, { id: R, fr: 0.3 }] },
    { id: 'r2', kind: 'flex', size: 0.25, slots: [{ id: S, fr: 1, span: 2 }], reserved: [{ of: P, at: 0 }, { of: M, at: 0 }] },
    { id: 'r3', kind: 'flex', size: 0.25, slots: [{ id: Q, fr: 1, span: 2 }], reserved: [{ of: M, at: 1 }, { of: S, at: 1 }] },
    { id: 'r4', kind: 'flex', size: 0.25, slots: [{ id: T, fr: 1 }], reserved: [{ of: Q, at: 0 }, { of: M, at: 0 }] },
  ],
};

function bare(layout: Layout): { hole: number; drawn: number } {
  const rects = layoutGeometry(layout, 2076, 977, 9).rects;
  return { hole: uncoveredFraction([...rects.values()], 2076, 977, 9), drawn: rects.size };
}

test('lifting the window whose column a neighbour pins leaves no hole: the window above reaches down over it', () => {
  const cleared = clearSpan(EXAMPLE, Q);
  const from = rowOfCell(cleared, Q)!;
  const lifted = repairSpans({ ...cleared, rows: cleared.rows.map((row) => (row.id === from.id ? normalizeRow(withoutCell(row, Q)) : row)) });
  expect(bare(lifted).hole).toBeGreaterThan(0.05);
  const whole = foldLifted(EXAMPLE, lifted, Q);
  expect(bare(whole)).toEqual({ hole: 0, drawn: 5 });
  const rects = layoutGeometry(whole, 2076, 977, 9).rects;
  expect(rects.get(P)!.h).toBeGreaterThan(layoutGeometry(EXAMPLE, 2076, 977, 9).rects.get(P)!.h);
});

test('closing the same window leaves no hole either (the removal path)', () => {
  expect(bare(removeCell(EXAMPLE, Q))).toEqual({ hole: 0, drawn: 5 });
});

test('closing the same window shrinks no other window by more than 2 px', () => {
  const closed = removeCell(EXAMPLE, Q);
  for (const [w, h] of [[2076, 977], [1560, 1004], [900, 700]] as const) {
    const was = layoutGeometry(EXAMPLE, w, h, 9).rects;
    const now = layoutGeometry(closed, w, h, 9).rects;
    for (const [one, rect] of now) {
      const before = was.get(one)!;
      expect(before.w - rect.w, `${one} width at ${w}`).toBeLessThanOrEqual(2);
      expect(before.h - rect.h, `${one} height at ${w}`).toBeLessThanOrEqual(2);
    }
  }
});
