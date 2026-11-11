/** @vitest-environment jsdom */
import { describe, expect, it, vi } from 'vitest';
import type { GestureState, Rect } from '../../lib/motion-grid/types';
import { mountKeyboard } from '../../lib/motion-grid/motion-test-kit';
import { createDashAdapter, colsFor } from './dash-adapter';
import type { GridItem } from './format/grid-format';
import type { Cols } from './grid-data';

const it3 = (id: string, x: number, y: number, w = 6, h = 4): GridItem => ({ id: id as GridItem['id'], x, y, w, h });

function make(items: GridItem[], cols: Cols = 24, width = 1500) {
  const commit = vi.fn();
  const adapter = createDashAdapter({ cols: () => cols, width: () => width, items: () => items, commit });
  return { adapter, commit };
}

const STEP = (1500 - 9 * 23) / 24 + 9;

function gesture(adapter: ReturnType<typeof make>['adapter'], source: GestureState['source'], px: number, py: number, grab = { x: 0, y: 0 }, delta = { x: 0, y: 0 }): GestureState {
  const startRect = adapter.rects().get((source as { id: string }).id) ?? null;
  return { source, pointer: { x: px, y: py }, start: { x: 0, y: 0 }, delta, grab, startRect, base: adapter.rects(), bounds: { w: 1500, h: 800 }, outside: false };
}

describe('breakpoints', () => {
  it('24 / 12 / 1 columns by width', () => {
    expect([colsFor(1500), colsFor(1100), colsFor(900), colsFor(720), colsFor(400)]).toEqual([24, 24, 12, 12, 1]);
  });
});

describe('hit', () => {
  const { adapter } = make([it3('a', 0, 0)]);
  const wrap = document.createElement('div');
  wrap.dataset['dashId'] = 'a';
  wrap.innerHTML = '<button id="b"></button><i data-dash-resize="se"></i><span id="s"></span><div data-motion-nograb><b id="n"></b></div>';
  const ev = {} as PointerEvent;
  it('grabs from the card, resizes from a handle, never from a button or a nograb region', () => {
    expect(adapter.hit(wrap.querySelector('#s')!, ev)).toEqual({ kind: 'move', id: 'a' });
    expect(adapter.hit(wrap.querySelector('[data-dash-resize]')!, ev)).toEqual({ kind: 'resize', id: 'a', edge: 'se' });
    expect(adapter.hit(wrap.querySelector('#b')!, ev)).toBeNull();
    expect(adapter.hit(wrap.querySelector('#n')!, ev)).toBeNull();
  });
});

describe('move', () => {
  it('previews the target cell, packs with the held item pinned and commits the packed items', () => {
    const { adapter, commit } = make([it3('a', 0, 0), it3('b', 6, 0)]);
    adapter.begin?.({ kind: 'move', id: 'a' }, 'pointer');
    const g = gesture(adapter, { kind: 'move', id: 'a' }, 6 * STEP + 3, 0);
    const key = adapter.targetKey(g);
    expect(key).toBe('m:6,0');
    const t = adapter.preview(g, key);
    const a = t.rects.get('a')!;
    const b = t.rects.get('b')!;
    expect(a.x).toBeCloseTo(6 * STEP);
    expect(b.y).toBeGreaterThanOrEqual(a.y + a.h);
    adapter.commit(t, g);
    const out = commit.mock.calls[0]![0] as GridItem[];
    expect(out.find((i) => (i.id as string) === 'a')).toMatchObject({ x: 6, y: 0 });
    expect(out.find((i) => (i.id as string) === 'b')!.y).toBeGreaterThanOrEqual(4);
  });

  it('packs after a drop: a hole above the held item closes', () => {
    const { adapter } = make([it3('a', 0, 0), it3('b', 0, 10)]);
    adapter.begin?.({ kind: 'move', id: 'b' }, 'pointer');
    const g = gesture(adapter, { kind: 'move', id: 'b' }, 0, 60 * 40);
    const t = adapter.preview(g, adapter.targetKey(g));
    expect((t.payload as GridItem[]).find((i) => (i.id as string) === 'b')!.y).toBe(4);
  });
});

describe('resize', () => {
  const run = (edge: 'e' | 's' | 'se', dx: number, dy: number) => {
    const { adapter, commit } = make([it3('a', 0, 0), it3('b', 12, 0)]);
    adapter.begin?.({ kind: 'resize', id: 'a', edge }, 'pointer');
    const g = gesture(adapter, { kind: 'resize', id: 'a', edge }, 0, 0, { x: 0, y: 0 }, { x: dx, y: dy });
    const t = adapter.preview(g, adapter.targetKey(g));
    adapter.commit(t, g);
    return { item: (commit.mock.calls[0]![0] as GridItem[]).find((i) => (i.id as string) === 'a')!, rect: adapter.activeRect!(g) as Rect };
  };
  it('from the east edge changes width only', () => expect(run('e', 2 * STEP, 500).item).toMatchObject({ w: 8, h: 4 }));
  it('from the south edge changes height only', () => expect(run('s', 500, 80).item).toMatchObject({ w: 6, h: 6 }));
  it('from the corner changes both, and clamps to a minimum', () => {
    expect(run('se', STEP, 40).item).toMatchObject({ w: 7, h: 5 });
    expect(run('se', -9999, -9999).item).toMatchObject({ w: 3, h: 3 });
  });
});

describe('keyboard step', () => {
  it('moves one cell, resizes with shift, and refuses at the edge', () => {
    const { adapter } = make([it3('a', 0, 0)]);
    expect(adapter.step!('a', { dir: 'left', resize: false })).toBeNull();
    const right = adapter.step!('a', { dir: 'right', resize: false })!;
    expect((right.payload as GridItem[])[0]).toMatchObject({ x: 1 });
    const wider = adapter.step!('a', { dir: 'right', resize: true })!;
    expect((wider.payload as GridItem[])[0]).toMatchObject({ w: 7 });
  });
});

describe('columns', () => {
  it('twelve columns widen each cell and extent is the packed height', () => {
    const { adapter } = make([it3('a', 0, 0, 6, 4), it3('b', 6, 0, 6, 4)], 12, 900);
    const r = adapter.rects();
    expect(r.get('b')!.x).toBeGreaterThan(r.get('a')!.x + r.get('a')!.w);
    expect(adapter.extent!(r)).toBe(4 * 40 - 9);
  });
});

describe('keyboard session previews, then commits once', () => {
  function live() {
    let items = [it3('a', 0, 0), it3('b', 12, 0)];
    const commit = vi.fn((next: GridItem[]) => { items = next; });
    const adapter = createDashAdapter({ cols: () => 24, width: () => 1500, items: () => items, commit });
    const k = mountKeyboard(adapter, ['a', 'b']);
    return { k, commit, items: () => items };
  }
  it('three arrows then Escape leave the items and write nothing', () => {
    const t = live();
    const before = t.items();
    for (let i = 0; i < 3; i++) t.k.key('a', 'ArrowRight');
    t.k.key('a', 'Escape');
    expect(t.commit).not.toHaveBeenCalled();
    expect(t.items()).toBe(before);
  });
  it('three arrows then Enter commit once with the three-step result', () => {
    const t = live();
    for (let i = 0; i < 3; i++) t.k.key('a', 'ArrowRight');
    t.k.key('a', 'Enter');
    expect(t.commit).toHaveBeenCalledTimes(1);
    expect(t.items().find((i) => (i.id as string) === 'a')).toMatchObject({ x: 3 });
  });
});
