import { expect, test } from 'vitest';
import { applyDrop } from './drop';
import { META } from './meta';
import { addInstance, removeCell } from './model';
import { layoutGeometry, rectsAreSound } from './rects/layout-rects';
import { validate } from './persist';
import { COL_MIN } from './floors';
import type { DropTarget } from './layout.svelte';
import { repairSpans } from './spans';
import type { Layout, RowModel, SlotId } from './types';

const S = (n: string) => `terminal:${n}` as SlotId;
const W = 3300, H = 1250, G = 9;
const layoutOf = (rows: RowModel[]): Layout => ({ v: 6, rows, hidden: [], heroCollapsed: false, collapsed: [] });

const before = (): Layout => layoutOf([
  { id: 'r1', kind: 'flex', size: 0.51, slots: [{ id: S('mac'), fr: 0.33 }, { id: S('notify'), fr: 0.33 }, { id: S('videos'), fr: 0.34, span: 2 }] } as RowModel,
  { id: 'r2', kind: 'flex', size: 0.25, slots: [{ id: S('home'), fr: 1, span: 2 }], reserved: [{ of: S('videos'), at: 1 }] } as RowModel,
  { id: 'r3', kind: 'flex', size: 0.24, slots: [{ id: S('menus'), fr: 1 }], reserved: [{ of: S('home'), at: 0 }] } as RowModel,
]);

function uncovered(layout: Layout): number {
  const { rects } = layoutGeometry(layout, W, H, G);
  const cols = new Set<number>(); const rowsY = new Set<number>();
  for (const r of rects.values()) { cols.add(r.x); cols.add(r.x + r.w); rowsY.add(r.y); rowsY.add(r.y + r.h); }
  let hole = 0; const xs = [0, ...cols, W].sort((a, b) => a - b); const ys = [0, ...rowsY, H].sort((a, b) => a - b);
  for (let i = 0; i < xs.length - 1; i++) for (let j = 0; j < ys.length - 1; j++) {
    const cx = (xs[i]! + xs[i + 1]!) / 2, cy = (ys[j]! + ys[j + 1]!) / 2; const w = xs[i + 1]! - xs[i]!, h = ys[j + 1]! - ys[j]!;
    if (w <= G + 1 || h <= G + 1) continue;
    if (![...rects.values()].some((r) => cx > r.x && cx < r.x + r.w && cy > r.y && cy < r.y + r.h)) hole += w * h;
  }
  return hole / (W * H);
}

test('S7 RED: removing the emptied bottom-left component leaves no dead band', () => {
  const after = removeCell(before(), S('home'));
  expect(uncovered(after)).toBeLessThan(0.01);
});

test('S3/S9 RED: removing the third-column spanner of the healthy layout pushes a window off the right edge', () => {
  const after = removeCell(before(), S('videos'));
  const { rects } = layoutGeometry(after, W, H, G);
  const menus = rects.get(S('menus'))!;
  expect(menus.x + menus.w).toBeLessThanOrEqual(W);
  expect(menus.w).toBeGreaterThan(44);
});

test('S1: edge zones on the before layout all land', () => {
  const base = addInstance(before(), 'terminal', 'ghost', '', META).layout;
  const ghost = S('ghost');
  const refused: string[] = [];
  for (const slot of [S('mac'), S('notify'), S('videos'), S('home'), S('menus')]) {
    for (const zone of ['left', 'right', 'top', 'bottom'] as const) {
      const t: DropTarget = zone === 'top' || zone === 'bottom' ? { kind: 'stack', of: slot, edge: zone === 'top' ? 'above' : 'below' } : { kind: 'split', of: slot, side: zone, width: W };
      const next = applyDrop(base, ghost, t, META);
      if (next === base) refused.push(`${slot.slice(9)}:${zone}`);
    }
  }
  expect(refused).toEqual([]);
});

test('geometry fuzz: a drop the gate accepts leaves a sound layout', () => {
  let seed = 12345; const rnd = () => (seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296;
  let accepted = 0; const bad: string[] = [];
  const sound = (l: Layout) => rectsAreSound([...layoutGeometry(l, W, H, G).rects.values()], W, H, G);
  for (let run = 0; run < 200; run++) {
    let layout = before();
    for (let n = 0; n < 20; n++) {
      const ids = layout.rows.flatMap((r) => r.slots.map((s) => s.id));
      const id = ids[Math.floor(rnd() * ids.length)]!;
      const k = rnd(); let next = layout;
      if (k < 0.4) { const row = layout.rows[Math.floor(rnd() * layout.rows.length)]!; next = applyDrop(layout, id, { kind: 'row', row: row.id, index: Math.floor(rnd() * 4) }, META); }
      else if (k < 0.8) { const of = ids[Math.floor(rnd() * ids.length)]!; next = applyDrop(layout, id, { kind: 'stack', of, edge: rnd() < 0.5 ? 'above' : 'below' }, META); }
      else next = applyDrop(layout, id, { kind: 'new', after: rnd() < 0.3 ? null : layout.rows[Math.floor(rnd() * layout.rows.length)]!.id }, META);
      next = repairSpans(next);
      if (next === layout || !sound(next)) continue;
      accepted++; layout = next;
      const { rects } = layoutGeometry(layout, W, H, G);
      for (const [sid, r] of rects) if (r.h < 120 || r.w < COL_MIN) bad.push(`${sid}:${r.w}x${r.h}`);
      if (uncovered(layout) > 0.011) bad.push('hole');
    }
  }
  expect(accepted).toBeGreaterThan(50);
  expect(bad).toEqual([]);
});

test('the gate refuses a window under the pane height, one under the column floor and a hole', () => {
  expect(rectsAreSound([{ x: 0, y: 0, w: 600, h: 100 }], 600, 100, G)).toBe(false);
  expect(rectsAreSound([{ x: 0, y: 0, w: 200, h: 400 }], 200, 400, G)).toBe(false);
  expect(rectsAreSound([{ x: 0, y: 0, w: 600, h: 400 }], 600, 400, G)).toBe(true);
  expect(rectsAreSound([{ x: 0, y: 0, w: 600, h: 150 }], 600, 400, G)).toBe(false);
});

test('S5: validate heals a stored layout whose bottom window has no column of its own', () => {
  const stored = layoutOf([
    { id: 'r1', kind: 'flex', size: 700, slots: [{ id: S('mac'), fr: 0.5, span: 2 }, { id: S('notify'), fr: 0.5, span: 2 }] } as RowModel,
    { id: 'r2', kind: 'flex', size: 500, slots: [{ id: S('menus'), fr: 1 }], reserved: [{ of: S('mac'), at: 0 }, { of: S('notify'), at: 1 }] } as RowModel,
  ]);
  const res = validate(JSON.parse(JSON.stringify(stored)), META, 'terminal');
  expect(res.refusal).toBeNull();
  const { rects } = layoutGeometry(res.layout!, W, H, G);
  for (const [id, r] of rects) expect(r.w, id).toBeGreaterThan(COL_MIN);
});
