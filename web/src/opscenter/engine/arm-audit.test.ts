import { expect, test } from 'vitest';
import { applyDrop } from './drop';
import { COL_MIN } from './floors';
import type { DropTarget } from './layout.svelte';
import { META } from './meta';
import { addInstance, hideCell, liftedPicture, removeCell, normalizeRow, resizeColumns, resizeCorner, resizeRows, rowOfCell, withoutCell } from './model';
import { sameRects, toDropTarget } from './rects/drop-aim';
import { layoutGeometry, rectsAreSound, uncoveredFraction } from './rects/layout-rects';
import { validate } from './persist';
import { MAX_SPAN, spanOf } from './spans';
import { GUTTER, computeTracks } from './tracks';
import type { Layout, RowModel, SlotId } from './types';

const G = 9;
const ROW_FLOOR = 120;
const BOXES: readonly (readonly [number, number])[] = [[2076, 977], [1560, 1004], [900, 700]];
const LIFT_BOXES: readonly (readonly [number, number])[] = [...BOXES, [2200, 1364]];
const ARMS = ['left', 'right', 'up', 'down'] as const;
type Arm = (typeof ARMS)[number];
type Rects = ReturnType<typeof layoutGeometry>['rects'];

const SHAPES: { name: string; rows: RowModel[] }[] = [
  { name: 'shape-1', rows: [{"id":"r16","kind":"flex","size":0.4509646302250804,"slots":[{"id":"terminal:@primary","fr":0.3062157221206581,"span":3},{"id":"terminal:row:121","fr":0.37294332723948814,"span":2},{"id":"terminal:row:197","fr":0.32084095063985374}]},{"id":"r21","kind":"flex","size":0.07958199356913183,"slots":[{"id":"terminal:row:32","fr":1,"span":2}],"reserved":[{"of":"terminal:@primary","at":0},{"of":"terminal:row:121","at":0}]},{"id":"r22","kind":"flex","size":0.4694533762057878,"slots":[{"id":"terminal:row:419","fr":1}],"reserved":[{"of":"terminal:@primary","at":0},{"of":"terminal:row:32","at":1}]}] as RowModel[] },
  { name: 'shape-2', rows: [{"id":"r7","kind":"flex","size":0.4896934128421901,"slots":[{"id":"terminal:@primary","fr":0.5,"span":2},{"id":"terminal:row:122","fr":0.5000000000000001}]},{"id":"r8","kind":"flex","size":0.51030658715781,"slots":[{"id":"terminal:row:123","fr":1}],"reserved":[{"of":"terminal:@primary","at":0}]}] as RowModel[] },
  { name: 'shape-3', rows: [{"id":"r14","kind":"flex","size":0.474565709224381,"slots":[{"id":"terminal:row:194","fr":0.4998616314713896,"span":2},{"id":"terminal:@primary","fr":0.5001383685286103}]},{"id":"r15","kind":"flex","size":0.5254342907756191,"slots":[{"id":"terminal:row:197","fr":1}],"reserved":[{"of":"terminal:row:194","at":0}]}] as RowModel[] },
  { name: 'shape-4', rows: [{"id":"r16","kind":"flex","size":0.4509646302250804,"slots":[{"id":"terminal:@primary","fr":0.5262741522316947,"span":2},{"id":"terminal:row:197","fr":0.4737258477683053}]},{"id":"r21","kind":"flex","size":0.5490353697749196,"slots":[{"id":"terminal:row:32","fr":1}],"reserved":[{"of":"terminal:@primary","at":0}]}] as RowModel[] },
  { name: 'shape-5', rows: [{"id":"r1","kind":"flex","size":1,"slots":[{"id":"terminal:@primary","fr":0.5421230057009662},{"id":"terminal:row:26","fr":0.4578769942990337}]}] as RowModel[] },
];

const layoutOf = (rows: RowModel[]): Layout => ({ v: 6, rows, hidden: [], heroCollapsed: false, collapsed: [] });
const winsOf = (l: Layout): SlotId[] => l.rows.flatMap((r) => r.slots.map((s) => s.id));
let seed = 20261109;
const rnd = (n: number): number => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return Math.floor((seed / 0x80000000) * n); };
const near = (a: number, b: number, tol: number): boolean => Math.abs(a - b) <= tol;

function dropFor(of: SlotId, arm: Arm, width: number, height: number): DropTarget {
  const grammar = arm === 'left' || arm === 'right' ? { kind: 'split', of, side: arm } : { kind: 'stack', of, edge: arm === 'up' ? 'above' : 'below' };
  return toDropTarget(grammar as never, width, height)!;
}

function liftedFolded(layout: Layout, id: SlotId, width: number, height?: number): Layout {
  return liftedPicture(layout, id, width, height);
}

