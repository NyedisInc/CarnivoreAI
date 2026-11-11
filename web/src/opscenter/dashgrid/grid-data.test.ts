import { describe, expect, it } from 'vitest';
import { META } from '../engine/meta';
import { insertDefaultAnalytics, resetLayout } from '../engine/model';
import type { RowModel, SlotId } from '../engine/types';
import { blobWithGrid, layoutFor, membershipOf, resolveGrid, withLayout } from './grid-data';
import { readBoardGrid, type BoardBlob } from './format/grid-format';
import { rowsSig } from './format/rows-sig';
import { boardRects } from './board-rects';

const ANALYTICS = [1, 2].map((n) => `analytics:00000000-0000-4000-8000-00000000000${n}` as const);
const plain = (): BoardBlob => JSON.parse(JSON.stringify(insertDefaultAnalytics(resetLayout(META), ANALYTICS))) as BoardBlob;
const rowOf = (id: RowModel['id'], slot: SlotId): RowModel => ({ id, kind: 'px', size: 200, slots: [{ id: slot, fr: 1 }] });

describe('resolveGrid', () => {
  it('uses the stored grid while its rowsSig matches the rows', () => {
    const blob = plain();
    const first = resolveGrid(blob);
    const stored = blobWithGrid(blob, first);
    expect(resolveGrid(stored)).toBe(stored.grid);
  });

  it('reconciles a changed widget set: survivors keep their place, the new one is placed, the gone is dropped', () => {
    const blob = plain();
    const stored = blobWithGrid(blob, resolveGrid(blob));
    const ids = membershipOf(stored.rows);
    const gone = ids[1]!;
    const rows = stored.rows.map((r) => ({ ...r, slots: r.slots.filter((s) => s.id !== gone) })).filter((r) => r.slots.length);
    rows.push(rowOf('r99', 'skills'));
    const next = resolveGrid({ rows, grid: stored.grid });
    const after = next.layouts['24'];
    expect(after.some((i) => i.id === gone)).toBe(false);
    expect(after.some((i) => i.id === 'skills')).toBe(true);
    const was = stored.grid.layouts['24'].find((i) => i.id === ids[0])!;
    expect(after.find((i) => i.id === ids[0])?.x).toBe(was.x);
    expect(next.rowsSig).toBe(rowsSig(rows));
  });

  it('converts the rows when the survivors were rearranged', () => {
    const blob = plain();
    const stored = blobWithGrid(blob, resolveGrid(blob));
    const rows = [...stored.rows].reverse();
    const next = resolveGrid({ rows, grid: stored.grid });
    expect(next).toEqual(expect.objectContaining({ order: membershipOf(rows) }));
    expect(next.layouts['24'].length).toBe(membershipOf(rows).length);
  });

  it('converts when there is no grid', () => {
    const blob = plain();
    expect(resolveGrid(blob).layouts['24']).toEqual(readBoardGrid(blob).grid.layouts['24']);
  });
});

describe('write and derived layouts', () => {
  it('a write keeps rows byte identical and membership in sync', () => {
    const blob = plain();
    const out = blobWithGrid(blob, resolveGrid(blob));
    expect(JSON.stringify(out.rows)).toBe(JSON.stringify(blob.rows));
    expect(out.grid.rowsSig).toBe(rowsSig(blob.rows));
    expect(out.grid.layouts['24'].map((i) => i.id).sort()).toEqual(membershipOf(blob.rows).sort());
  });

  it('12 columns halve widths and 1 column stacks at full width', () => {
    const grid = resolveGrid(plain());
    expect(layoutFor(grid, 12).every((i) => i.x + i.w <= 12 && i.w >= 1)).toBe(true);
    const one = layoutFor(grid, 1);
    expect(one.every((i) => i.x === 0 && i.w === 1)).toBe(true);
    expect(new Set(one.map((i) => i.y)).size).toBe(one.length);
  });

  it('an edit at 24 columns drops the derived layouts, an edit at 12 keeps its own', () => {
    const grid = resolveGrid(plain());
    const twelve = withLayout(grid, 12, layoutFor(grid, 12));
    expect(twelve.layouts['12']).toBeDefined();
    expect(withLayout(twelve, 24, grid.layouts['24']).layouts['12']).toBeUndefined();
  });

  it('previews read through one helper at a width', () => {
    const blob = plain();
    const wide = boardRects(blob, 1440);
    expect(wide.length).toBe(membershipOf(blob.rows).length);
    expect(Math.max(...wide.map((b) => b.top + b.height))).toBeCloseTo(100);
    expect(boardRects(undefined, 1440)).toEqual([]);
  });
});
