import { describe, expect, it } from 'vitest';
import {
  buildZones,
  candidatesAt,
  compassAt,
  nextTarget,
  type Candidate,
  type Dragged,
  type SnapCell,
  type SnapStrip,
  type SnapWindow,
  type Snapshot,
} from './drop-grammar';

const G = 9;
const STRIP_H = 28;

function win(id: string, x: number, y: number, w: number, h: number, tabs: string[] = [id + '1'], centres?: number[]): SnapWindow {
  const strip: SnapStrip = {
    x, y, w, h: STRIP_H,
    tabs: tabs.map((t, i) => ({ id: t, centre: centres?.[i] ?? x + (w * (i + 0.5)) / tabs.length })),
  };
  return { id, x, y, w, h, takesTabs: true, tabs, strip };
}

const cell = (owner: string | null, x: number, width: number): SnapCell => ({ owner, x, width });

function working(): Snapshot {
  return {
    width: 1000, height: 700, gutter: G,
    rows: [
      { id: 'r0', top: 0, height: 340, cells: [cell('A', 0, 320), cell('B', 329, 320), cell('C', 658, 342)] },
      { id: 'r1', top: 349, height: 351, cells: [cell('D', 0, 320), cell('E', 329, 320), cell('C', 658, 342)] },
    ],
    windows: [
      win('A', 0, 0, 320, 340, ['a1', 'a2'], [80, 240]),
      win('B', 329, 0, 320, 340),
      win('C', 658, 0, 342, 700),
      win('D', 0, 349, 320, 351),
      win('E', 329, 349, 320, 351),
    ],
  };
}

function unaligned(): Snapshot {
  return {
    width: 1000, height: 700, gutter: G,
    rows: [
      { id: 'r0', top: 0, height: 220, cells: [cell('A', 0, 320), cell('B', 329, 671)] },
      { id: 'r1', top: 229, height: 220, cells: [cell('D', 0, 400), cell('E', 409, 591)] },
      { id: 'r2', top: 458, height: 242, cells: [cell('F', 0, 1000)] },
    ],
    windows: [win('A', 0, 0, 320, 220), win('B', 329, 0, 671, 220), win('D', 0, 229, 400, 220), win('E', 409, 229, 591, 220), win('F', 0, 458, 1000, 242)],
  };
}

const tab: Dragged = { kind: 'tab', tab: 'x' };
const zones = buildZones(working());
const first = (z = zones, x = 0, y = 0, d: Dragged = tab): Candidate | undefined => candidatesAt(z, { x, y }, d)[0];

