/** @vitest-environment jsdom */
import { describe, expect, it, vi } from 'vitest';
import type { GestureState } from '../../lib/motion-grid/types';
import { createDashAdapter } from './dash-adapter';
import type { GridItem } from './format/grid-format';

const item = (id: string, x: number, y: number, w: number, h: number): GridItem => ({ id: id as GridItem['id'], x, y, w, h });
const STEP = (1500 - 9 * 23) / 24 + 9;

function drag(edge: string, dx: number, dy: number) {
  const items = [item('f', 0, 0, 24, 4), item('a', 6, 4, 6, 4)];
  const commit = vi.fn();
  const adapter = createDashAdapter({ cols: () => 24, width: () => 1500, items: () => items, commit });
  const source = { kind: 'resize', id: 'a', edge } as GestureState['source'];
  adapter.begin?.(source, 'pointer');
  const g: GestureState = { source, pointer: { x: 0, y: 0 }, start: { x: 0, y: 0 }, delta: { x: dx, y: dy }, grab: { x: 0, y: 0 }, startRect: adapter.rects().get('a' as never) ?? null, base: adapter.rects(), bounds: { w: 1500, h: 800 }, outside: false };
  const target = adapter.preview(g, adapter.targetKey(g));
  adapter.commit(target, g);
  return commit.mock.calls[0]![0].find((i: GridItem) => (i.id as string) === 'a') as GridItem;
}

describe('dashboard resize from all 8 handles', () => {
  const cases: [string, number, number, Partial<GridItem>][] = [
    ['e', 2 * STEP, 0, { x: 6, w: 8 }],
    ['w', -2 * STEP, 0, { x: 4, w: 8 }],
    ['s', 0, 2 * 40, { y: 4, h: 6 }],
    ['se', STEP, 40, { x: 6, y: 4, w: 7, h: 5 }],
    ['sw', -STEP, 40, { x: 5, y: 4, w: 7, h: 5 }],
  ];
  for (const [edge, dx, dy, want] of cases) {
    it(`${edge} moves its own edge and keeps the opposite one`, () => {
      expect(drag(edge, dx, dy)).toMatchObject(want);
    });
  }
  it('n, ne and nw move the top edge up and keep the bottom edge where it was (the grid then packs the item upward as it always does)', () => {
    const items = [item('a', 6, 4, 6, 4)];
    const adapter = createDashAdapter({ cols: () => 24, width: () => 1500, items: () => items, commit: vi.fn() });
    for (const edge of ['n', 'ne', 'nw']) {
      const source = { kind: 'resize', id: 'a', edge } as GestureState['source'];
      adapter.begin?.(source, 'pointer');
      const r0 = adapter.rects().get('a')!;
      const g: GestureState = { source, pointer: { x: 0, y: 0 }, start: { x: 0, y: 0 }, delta: { x: edge === 'ne' ? STEP : edge === 'nw' ? -STEP : 0, y: -80 }, grab: { x: 0, y: 0 }, startRect: r0, base: adapter.rects(), bounds: { w: 1500, h: 800 }, outside: false };
      const rect = adapter.activeRect!(g);
      expect(rect.y).toBe(r0.y - 80);
      expect(rect.y + rect.h).toBe(r0.y + r0.h);
    }
  });
  it('stops at the grid edge and keeps the opposite edge there', () => {
    const w = drag('w', -99999, 0);
    expect(w.x).toBe(0);
    expect(w.x + w.w).toBe(12);
    const n = drag('n', 0, -99999);
    expect(n.y).toBe(0);
  });
});