function overlaps(rects: Rects): boolean {
  const rs = [...rects.values()];
  return rs.some((a, i) => rs.slice(i + 1).some((b) => a.x < b.x + b.w - 1 && b.x < a.x + a.w - 1 && a.y < b.y + b.h - 1 && b.y < a.y + a.h - 1));
}

const tally = new Map<string, number>();
const failures: string[] = [];
const count = (key: string): void => { tally.set(key, (tally.get(key) ?? 0) + 1); };

function judge(name: string, layout: Layout, base: Layout, active: SlotId, ref: Layout, target: SlotId, arm: Arm, [W, H]: readonly [number, number], label: string): void {
  const refRects = layoutGeometry(ref, W, H, G).rects;
  const refClass = liftClass(ref, W, H);
  const where = `${name} ${W}x${H} ${label} ${arm} of ${target.split(':').pop()}${refClass ? ` [${refClass}]` : ''}`;
  const t0 = refRects.get(target);
  if (!t0) return;
  const horizontal = arm === 'left' || arm === 'right';
  const room = horizontal ? t0.w >= 2 * COL_MIN + G : t0.h >= 2 * ROW_FLOOR + G;
  const startRects = layoutGeometry(layout, W, H, G).rects;
  const sound0 = rectsAreSound([...startRects.values()], W, H, G);
  const kind = label.startsWith('move') ? 'move' : 'add';
  const spanFull = ref.rows.some((row) => row.slots.some((slot) => spanOf(slot) >= MAX_SPAN));
  const next = applyDrop(base, active, dropFor(target, arm, W, H), META);

  const tol = horizontal ? 2 : G + 2;
  const unchanged = (() => {
    const half = horizontal ? (t0.w - G) / 2 : (t0.h - G) / 2;
    return [...startRects].every(([id, r]) => {
      if (id === active) {
        const mine = horizontal ? { x: arm === 'left' ? t0.x : t0.x + half + G, y: t0.y, w: half, h: t0.h } : { x: t0.x, y: arm === 'up' ? t0.y : t0.y + half + G, w: t0.w, h: half };
        return near(r.x, mine.x, tol) && near(r.y, mine.y, tol) && near(r.w, mine.w, tol) && near(r.h, mine.h, tol);
      }
      if (id === target) {
        const mine = horizontal ? { x: arm === 'left' ? t0.x + half + G : t0.x, y: t0.y, w: half, h: t0.h } : { x: t0.x, y: arm === 'up' ? t0.y + half + G : t0.y, w: t0.w, h: half };
        return near(r.x, mine.x, tol) && near(r.y, mine.y, tol) && near(r.w, mine.w, tol) && near(r.h, mine.h, tol);
      }
      const o = refRects.get(id);
      return !!o && near(r.x, o.x, tol) && near(r.y, o.y, tol) && near(r.w, o.w, tol) && near(r.h, o.h, tol);
    });
  })();

  if (next === base) {
    if (unchanged) count(`${kind} same`);
    else if (spanFull) count(`${kind} span`);
    else if (!room) count(`${kind} noroom-${horizontal ? 'x' : 'y'}`);
    else failures.push(`${where}: refused (the layout came back unchanged) although the target is ${Math.round(t0.w)}x${Math.round(t0.h)}`);
    return;
  }
  const geo = layoutGeometry(next, W, H, G).rects;
  const arrival = geo.get(active);
  const mine = geo.get(target);
  if (!arrival || !mine || geo.size !== winsOf(next).length) { failures.push(`${where}: a window is lost`); return; }
  if (overlaps(geo)) { failures.push(`${where}: two windows overlap`); return; }
  if (uncoveredFraction([...geo.values()], W, H, G) > 0.011) { failures.push(`${where}: a hole`); return; }
  if (sameRects(startRects, geo)) { count(`${kind} same`); return; }
  const soundNext = rectsAreSound([...geo.values()], W, H, G);
  const thirds = [...geo].filter(([id]) => id !== active && id !== target);
  if (sound0 && !soundNext) {
    if (!room) count(`${kind} noroom-${horizontal ? 'x' : 'y'}`);
    else if (thirds.some(([, r]) => r.w < COL_MIN || r.h < ROW_FLOOR)) count(`${kind} third`);
    else failures.push(`${where}: refused by the floor gate with room (arrival ${Math.round(arrival.w)}x${Math.round(arrival.h)}, target ${Math.round(mine.w)}x${Math.round(mine.h)}, target before ${Math.round(t0.w)}x${Math.round(t0.h)})`);
    return;
  }
  const bad: string[] = [];
  if (horizontal) {
    const half = (t0.w - G) / 2;
    const [a, b] = arm === 'left' ? [arrival, mine] : [mine, arrival];
    if (!(a.x < b.x)) bad.push('wrong side');
    for (const r of [arrival, mine]) if (!near(r.w, half, tol) || !near(r.y, t0.y, tol) || !near(r.h, t0.h, tol)) bad.push(`half ${Math.round(r.w)}x${Math.round(r.h)} at y ${Math.round(r.y)}`);
    if (!near(a.x, t0.x, tol) || !near(b.x + b.w, t0.x + t0.w, tol)) bad.push('extent');
  } else {
    const half = (t0.h - G) / 2;
    const [a, b] = arm === 'up' ? [arrival, mine] : [mine, arrival];
    if (!(a.y < b.y)) bad.push('wrong side');
    for (const r of [arrival, mine]) if (!near(r.h, half, tol) || !near(r.x, t0.x, tol) || !near(r.w, t0.w, tol)) bad.push(`half ${Math.round(r.w)}x${Math.round(r.h)} at x ${Math.round(r.x)}`);
    if (!near(a.y, t0.y, tol) || !near(b.y + b.h, t0.y + t0.h, tol)) bad.push('extent');
  }
  for (const [id, r] of thirds) {
    const o = refRects.get(id);
    if (!o || (horizontal ? !near(r.x, o.x, tol) || !near(r.y, o.y, tol) || !near(r.w, o.w, tol) || !near(r.h, o.h, tol) : r.h < o.h - 2 || r.w < o.w - 2)) bad.push(`${id.split(':').pop()} moved ${o ? `${Math.round(o.x)},${Math.round(o.y)} ${Math.round(o.w)}x${Math.round(o.h)}` : '?'} to ${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.w)}x${Math.round(r.h)}`);
  }
  if (bad.length) {
    failures.push(`${where}: ${bad.join('; ')}`);
    return;
  }
  count(`${kind} offered-${horizontal ? 'split' : 'stack'}`);
}