describe('zone table on the Working shape (one point per target)', () => {
  it('T1 strip caret, T2 to T6: the five compass icons of a window resolve to their drops', () => {
    expect(first(zones, 130, 15)?.target).toEqual({ kind: 'strip', slot: 'A', index: 1 });
    expect(first(zones, 160, 184)?.target).toEqual({ kind: 'middle', slot: 'A' });
    expect(first(zones, 116, 184)?.target).toEqual({ kind: 'split', of: 'A', side: 'left' });
    expect(first(zones, 204, 184)?.target).toEqual({ kind: 'split', of: 'A', side: 'right' });
    expect(first(zones, 160, 140)?.target).toEqual({ kind: 'stack', of: 'A', edge: 'above' });
    expect(first(zones, 160, 228)?.target).toEqual({ kind: 'stack', of: 'A', edge: 'below' });
  });

  it('over the window body but not on an icon there is no drop, where an edge zone used to be', () => {
    for (const [x, y] of [[50, 200], [160, 48], [160, 320], [138, 184], [160, 162]] as [number, number][]) {
      expect(candidatesAt(zones, { x, y }, tab)).toEqual([]);
    }
  });

  it('the plate is a function of the lift snapshot and the window alone: it does not follow the pointer', () => {
    const a = compassAt(zones, { x: 20, y: 60 }, tab);
    const b = compassAt(zones, { x: 300, y: 320 }, tab);
    expect(a?.window).toBe('A');
    expect(b).toEqual(a);
    expect(a?.slots.map((s) => s.dir)).toEqual(['centre', 'up', 'down', 'left', 'right']);
    expect(a?.slots.every((s) => s.rect.w >= 36 && s.rect.w <= 44 && s.rect.w === s.rect.h)).toBe(true);
    expect(compassAt(zones, { x: 160, y: 15 }, tab)).toBeNull();
    expect(compassAt(zones, { x: 160, y: 184 }, { kind: 'window', id: 'A' })).toBeNull();
  });

  it('a short window shrinks its icons to fit but never under 18 px, so the plate fits the 104 px row floor', () => {
    const s = working();
    s.windows[1] = win('B', 329, 0, 320, 104);
    const geo = compassAt(buildZones(s), { x: 489, y: 80 }, tab);
    expect(geo?.slots[0]?.rect.w).toBe(18);
    expect(geo!.plate.y).toBeGreaterThanOrEqual(28);
    expect(geo!.plate.y + geo!.plate.h).toBeLessThanOrEqual(104);
  });

  it('T7 to T10: bands on all four sides', () => {
    const left = first(zones, 10, 300)?.target;
    expect(left).toMatchObject({ kind: 'seam' });
    expect(left?.kind === 'seam' && left.rows).toEqual([
      { row: 'r0', left: null, right: 'A' },
      { row: 'r1', left: null, right: 'D' },
    ]);
    const right = first(zones, 990, 300)?.target;
    expect(right?.kind === 'seam' && right.rows.map((r) => [r.left, r.right])).toEqual([['C', null], ['C', null]]);
    expect(first(zones, 500, 2)?.target).toEqual({ kind: 'new', after: null });
    expect(first(zones, 500, -10)?.target).toEqual({ kind: 'new', after: null });
    expect(first(zones, 500, 690)?.target).toEqual({ kind: 'new', after: 'r1' });
    expect(first(zones, -30, 100)?.label).toBe('opscenter.drop.column_left');
  });

  it('T11 seam over a run of two rows; T12 a one-row run when seams do not line up', () => {
    const c = first(zones, 324.5, 100);
    expect(c?.target).toMatchObject({ kind: 'seam' });
    expect(c?.target.kind === 'seam' && c.target.rows).toEqual([
      { row: 'r0', left: 'A', right: 'B' },
      { row: 'r1', left: 'D', right: 'E' },
    ]);
    expect(c?.label).toBe('opscenter.drop.column');
    const u = buildZones(unaligned());
    const one = first(u, 324.5, 100);
    expect(one?.target.kind === 'seam' && one.target.rows).toEqual([{ row: 'r0', left: 'A', right: 'B' }]);
    const two = first(u, 404.5, 300);
    expect(two?.target.kind === 'seam' && two.target.rows).toEqual([{ row: 'r1', left: 'D', right: 'E' }]);
  });

  it('T13 full-width row seam, T14 part-width run beside a spanner', () => {
    expect(first(buildZones(unaligned()), 500, 224)?.target).toEqual({ kind: 'new', after: 'r0' });
    const run = first(zones, 100, 344);
    expect(run?.target).toEqual({ kind: 'stack-run', of: ['A', 'B'], edge: 'below' });
    expect(run?.label).toBe('opscenter.drop.row');
  });

  it('labels and reflows: T1 and T2 never reflow, the rest do', () => {
    expect(first(zones, 130, 15)).toMatchObject({ label: '', reflows: false });
    expect(first(zones, 160, 184)).toMatchObject({ label: 'opscenter.tabs.drop_center', reflows: false });
    expect(first(zones, 160, 184, { kind: 'window', id: 'E' })?.label).toBe('opscenter.drop.add_tabs');
    expect(first(zones, 116, 184)).toMatchObject({ label: 'opscenter.tabs.drop_left', reflows: true, compass: 'left' });
  });

  it('more than 48 px outside there is no target', () => {
    expect(candidatesAt(zones, { x: -60, y: 100 }, tab)).toEqual([]);
    expect(candidatesAt(zones, { x: 500, y: 760 }, tab)).toEqual([]);
  });
});

describe('priority and ties', () => {
  it('a strip wins over a seam except its top 10 px, and over a row seam only below the seam zone', () => {
    expect(first(zones, 315, 15)?.target.kind).toBe('strip');
    expect(first(zones, 315, 2)?.target.kind).not.toBe('strip');
    expect(first(zones, 100, 351)?.target.kind).toBe('stack-run');
    expect(first(zones, 100, 365)?.target.kind).toBe('strip');
  });

  it('corner ties go to left or right, otherwise the nearer edge', () => {
    expect(first(zones, -10, -10)?.key).toBe('band:left');
    expect(first(zones, 10, 690)?.key).toBe('band:left');
    expect(first(zones, 990, 690)?.key).toBe('band:right');
    expect(first(zones, 10, 3)?.key).toBe('band:top');
    expect(first(zones, 990, 695)?.key).toBe('band:bottom');
  });

  it('at a junction the nearer seam line wins', () => {
    expect(first(zones, 645, 346)?.target.kind).toBe('stack-run');
    expect(first(zones, 645, 330)?.target.kind).toBe('seam');
  });

  it('a compass icon is one candidate: splits rank 5, the centre 6', () => {
    expect(candidatesAt(zones, { x: 116, y: 184 }, tab).map((c) => c.priority)).toEqual([5]);
    expect(candidatesAt(zones, { x: 160, y: 184 }, tab).map((c) => c.priority)).toEqual([6]);
  });

  it('own window: none for a window over itself, none for a tab over its own middle or only-tab edges', () => {
    expect(candidatesAt(zones, { x: 160, y: 184 }, { kind: 'window', id: 'A' })).toEqual([]);
    expect(candidatesAt(zones, { x: 116, y: 184 }, { kind: 'window', id: 'A' })).toEqual([]);
    expect(candidatesAt(zones, { x: 160, y: 15 }, { kind: 'window', id: 'A' })).toEqual([]);
    expect(candidatesAt(zones, { x: 160, y: 184 }, { kind: 'tab', tab: 'a1' })).toEqual([]);
    expect(first(zones, 116, 184, { kind: 'tab', tab: 'a1' })?.target).toEqual({ kind: 'split', of: 'A', side: 'left' });
    expect(candidatesAt(zones, { x: 160, y: 538 }, { kind: 'tab', tab: 'D1' })).toEqual([]);
    expect(candidatesAt(zones, { x: 116, y: 538 }, { kind: 'tab', tab: 'D1' })).toEqual([]);
    expect(compassAt(zones, { x: 160, y: 538 }, { kind: 'tab', tab: 'D1' })).toBeNull();
  });

  it('a window with no middle has a compass whose centre icon takes no drop', () => {
    const s = working();
    s.windows[1] = { ...s.windows[1]!, takesTabs: false, tabs: [], strip: null };
    const z = buildZones(s);
    expect(first(z, 445, 170)?.target).toEqual({ kind: 'split', of: 'B', side: 'left' });
    expect(candidatesAt(z, { x: 489, y: 170 }, tab)).toEqual([]);
    expect(compassAt(z, { x: 489, y: 170 }, tab)?.slots[0]).toMatchObject({ dir: 'centre', allowed: false });
  });
});

