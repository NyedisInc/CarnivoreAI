import { describe, expect, test } from 'vitest';
import { applyDrop } from '../drop';
import { META } from '../meta';
import { resizeColumns, resizeRows } from '../model';
import { repairSpans } from '../spans';
import { computeTracks } from '../tracks';
import type { Layout, SlotId } from '../types';
import { applyDivider, dividerSpecs } from './dividers';
import { contentExtent, dropGeometry, layoutGeometry } from './layout-rects';

const A = 'terminal:ses_a' as SlotId;
const B = 'terminal:ses_b' as SlotId;
const C = 'terminal:ses_c' as SlotId;
const D = 'terminal:ses_d' as SlotId;
const GUT = 9;
const W = 1200;
const H = 800;

function page(kind: 'flex' | 'px', ...rows: SlotId[][]): Layout {
  return {
    v: 6,
    rows: rows.map((ids, at) => ({
      id: `r${at + 1}` as const,
      kind,
      size: kind === 'flex' ? 1 / rows.length : 300,
      slots: ids.map((id) => ({ id, fr: 1 / ids.length })),
    })),
    hidden: ['notes'],
    heroCollapsed: false,
    collapsed: [],
  };
}

function overlap(a: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

function expectSound(layout: Layout): void {
  const { rects, tracks } = layoutGeometry(layout, W, H, GUT);
  const ids = layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));
  expect([...rects.keys()].sort()).toEqual([...ids].sort());
  const all = [...rects.values()];
  all.forEach((a, i) => all.slice(i + 1).forEach((b) => expect(overlap(a, b)).toBe(false)));
  for (const row of tracks.rows) {
    const last = row.cells[row.cells.length - 1]!;
    expect(last.x + last.width).toBe(W);
  }
}

describe('layoutGeometry', () => {
  test('is the tracks of the surface, slot by slot', () => {
    const layout = page('flex', [A, B], [C]);
    const { rects, tracks } = layoutGeometry(layout, W, H, GUT);
    const top = tracks.rows[0]!;
    expect(rects.get(A)).toEqual({ x: top.cells[0]!.x, y: 0, w: top.cells[0]!.width, h: top.height });
    expect(rects.get(B)!.x).toBe(top.cells[0]!.width + GUT);
    expect(rects.get(C)).toEqual({ x: 0, y: top.height + GUT, w: W, h: tracks.rows[1]!.height });
    expect(top.height + tracks.rows[1]!.height + GUT).toBe(H);
    expect(tracks).toEqual(computeTracks({ rows: layout.rows, width: W, height: H, gutter: GUT, metas: META }));
  });

  test('a spanning cell covers every row it reaches, gutters included', () => {
    const layout = repairSpans({ ...page('flex', [A, B], [C, D]), rows: page('flex', [A, B], [C, D]).rows.map((row, at) => (at === 0 ? { ...row, slots: row.slots.map((slot, i) => (i === 0 ? { ...slot, span: 2 } : slot)) } : row)) });
    const { rects, tracks } = layoutGeometry(layout, W, H, GUT);
    expect(rects.get(A)!.h).toBe(H);
    expect(rects.get(A)!.h).toBe(tracks.spanHeight.get(A));
    expectSound(layout);
  });

  test('content extent is the rows added up for pixel rows and null for flex rows', () => {
    const px = page('px', [A], [B]);
    expect(contentExtent(px, layoutGeometry(px, W, H, GUT).tracks)).toBe(300 + 300 + GUT);
    const flex = page('flex', [A], [B]);
    expect(contentExtent(flex, layoutGeometry(flex, W, H, GUT).tracks)).toBeNull();
  });
});

