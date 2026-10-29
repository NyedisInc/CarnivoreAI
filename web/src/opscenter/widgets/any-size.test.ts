import { describe, expect, test } from 'vitest';
import { META } from '../engine/meta';
import { resizeRows } from '../engine/model';
import { computeTracks } from '../engine/tracks';
import { COL_MIN, ROW_MIN } from '../engine/floors';
import type { Layout, RowModel } from '../engine/types';
import { checkFit, fitsForSlot, SIZE_UNIT_PX, suggestedSizes } from './fits';

const row: RowModel = {
  id: 'r1',
  kind: 'px',
  size: 128,
  slots: [{ id: 'machine-stats', fr: 0.3 }, { id: 'notes', fr: 0.7 }],
};
const layout = { v: 6, rows: [row], hidden: [], heroCollapsed: false, collapsed: [] } as unknown as Layout;

describe('the layout editor accepts a size the widget does not suggest', () => {
  const fits = fitsForSlot('machine-stats')!;
  const suggested = suggestedSizes(fits);

  test('machine stats offers the named sizes it calls out, and 5 x 5 is not one of them', () => {
    expect(fits.anySize).toBe(true);
    expect(suggested).toEqual([{ name: 'tall', w: 2, h: 4 }, { name: 'medium', w: 4, h: 4 }, { name: 'large', w: 6, h: 5 }, { name: 'full', w: 12, h: 5 }]);
    expect(suggested.some((size) => size.w === 5 && size.h === 5)).toBe(false);
  });

  test('a divider may widen it past its largest suggestion: the seam stops only at the neighbour floor', () => {
    const tracks = computeTracks({ rows: [row], width: 2400, height: 900, gutter: 12, metas: META });
    const seam = tracks.rows[0]!.seams[0]!;
    expect(seam.leftMaxPx).toBeGreaterThan(8 * SIZE_UNIT_PX.w);
    expect(seam.leftMaxPx).toBe(seam.pairPx - COL_MIN);
    expect(seam.leftMinPx).toBe(COL_MIN);
  });

  test('a pixel row may be dragged taller than any suggestion, and nobody refuses it', () => {
    const tall = resizeRows(layout, 'r1', 5 * SIZE_UNIT_PX.h - row.size, 0, META);
    expect(tall.rows[0]!.size).toBe(5 * SIZE_UNIT_PX.h);
    expect(resizeRows(layout, 'r1', -5000, 0, META).rows[0]!.size).toBe(ROW_MIN);
  });

  test('the frame draws the body at a non-suggested size, and only a box below the floor is a misfit', () => {
    const box = { width: 5 * SIZE_UNIT_PX.w + 17, height: 5 * SIZE_UNIT_PX.h - 9 };
    expect(checkFit(fits, box)).toEqual({ ok: true });
    expect(checkFit(fits, { width: 40 * SIZE_UNIT_PX.w, height: 30 * SIZE_UNIT_PX.h })).toEqual({ ok: true });
    expect(checkFit(fits, { width: 10, height: 10 })).toMatchObject({ ok: false, reason: 'too-small' });
  });
});