describe('priority-aware hold', () => {
  const run = (points: [number, number][], d: Dragged = tab, z = zones): (Candidate | null)[] => {
    let held: Candidate | null = null;
    return points.map(([x, y]) => {
      const fresh = candidatesAt(z, { x, y }, d)[0] ?? null;
      held = nextTarget(held, fresh, { x, y }, null);
      return held;
    });
  };

  it('a compass icon is held by its own rect alone: the gap between icons holds nothing, the next icon wins at once', () => {
    const left = first(zones, 116, 184)!;
    expect(nextTarget(left, first(zones, 130, 184) ?? null, { x: 130, y: 184 }, null)).toBe(left);
    expect(nextTarget(left, first(zones, 138, 184) ?? null, { x: 138, y: 184 }, null)).toBeNull();
    expect(nextTarget(left, first(zones, 142, 184) ?? null, { x: 142, y: 184 }, null)?.target.kind).toBe('middle');
  });

  it('an armed placeholder never holds a compass icon, even with the pointer inside it', () => {
    const left = first(zones, 116, 184)!;
    const placeholder = { x: 0, y: 28, w: 160, h: 312 };
    const p = { x: 160, y: 184 };
    expect(nextTarget(left, first(zones, p.x, p.y) ?? null, p, placeholder)?.target.kind).toBe('middle');
    const q = { x: 60, y: 100 };
    expect(nextTarget(left, first(zones, q.x, q.y) ?? null, q, placeholder)).toBeNull();
  });

  it('a held icon yields the left band, the bottom band, a seam', () => {
    const left = first(zones, 116, 184)!;
    expect(nextTarget(left, first(zones, 10, 200)!, { x: 10, y: 200 }, null)?.key).toBe('band:left');
    const bottom = first(zones, 160, 582)!;
    expect(bottom.target).toEqual({ kind: 'stack', of: 'D', edge: 'below' });
    expect(nextTarget(bottom, first(zones, 100, 690)!, { x: 100, y: 690 }, null)?.key).toBe('band:bottom');
    const icon = first(zones, 445, 184)!;
    expect(icon.target).toEqual({ kind: 'split', of: 'B', side: 'left' });
    expect(nextTarget(icon, first(zones, 335, 200)!, { x: 335, y: 200 }, null)?.target.kind).toBe('seam');
  });

  it('sliding along a strip walks the caret index and honours the dead band', () => {
    const s = working();
    s.windows[0] = win('A', 0, 0, 320, 340, ['a1', 'a2', 'a3'], [50, 150, 250]);
    const z = buildZones(s);
    const idx = (xs: number[]): number[] =>
      run(xs.map((x) => [x, 15] as [number, number]), tab, z).map((c) => (c?.target.kind === 'strip' ? c.target.index : -1));
    expect(idx([10, 40, 56, 100, 148, 160, 246, 262, 300])).toEqual([0, 0, 1, 1, 1, 2, 2, 3, 3]);
    expect(idx([40, 50, 52, 56, 50, 48])).toEqual([0, 0, 0, 1, 1, 1]);
    const own = candidatesAt(z, { x: 100, y: 15 }, { kind: 'tab', tab: 'a2' })[0];
    expect(own?.target).toEqual({ kind: 'strip', slot: 'A', index: 1 });
  });

  it('leaving a strip vertically re-picks at once', () => {
    const held = first(zones, 100, 15)!;
    expect(held.target.kind).toBe('strip');
    const p = { x: 160, y: 184 };
    expect(nextTarget(held, first(zones, p.x, p.y) ?? null, p, null)?.target.kind).toBe('middle');
    const q = { x: 50, y: 100 };
    expect(nextTarget(held, first(zones, q.x, q.y) ?? null, q, null)).toBeNull();
  });
});
