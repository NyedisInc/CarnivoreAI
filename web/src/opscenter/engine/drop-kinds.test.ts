import { expect, test } from 'vitest';
import { applyDrop } from './drop';
import { META } from './meta';
import { removeCell } from './model';
import { layoutGeometry, rectsAreSound } from './rects/layout-rects';
import { repairSpans } from './spans';
import type { DropTarget } from './layout.svelte';
import type { Layout, RowModel, SlotId } from './types';

const S = (n: string) => `terminal:${n}` as SlotId;
const W = 3300, H = 1250, G = 9;
const layoutOf = (rows: RowModel[]): Layout => ({ v: 6, rows, hidden: [], heroCollapsed: false, collapsed: [] });
const rectsOf = (l: Layout) => layoutGeometry(l, W, H, G).rects;
const sound = (l: Layout) => rectsAreSound([...rectsOf(l).values()], W, H, G);
const near = (a: number, b: number) => Math.abs(a - b) <= 1;

const working = (): Layout => layoutOf([
  { id: 'r1', kind: 'flex', size: 0.5, slots: [{ id: S('a'), fr: 0.33 }, { id: S('b'), fr: 0.33 }, { id: S('c'), fr: 0.34, span: 2 }] } as RowModel,
  { id: 'r2', kind: 'flex', size: 0.5, slots: [{ id: S('d'), fr: 0.3 }, { id: S('e'), fr: 0.3 }, { id: S('g'), fr: 0.4 }], reserved: [{ of: S('c'), at: 3 }] } as RowModel,
]);

const unaligned = (): Layout => layoutOf([
  { id: 'r1', kind: 'flex', size: 0.34, slots: [{ id: S('a'), fr: 0.2 }, { id: S('g'), fr: 0.3 }, { id: S('b'), fr: 0.5 }] } as RowModel,
  { id: 'r2', kind: 'flex', size: 0.33, slots: [{ id: S('c'), fr: 0.4 }, { id: S('d'), fr: 0.6 }] } as RowModel,
  { id: 'r3', kind: 'flex', size: 0.33, slots: [{ id: S('f'), fr: 0.4 }, { id: S('h'), fr: 0.6 }] } as RowModel,
]);

const ids = (l: Layout) => l.rows.flatMap((r) => r.slots.map((s) => s.id));

test('split: every window but the target and the arrival keeps its rect, on both shapes and both sides', () => {
  let landed = 0;
  for (const make of [working, unaligned]) {
    const start = make();
    const rest = rectsOf(removeCell(start, S('g')));
    for (const of of ids(start).filter((id) => id !== S('g'))) {
      for (const side of ['left', 'right'] as const) {
        const next = applyDrop(start, S('g'), { kind: 'split', of, side, width: W }, META);
        if (next === start) continue;
        landed += 1;
        expect(sound(next), `${of} ${side}`).toBe(true);
        const now = rectsOf(next);
        const arrival = now.get(S('g'))!, target = now.get(of)!, before = rest.get(of)!;
        expect(near(arrival.y, before.y) && near(arrival.h, before.h) && near(target.h, before.h), `${of} ${side} height`).toBe(true);
        expect(near(Math.min(arrival.x, target.x), before.x) && near(Math.max(arrival.x + arrival.w, target.x + target.w), before.x + before.w), `${of} ${side} columns`).toBe(true);
        expect(side === 'left' ? arrival.x < target.x : arrival.x > target.x).toBe(true);
        for (const [id, r] of rest) {
          if (id === of || id === S('g')) continue;
          const moved = now.get(id)!;
          expect(near(moved.x, r.x) && near(moved.y, r.y) && near(moved.w, r.w) && near(moved.h, r.h), `${of} ${side}: ${id} moved`).toBe(true);
        }
      }
    }
  }
  expect(landed).toBeGreaterThan(8);
});

test('split a spanning window: the arrival covers every row it covers', () => {
  const next = applyDrop(working(), S('g'), { kind: 'split', of: S('c'), side: 'left', width: W }, META);
  expect(next).not.toBe(working());
  const now = rectsOf(next);
  expect(near(now.get(S('g'))!.h, now.get(S('c'))!.h)).toBe(true);
  expect(now.get(S('g'))!.h).toBeGreaterThan(H / 2);
});