function liftClass(ref: Layout, W: number, H: number): '' | 'REFHOLE' | 'REFSQUEEZE' {
  const rects = [...layoutGeometry(ref, W, H, G).rects.values()];
  if (uncoveredFraction(rects, W, H, G) > 0.011) return 'REFHOLE';
  return rects.some((r) => r.w < COL_MIN || r.h < ROW_FLOOR) ? 'REFSQUEEZE' : '';
}

function audit(name: string, layout: Layout, box: readonly [number, number]): void {
  const wins = winsOf(layout);
  const ghost = addInstance(layout, 'terminal', 'row:99990', '', META);
  const kinds: { label: string; base: Layout; active: SlotId; ref: Layout }[] = [];
  if (!ghost.refusal) kinds.push({ label: 'add', base: ghost.layout, active: 'terminal:row:99990' as SlotId, ref: layout });
  for (const w of wins) kinds.push({ label: `move ${w.split(':').pop()}`, base: layout, active: w, ref: liftedFolded(layout, w, box[0], box[1]) });
  for (const k of kinds) for (const target of wins) {
    if (target === k.active) continue;
    for (const arm of ARMS) judge(name, layout, k.base, k.active, k.ref, target, arm, box, k.label);
  }
}

function dragDivider(layout: Layout): Layout {
  const [W, H] = BOXES[0]!;
  const tracks = layoutGeometry(layout, W, H, G).tracks;
  const row = tracks.rows[rnd(tracks.rows.length)]!;
  const dx = (rnd(2) ? 1 : -1) * (40 + rnd(500));
  const dy = (rnd(2) ? 1 : -1) * (30 + rnd(300));
  const seam = row.seams.length ? row.seams[rnd(row.seams.length)] : undefined;
  const pick = rnd(4);
  if (pick === 0 && seam) return resizeColumns(layout, row.id, seam.index, dx, row.free, seam.leftMinPx, seam.leftMaxPx);
  if (pick === 1) return resizeRows(layout, row.id, dy, tracks.flexSpace, META);
  if (seam) return resizeCorner(layout, row.id, seam.index, row.id, dx, dy, row.free, seam.leftMinPx, seam.leftMaxPx, tracks.flexSpace, META);
  return layout;
}

