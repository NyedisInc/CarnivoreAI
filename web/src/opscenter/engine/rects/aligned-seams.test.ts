/** @vitest-environment jsdom */
import { describe, expect, test } from 'vitest';
import type { Rect } from '../../../lib/motion-grid';
import type { Layout, SlotId } from '../types';
import { repairSpans } from '../spans';
import { applyDivider, dividerSpecs } from './dividers';
import { layoutGeometry, rectsAreSound } from './layout-rects';

const A = 'terminal:row:1' as SlotId;
const B = 'terminal:row:2' as SlotId;
const C = 'terminal:row:3' as SlotId;
const D = 'terminal:row:4' as SlotId;
const G = 9;

export function twoStacks(left: number, right: number): Layout {
  const lo = Math.min(left, right);
  const hi = Math.max(left, right);
  const leftIsHigher = left < right;
  return repairSpans({
    v: 6,
    rows: [
      { id: 'r1', kind: 'flex', size: lo, slots: [{ id: A, fr: 0.5, ...(leftIsHigher ? {} : { span: 2 }) }, { id: C, fr: 0.5, ...(leftIsHigher ? { span: 2 } : {}) }] },
      { id: 'r2', kind: 'flex', size: hi - lo, slots: [leftIsHigher ? { id: B, fr: 0.5, span: 2 } : { id: D, fr: 0.5, span: 2 }], reserved: [{ of: leftIsHigher ? C : A, at: leftIsHigher ? 1 : 0 }] },
      { id: 'r3', kind: 'flex', size: 1 - hi, slots: [leftIsHigher ? { id: D, fr: 0.5 } : { id: B, fr: 0.5 }], reserved: [leftIsHigher ? { of: B, at: 0 } : { of: D, at: 1 }] },
    ],
    hidden: [],
    heroCollapsed: false,
    collapsed: [],
  } as unknown as Layout);
}

describe('aligned seams', () => {
  for (const [W, HT] of [[1440, 800], [2600, 1000]] as const) {
    for (const [left, right] of [[0.4, 0.7], [0.7, 0.4]] as const) {
      test(`${W}x${HT}: the right divider passes the left one's level with all four windows kept (left ${left}, right ${right})`, () => {
        const layout = twoStacks(left, right);
        const geo = layoutGeometry(layout, W, HT, G);
        const spec = dividerSpecs(layout, geo.tracks, { width: W, height: HT }, G, true).find((one) => one.kind === 'row' && one.seg!.above.includes(C) && one.seg!.below.includes(D))!;
        expect(spec).toBeTruthy();
        const target = geo.rects.get(A)!.y + geo.rects.get(A)!.h;
        const start = geo.rects.get(C)!.y + geo.rects.get(C)!.h;
        const dyAligned = target - start;
        for (let step = -30; step <= 30; step += 1) {
          const dy = dyAligned + step;
          const next = applyDivider(layout, spec, 0, dy);
          const rects = layoutGeometry(next, W, HT, G).rects;
          const got = [A, B, C, D].map((id) => rects.get(id) as Rect | undefined);
          expect(got.every(Boolean), `dy ${dy}`).toBe(true);
          expect(rectsAreSound(got as Rect[], W, HT, G), `dy ${dy}`).toBe(true);
          expect(Math.abs(rects.get(A)!.h - geo.rects.get(A)!.h)).toBeLessThanOrEqual(2);
          expect(Math.abs(rects.get(B)!.y - geo.rects.get(B)!.y)).toBeLessThanOrEqual(2);
          expect(Math.abs(rects.get(C)!.h - (geo.rects.get(C)!.h + dy))).toBeLessThanOrEqual(Math.abs(step) > G + 1 ? 2 : G + 2);
        }
      });
    }
  }

  for (const [left, right] of [[0.4, 0.7], [0.7, 0.4]] as const) {
    test(`the dividers keep one relative order as the right divider passes the left one's level (left ${left}, right ${right})`, () => {
      const W = 1440;
      const HT = 800;
      const layout = twoStacks(left, right);
      const geo = layoutGeometry(layout, W, HT, G);
      const spec = dividerSpecs(layout, geo.tracks, { width: W, height: HT }, G, true).find((one) => one.kind === 'row' && one.seg!.above.includes(C) && one.seg!.below.includes(D))!;
      const dyAligned = geo.rects.get(A)!.y + geo.rects.get(A)!.h - (geo.rects.get(C)!.y + geo.rects.get(C)!.h);
      const idsAt = (dy: number): string[] => {
        const next = applyDivider(layout, spec, 0, dy);
        return dividerSpecs(next, layoutGeometry(next, W, HT, G).tracks, { width: W, height: HT }, G, true).map((one) => one.id);
      };
      let before = idsAt(dyAligned - 40);
      for (let dy = dyAligned - 39; dy <= dyAligned + 40; dy += 1) {
        const now = idsAt(dy);
        expect(now, `dy ${dy}`).toContain(spec.id);
        const kept = before.filter((id) => now.includes(id));
        expect(now.filter((id) => kept.includes(id)), `dy ${dy}`).toEqual(kept);
        before = now;
      }
    });
  }
});