test('seam: the edge columns are full height, on both shapes', () => {
  for (const make of [working, unaligned]) {
    const start = make();
    const rest = removeCell(start, S('g'));
    const edge = (side: 'left' | 'right'): DropTarget => ({
      kind: 'seam',
      width: W,
      rows: rest.rows.map((row) => {
        const reservedAt = (at: number) => row.reserved?.find((one) => one.at === at)?.of;
        const cell = side === 'left' ? (reservedAt(0) ?? row.slots[0]!.id) : (reservedAt(row.slots.length) ?? row.slots.at(-1)!.id);
        return { row: row.id, left: side === 'left' ? null : cell, right: side === 'left' ? cell : null };
      }),
    });
    for (const side of ['left', 'right'] as const) {
      const next = applyDrop(start, S('g'), edge(side), META);
      expect(next, `${side} landed`).not.toBe(start);
      expect(sound(next), side).toBe(true);
      const arrival = rectsOf(next).get(S('g'))!;
      expect(near(arrival.y, 0) && near(arrival.h, H), `${side} full height ${JSON.stringify(arrival)}`).toBe(true);
      expect(side === 'left' ? near(arrival.x, 0) : near(arrival.x + arrival.w, W)).toBe(true);
    }
  }
});

test('seam: an interior column spans exactly its run and never cuts a window', () => {
  const start = unaligned();
  const target: DropTarget = { kind: 'seam', width: W, rows: [{ row: 'r2', left: S('c'), right: S('d') }, { row: 'r3', left: S('f'), right: S('h') }] };
  const next = applyDrop(start, S('g'), target, META);
  expect(next).not.toBe(start);
  expect(sound(next)).toBe(true);
  const now = rectsOf(next);
  const arrival = now.get(S('g'))!, c = now.get(S('c'))!, f = now.get(S('f'))!;
  expect(near(arrival.y, c.y) && near(arrival.y + arrival.h, f.y + f.h)).toBe(true);
  expect(arrival.x).toBeGreaterThan(c.x + c.w - 2);
  expect(now.get(S('d'))!.x).toBeGreaterThan(arrival.x + arrival.w - 2);
  expect(now.get(S('a'))!.y).toBe(0);
});

test('seam: a one-row run is an ordinary insert between two windows', () => {
  const start = unaligned();
  const target: DropTarget = { kind: 'seam', width: W, rows: [{ row: 'r2', left: S('c'), right: S('d') }] };
  const next = applyDrop(start, S('g'), target, META);
  expect(next).not.toBe(start);
  const now = rectsOf(next);
  expect(near(now.get(S('g'))!.h, now.get(S('c'))!.h)).toBe(true);
  expect(sound(next)).toBe(true);
});

test('seam: a full width bottom window dragged to the left band is a full height left column', () => {
  const start = layoutOf([
    { id: 'r1', kind: 'flex', size: 0.5, slots: [{ id: S('a'), fr: 0.5 }, { id: S('b'), fr: 0.5 }] } as RowModel,
    { id: 'r2', kind: 'flex', size: 0.5, slots: [{ id: S('c'), fr: 1 }] } as RowModel,
  ]);
  const target: DropTarget = { kind: 'seam', width: W, rows: [{ row: 'r1', left: null, right: S('a') }, { row: 'r2', left: null, right: S('c') }] };
  const next = applyDrop(start, S('c'), target, META);
  expect(next).not.toBe(start);
  expect(next.rows).toHaveLength(1);
  expect(sound(next)).toBe(true);
  const c = rectsOf(next).get(S('c'))!;
  expect(near(c.x, 0) && near(c.y, 0) && near(c.h, H)).toBe(true);
});

test('seam: refused only when no row is left', () => {
  const start = layoutOf([{ id: 'r1', kind: 'flex', size: 1, slots: [{ id: S('a'), fr: 1 }] } as RowModel]);
  const none: DropTarget = { kind: 'seam', width: W, rows: [{ row: 'r9' as RowModel['id'], left: null, right: S('a') }] };
  expect(applyDrop(start, S('a'), none, META)).toBe(start);
});

test('stack-run: a new row under part of a row takes the run columns and the spanner grows', () => {
  const start = working();
  const next = applyDrop(start, S('g'), { kind: 'stack-run', of: [S('a'), S('b')], edge: 'below' }, META);
  expect(next).not.toBe(start);
  expect(sound(next)).toBe(true);
  const now = rectsOf(next);
  const a = now.get(S('a'))!, b = now.get(S('b'))!, g = now.get(S('g'))!;
  expect(near(g.x, a.x) && near(g.x + g.w, b.x + b.w)).toBe(true);
  expect(g.y).toBeGreaterThan(a.y + a.h - 2);
  expect(near(now.get(S('c'))!.h, H)).toBe(true);
});