function corpus(): { name: string; layout: Layout }[] {
  seed = 20261109;
  const seen = new Map<string, { name: string; layout: Layout }>();
  const [W, H] = BOXES[0]!;
  for (const shape of SHAPES) {
    let cur = layoutOf(shape.rows);
    seen.set(JSON.stringify(cur.rows), { name: shape.name, layout: cur });
    for (let step = 0; step < 70; step += 1) {
      const wins = winsOf(cur);
      let next = cur;
      if (rnd(10) < 4) next = dragDivider(cur);
      else {
        const add = wins.length < 7 && (wins.length < 2 || rnd(10) < 4);
        let base = cur;
        let active: SlotId;
        if (add) {
          const added = addInstance(cur, 'terminal', `row:${9000 + step}`, '', META);
          if (added.refusal) continue;
          base = added.layout;
          active = `terminal:row:${9000 + step}` as SlotId;
        } else active = wins[rnd(wins.length)]!;
        const others = wins.filter((w) => w !== active);
        const dropped = applyDrop(base, active, dropFor(others[rnd(others.length)]!, ARMS[rnd(4)]!, W, H), META);
        if (dropped !== base && rectsAreSound([...layoutGeometry(dropped, W, H, G).rects.values()], W, H, G)) next = dropped;
      }
      if (next === cur) continue;
      cur = next;
      seen.set(JSON.stringify(cur.rows), { name: `${shape.name}+${step + 1}`, layout: cur });
    }
  }
  return [...seen.values()];
}

test('every compass arm on a window with room for two halves is offered, for every drag kind', () => {
  const layouts = corpus();
  for (const { name, layout } of layouts) for (const box of BOXES) audit(name, layout, box);
  const wanted = ['add offered-split', 'add offered-stack', 'move offered-split', 'move offered-stack', 'add noroom-x', 'add noroom-y', 'move noroom-x', 'move noroom-y', 'move same'];
  expect(layouts.length).toBeGreaterThan(40);
  expect(wanted.filter((key) => !tally.get(key))).toEqual([]);
  const every = Math.max(1, Math.ceil(failures.length / 14));
  expect({ count: failures.length, sample: failures.filter((_one, at) => at % every === 0) }).toEqual({ count: 0, sample: [] });
}, 60_000);

function liftVerdict(tag: string, own: Rects, after: Rects, gone: SlotId, W: number, H: number): string[] {
  const bad: string[] = [];
  for (const [other, was] of own) {
    if (other === gone) continue;
    const now = after.get(other);
    if (!now || now.w < 1) bad.push(`${tag}: ${other} is gone or zero width`);
    else if (now.w < was.w - 2 || now.h < was.h - 2) bad.push(`${tag}: ${now.w < was.w - 2 ? 'W' : 'H'} ${other} shrank ${was.w}x${was.h} to ${now.w}x${now.h}`);
  }
  if (uncoveredFraction([...after.values()], W, H, G) >= 0.01) bad.push(`${tag}: a hole`);
  return bad;
}

function sweep(close: boolean): { bad: string[]; runs: number } {
  const bad: string[] = [];
  let runs = 0;
  for (const { name, layout } of corpus()) for (const [W, H] of LIFT_BOXES) {
    const own = layoutGeometry(layout, W, H, G).rects;
    for (const id of winsOf(layout)) {
      const kinds = close ? [['remove', removeCell(layout, id, W, H)], ['hide', hideCell(layout, id, W, H)]] as const : [['lift', liftedFolded(layout, id, W, H)]] as const;
      for (const [verb, picture] of kinds) {
        if (picture === layout) continue;
        runs += 1;
        bad.push(...liftVerdict(`${name} ${W}x${H} ${verb} ${id.split(':').pop()}`, own, layoutGeometry(picture, W, H, G).rects, id, W, H));
        if (close) {
          const committed = layoutGeometry(picture, W, H, G).rects;
          const loaded = validate(JSON.parse(JSON.stringify(picture)), META, 'terminal').layout;
          const back = loaded ? layoutGeometry(loaded, W, H, G).rects : undefined;
          for (const [other, r] of committed) {
            const b = back?.get(other);
            if (!b || [b.x - r.x, b.y - r.y, b.w - r.w, b.h - r.h].some((d) => Math.abs(d) > 2)) bad.push(`${name} ${W}x${H} ${verb} ${id.split(':').pop()}: reload moved ${other} ${Math.round(r.y)},${Math.round(r.h)} to ${b ? `${Math.round(b.y)},${Math.round(b.h)}` : 'nothing'}`);
          }
        }
      }
    }
  }
  return { bad, runs };
}

/* list, so the */
const sampleOf = (bad: string[]): { count: number; sample: string[] } => ({ count: bad.length, sample: bad.filter((_one, at) => at % Math.max(1, Math.ceil(bad.length / 14)) === 0) });

test('a lift shrinks no window and leaves the picture whole, at every size (#2937)', () => {
  const { bad, runs } = sweep(false);
  expect(runs).toBeGreaterThan(500);
  expect(sampleOf(bad)).toEqual({ count: 0, sample: [] });
}, 60_000);

test('closing or hiding a window shrinks no other window and leaves the picture whole, at every size (#2937)', () => {
  const { bad, runs } = sweep(true);
  expect(runs).toBeGreaterThan(500);
  expect(sampleOf(bad)).toEqual({ count: 0, sample: [] });
}, 60_000);