describe('rects of the reducers output', () => {
  test('a column divider moves the left cell by exactly the pixels dragged (freeform) and stops at the 240 px floor', () => {
    const layout = page('flex', [A, B, C]);
    const spec = dividerSpecs(layout, layoutGeometry(layout, W, H, GUT).tracks, { width: W, height: H }, GUT, true).find((one) => one.kind === 'col')!;
    const before = layoutGeometry(layout, W, H, GUT).rects;
    const moved = layoutGeometry(applyDivider(layout, spec, 57, 0), W, H, GUT).rects;
    expect(Math.abs(moved.get(A)!.w - before.get(A)!.w - 57)).toBeLessThanOrEqual(1);
    const squeezed = layoutGeometry(applyDivider(layout, spec, -5000, 0), W, H, GUT).rects;
    expect(squeezed.get(A)!.w).toBeGreaterThanOrEqual(240 - 1);
    expectSound(applyDivider(layout, spec, 57, 0));
    expect(resizeColumns(layout, 'r1', 0, 57, spec.free, spec.seam!.leftMinPx, spec.seam!.leftMaxPx)).toEqual(applyDivider(layout, spec, 57, 0));
  });

  test('a row divider on a flex page trades height between the rows and keeps the 104 px floor', () => {
    const layout = page('flex', [A], [B]);
    const spec = dividerSpecs(layout, layoutGeometry(layout, W, H, GUT).tracks, { width: W, height: H }, GUT, true).find((one) => one.kind === 'row')!;
    const moved = layoutGeometry(applyDivider(layout, spec, 100, 100), W, H, GUT);
    expect(moved.rects.get(A)!.h).toBeGreaterThan(layoutGeometry(layout, W, H, GUT).rects.get(A)!.h);
    expect(moved.rects.get(A)!.h + moved.rects.get(B)!.h + GUT).toBe(H);
    const squeezed = layoutGeometry(applyDivider(layout, spec, 0, 5000), W, H, GUT).rects;
    expect(squeezed.get(B)!.h).toBeGreaterThanOrEqual(104 - 1);
    expect(layoutGeometry(applyDivider(layout, spec, 0, 100), W, H, GUT).rects.get(A)!.h).toBeCloseTo(layoutGeometry(resizeRows(layout, 'r1', 100, spec.flexSpace, META), W, H, GUT).rects.get(A)!.h, -1);
  });

  test('a divider on an unchanged pointer is the very layout passed in', () => {
    const layout = page('flex', [A, B]);
    const spec = dividerSpecs(layout, layoutGeometry(layout, W, H, GUT).tracks, { width: W, height: H }, GUT, true)[0]!;
    expect(applyDivider(layout, spec, 0, 0)).toBe(layout);
  });

  test('drops produce sound layouts: into another row, a row of its own, beside a cell in its own row', () => {
    const layout = page('flex', [A, B], [C]);
    for (const target of [
      { kind: 'row', row: 'r2', index: 1 },
      { kind: 'new', after: null },
      { kind: 'new', after: 'r2' },
      { kind: 'row', row: 'r1', index: 2 },
      { kind: 'stack', of: C, edge: 'above' },
    ] as const) {
      const next = applyDrop(layout, A, target);
      expect(next).not.toBe(layout);
      expectSound(next);
    }
  });
});

describe('dividers and drop geometry', () => {
  test('a two row, two column page has one seam per row, one boundary stretch per column and one intersection square', () => {
    const layout = page('flex', [A, B], [C, D]);
    const { tracks } = layoutGeometry(layout, W, H, GUT);
    const specs = dividerSpecs(layout, tracks, { width: W, height: H }, GUT, true);
    expect(specs.filter((one) => one.kind === 'col')).toHaveLength(2);
    expect(specs.filter((one) => one.kind === 'row')).toHaveLength(2);
    expect(specs.filter((one) => one.kind === 'inter')).toHaveLength(1);
    expect(specs.find((one) => one.kind === 'row')!.rect).toMatchObject({ y: tracks.rows[0]!.height, h: GUT });
    expect(dividerSpecs(layout, tracks, { width: W, height: H }, GUT, false)).toEqual([]);
  });

  test('drop geometry lists a row per row and a cell per drawn slot in container coordinates', () => {
    const layout = page('flex', [A, B], [C]);
    const { rows, cells } = dropGeometry(layout, layoutGeometry(layout, W, H, GUT).tracks);
    expect(rows.map((row) => row.id)).toEqual(['r1', 'r2']);
    expect(rows[0]!.centres).toHaveLength(2);
    expect(cells.map((cell) => cell.id)).toEqual([A, B, C]);
    expect(cells[2]).toMatchObject({ left: 0, right: W, top: rows[1]!.top, bottom: rows[1]!.bottom });
  });
});