test('stack-run of one cell is the stack', () => {
  const start = working();
  const one = applyDrop(start, S('g'), { kind: 'stack-run', of: [S('a')], edge: 'below' }, META);
  const stack = applyDrop(start, S('g'), { kind: 'stack', of: S('a'), edge: 'below' }, META);
  expect(one).toEqual(stack);
});

test('stack-run refuses cells that are not side by side', () => {
  const start = working();
  expect(applyDrop(start, S('g'), { kind: 'stack-run', of: [S('a'), S('c')], edge: 'below' }, META)).toBe(start);
});

test('reservations are drawn in the x order of the row above, so the stack tie case lands', () => {
  const start = layoutOf([
    { id: 'r1', kind: 'flex', size: 0.5, slots: [{ id: S('a'), fr: 0.33 }, { id: S('b'), fr: 0.33 }, { id: S('c'), fr: 0.34, span: 2 }] } as RowModel,
    { id: 'r2', kind: 'flex', size: 0.5, slots: [{ id: S('d'), fr: 0.3 }, { id: S('e'), fr: 0.3 }, { id: S('g'), fr: 0.4 }], reserved: [{ of: S('c'), at: 3 }] } as RowModel,
  ]);
  const next = applyDrop(start, S('b'), { kind: 'stack', of: S('d'), edge: 'above' }, META);
  expect(next).not.toBe(start);
  expect(sound(next)).toBe(true);
  const second = layoutOf([
    { id: 'r1', kind: 'flex', size: 0.25, slots: [{ id: S('b'), fr: 0.4925 }, { id: S('c'), fr: 0.5075, span: 3 }] } as RowModel,
    { id: 'r3', kind: 'flex', size: 0.25, slots: [{ id: S('a'), fr: 1 }], reserved: [{ of: S('c'), at: 1 }] } as RowModel,
    { id: 'r2', kind: 'flex', size: 0.5, slots: [{ id: S('d'), fr: 0.3 }, { id: S('e'), fr: 0.3 }, { id: S('g'), fr: 0.4 }], reserved: [{ of: S('c'), at: 3 }] } as RowModel,
  ]);
  const landed = applyDrop(second, S('a'), { kind: 'stack', of: S('e'), edge: 'below' }, META);
  expect(landed).not.toBe(second);
  expect(sound(landed)).toBe(true);
});

test('fuzz: no drop of any kind leaves two windows overlapping', () => {
  let seed = 4242; const rnd = () => (seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296;
  const overlaps = (l: Layout): boolean => {
    const rs = [...rectsOf(l).values()];
    return rs.some((a, i) => rs.slice(i + 1).some((b) => a.x < b.x + b.w - 1 && b.x < a.x + a.w - 1 && a.y < b.y + b.h - 1 && b.y < a.y + a.h - 1));
  };
  let landed = 0; const bad: string[] = [];
  for (let run = 0; run < 150; run++) {
    let layout = [working, unaligned][run % 2]!();
    for (let n = 0; n < 12; n++) {
      const all = ids(layout);
      const id = all[Math.floor(rnd() * all.length)]!;
      const other = () => all[Math.floor(rnd() * all.length)]!;
      const row = layout.rows[Math.floor(rnd() * layout.rows.length)]!;
      const k = rnd(); let target: DropTarget;
      if (k < 0.3) target = { kind: 'stack', of: other(), edge: rnd() < 0.5 ? 'above' : 'below' };
      else if (k < 0.55) target = { kind: 'split', of: other(), side: rnd() < 0.5 ? 'left' : 'right', width: W };
      else if (k < 0.75) target = { kind: 'stack-run', of: [other(), other()], edge: 'below' };
      else if (k < 0.9) {
        const cells = layout.rows.map((r) => ({ row: r.id, left: null as SlotId | null, right: r.slots[0]!.id }));
        target = { kind: 'seam', width: W, rows: cells.slice(0, 1 + Math.floor(rnd() * cells.length)) };
      } else target = { kind: 'row', row: row.id, index: Math.floor(rnd() * 4) };
      const next = repairSpans(applyDrop(layout, id, target, META));
      if (next === layout || !sound(next)) continue;
      landed++; layout = next;
      if (overlaps(layout)) bad.push(JSON.stringify(target));
    }
  }
  expect(landed).toBeGreaterThan(100);
  expect(bad).toEqual([]);
});
