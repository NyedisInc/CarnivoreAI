/** @vitest-environment jsdom */
import { describe, expect, test, vi } from 'vitest';
import type { GestureState, Rect, Source } from '../../../lib/motion-grid';
import type { LayoutStore } from '../layout.svelte';
import { removeCell } from '../model';
import { repairSpans } from '../spans';
import type { Layout, SlotId } from '../types';
import { applyDivider, dividerSpecs } from './dividers';
import { layoutGeometry } from './layout-rects';
import { createRowsAdapter } from './rows-adapter';

const H = 'terminal:@primary' as SlotId;
const AF = 'terminal:row:2' as SlotId;
const CW = 'terminal:row:3' as SlotId;
const AC = 'terminal:row:4' as SlotId;
const MA = 'terminal:row:5' as SlotId;
const W = 1400;
const HT = 800;
const G = 9;

function stacks(): Layout {
  return repairSpans({
    v: 6,
    rows: [
      { id: 'r1', kind: 'flex', size: 0.45, slots: [{ id: H, fr: 1, span: 3 }, { id: AF, fr: 0.5, span: 2 }, { id: AC, fr: 0.5 }] },
      { id: 'r2', kind: 'flex', size: 0.2, slots: [{ id: MA, fr: 1, span: 2 }], reserved: [{ of: H, at: 0 }, { of: AF, at: 0 }] },
      { id: 'r3', kind: 'flex', size: 0.35, slots: [{ id: CW, fr: 1 }], reserved: [{ of: H, at: 0 }, { of: MA, at: 1 }] },
    ],
    hidden: [],
    heroCollapsed: false,
    collapsed: [],
  } as Layout);
}

function sameLine(): Layout {
  return repairSpans({
    v: 6,
    rows: [
      { id: 'r1', kind: 'flex', size: 0.5, slots: [{ id: H, fr: 1, span: 2 }, { id: AF, fr: 0.5 }, { id: AC, fr: 0.5 }] },
      { id: 'r2', kind: 'flex', size: 0.5, slots: [{ id: CW, fr: 0.5 }, { id: MA, fr: 0.5 }], reserved: [{ of: H, at: 0 }] },
    ],
    hidden: [],
    heroCollapsed: false,
    collapsed: [],
  } as Layout);
}

const rectsOf = (layout: Layout): Map<SlotId, Rect> => layoutGeometry(layout, W, HT, G).rects;
const specsOf = (layout: Layout) => dividerSpecs(layout, layoutGeometry(layout, W, HT, G).tracks, { width: W, height: HT }, G, true);

describe('independent columns', () => {
  test('dragging one column past a neighbour column\'s split moves only that column', () => {
    const layout = stacks();
    const before = rectsOf(layout);
    const spec = specsOf(layout).find((one) => one.kind === 'row' && one.seg!.below.includes(CW))!;
    const after = rectsOf(applyDivider(layout, spec, 0, -300));
    expect(after.get(CW)!.h).toBeGreaterThan(before.get(CW)!.h + 250);
    expect(after.get(AF)!.h).toBeLessThan(before.get(AF)!.h - 250);
    for (const id of [H, AC, MA]) expect(after.get(id)).toEqual(before.get(id));
  });

  test('two columns sharing one row line each get a handle and move alone', () => {
    const layout = sameLine();
    const specs = specsOf(layout).filter((one) => one.kind === 'row');
    expect(specs).toHaveLength(2);
    const before = rectsOf(layout);
    const left = specs.find((one) => one.seg!.above.includes(AF))!;
    const after = rectsOf(applyDivider(layout, left, 0, 80));
    expect(after.get(AF)!.h).toBeGreaterThan(before.get(AF)!.h + 70);
    for (const id of [H, AC, MA]) expect(after.get(id)).toEqual(before.get(id));
  });
});

describe('resize from every side and corner', () => {
  test('every cell has a divider on each side and corner that has a neighbour, and none on the window border', () => {
    for (const layout of [stacks(), sameLine()]) {
      const specs = specsOf(layout);
      const hit = (x: number, y: number): boolean => specs.some((s) => x >= s.rect.x && x <= s.rect.x + s.rect.w && y >= s.rect.y && y <= s.rect.y + s.rect.h);
      const covers = (x: number, y: number): boolean => [...rectsOf(layout).values()].some((r) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h);
      for (const r of rectsOf(layout).values()) {
        const left = r.x - G / 2;
        const right = r.x + r.w + G / 2;
        const top = r.y - G / 2;
        const bottom = r.y + r.h + G / 2;
        const midX = r.x + r.w / 2;
        const midY = r.y + r.h / 2;
        if (left > 0) expect(hit(left, midY)).toBe(true);
        if (right < W) expect(hit(right, midY)).toBe(true);
        if (top > 0) expect(hit(midX, top)).toBe(true);
        if (bottom < HT) expect(hit(midX, bottom)).toBe(true);
        for (const [x, y, sx, sy] of [[left, top, left, top], [right, top, right, top], [left, bottom, left, bottom], [right, bottom, right, bottom]] as const) {
          if (x > 0 && x < W && y > 0 && y < HT && covers(x + (x === left ? -G : G), y) && covers(x, y + (y === top ? -G : G))) expect(hit(sx, sy)).toBe(true);
        }
      }
    }
  });
});

describe('a cell leaves a stack', () => {
  test('the cell left in its column fills the freed space at once and no empty row remains', () => {
    const layout = removeCell(stacks(), CW);
    const rects = rectsOf(layout);
    expect(rects.get(AF)!.y + rects.get(AF)!.h).toBe(HT);
    expect(layout.rows.every((row) => row.slots.length > 0)).toBe(true);
  });
});

describe('what a drag shows is what the release writes', () => {
  test('the committed layout draws the previewed rects, down to the floor of the cells it touches and no further', () => {
    const state = { layout: stacks() };
    const commits: Layout[] = [];
    const store = { page: 'terminal', state, snapshot: () => state.layout, commitLayout: vi.fn((next: Layout) => { commits.push(next); state.layout = next; }) } as unknown as LayoutStore;
    const container = document.createElement('div');
    const adapter = createRowsAdapter({ store, box: () => ({ width: W, height: HT }), gutter: G, wide: () => true, zoomed: () => null, container: () => container, onState: () => {} });
    const spec = specsOf(state.layout).find((one) => one.kind === 'row' && one.seg!.above.includes(AF))!;
    const source: Source = { kind: 'divider', id: spec.id };
    for (const dy of [120, 5000]) {
      state.layout = stacks();
      adapter.begin!(source, 'pointer');
      const g: GestureState = { source, pointer: { x: 0, y: 0 }, start: { x: 0, y: 0 }, delta: { x: 0, y: dy }, grab: { x: 0, y: 0 }, startRect: null, base: adapter.rects(), bounds: { w: W, h: HT }, outside: false };
      const shown = adapter.preview(g, adapter.targetKey(g));
      adapter.commit(shown, g);
      const written = rectsOf(commits.at(-1)!);
      for (const [id, rect] of shown.rects) {
        const got = written.get(id as never)!;
        expect(Math.abs(got.y - rect.y)).toBeLessThanOrEqual(1);
        expect(Math.abs(got.h - rect.h)).toBeLessThanOrEqual(1);
      }
    }
    expect(rectsOf(commits.at(-1)!).get(CW)!.h).toBe(104);
    expect(rectsOf(commits.at(-1)!).get(CW)!.y + 104).toBe(HT);
  });
});
