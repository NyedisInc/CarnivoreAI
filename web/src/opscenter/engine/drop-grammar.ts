import { bodyOf, compassGeometry, type CompassDir, type CompassGeometry } from './dock-compass';

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface SnapCell {
  owner: string | null;
  x: number;
  width: number;
}

export interface SnapRow {
  id: string;
  top: number;
  height: number;
  cells: SnapCell[];
}

export interface SnapStrip extends Rect {
  tabs: { id: string; centre: number }[];
}

export interface SnapWindow extends Rect {
  id: string;
  takesTabs: boolean;
  tabs: string[];
  strip: SnapStrip | null;
}

export interface Snapshot {
  width: number;
  height: number;
  gutter: number;
  rows: SnapRow[];
  windows: SnapWindow[];
}

export type Dragged = { kind: 'tab'; tab: string } | { kind: 'window'; id: string };

export interface SeamRow {
  row: string;
  left: string | null;
  right: string | null;
}

export type GrammarTarget =
  | { kind: 'strip'; slot: string; index: number }
  | { kind: 'middle'; slot: string }
  | { kind: 'split'; of: string; side: 'left' | 'right' }
  | { kind: 'stack'; of: string; edge: 'above' | 'below' }
  | { kind: 'seam'; rows: SeamRow[] }
  | { kind: 'new'; after: string | null }
  | { kind: 'stack-run'; of: string[]; edge: 'below' };

export interface Candidate {
  key: string;
  target: GrammarTarget;
  zone: Rect;
  hold: Rect;
  priority: number;
  label: string;
  reflows: boolean;
  compass?: CompassDir;
}

export const STRIP_TOP_PX = 10;
export const DEAD_BAND_PX = 6;
export const HOLD_PX = 8;
export const BAND_REACH_PX = 40;
export const OUTSIDE_PX = 48;
const BAND_TOP = STRIP_TOP_PX;
const BAND_SIDE = 24;
const BAND_BOTTOM = 24;
const SEAM_REACH = 16;
const SEAM_BELOW_EXTRA = 4;

const PRIORITY = { strip: 2, band: 3, seam: 4, edge: 5, middle: 6 } as const;

interface VSeam {
  xs: number;
  rows: SeamRow[];
  zone: Rect;
}

interface HSeam {
  ys: number;
  zone: Rect;
  target: GrammarTarget;
  key: string;
}

export interface Zones {
  width: number;
  height: number;
  windows: SnapWindow[];
  vseams: VSeam[];
  hseams: HSeam[];
  rowIds: string[];
  firstOwner: Map<string, string | null>;
  lastOwner: Map<string, string | null>;
}

function within(r: Rect, x: number, y: number): boolean {
  return x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h;
}

function inflate(r: Rect, by: number): Rect {
  return { x: r.x - by, y: r.y - by, w: r.w + 2 * by, h: r.h + 2 * by };
}

function owned(row: SnapRow): SnapCell[] {
  return row.cells.filter((c) => c.owner !== null);
}

function buildVSeams(rows: SnapRow[]): VSeam[] {
  const open: { xs: number; first: number; last: number; rows: SeamRow[] }[] = [];
  const done: typeof open = [];
  rows.forEach((row, i) => {
    const cells = owned(row);
    const seen = new Set<(typeof open)[number]>();
    for (let k = 0; k + 1 < cells.length; k++) {
      const a = cells[k]!;
      const b = cells[k + 1]!;
      if (a.owner === b.owner) continue;
      const xs = (a.x + a.width + b.x) / 2;
      const run = open.find((o) => o.last === i - 1 && Math.abs(o.xs - xs) <= 1 && !seen.has(o));
      const entry: SeamRow = { row: row.id, left: a.owner, right: b.owner };
      if (run) {
        run.rows.push(entry);
        run.last = i;
        seen.add(run);
      } else {
        const fresh = { xs, first: i, last: i, rows: [entry] };
        open.push(fresh);
        seen.add(fresh);
      }
    }
    for (let j = open.length - 1; j >= 0; j--) {
      if (open[j]!.last < i) done.push(...open.splice(j, 1));
    }
  });
  done.push(...open);
  return done.map((run) => {
    const top = rows[run.first]!.top;
    const last = rows[run.last]!;
    return {
      xs: run.xs,
      rows: run.rows,
      zone: { x: run.xs - SEAM_REACH, y: top, w: 2 * SEAM_REACH, h: last.top + last.height - top },
    };
  });
}

function buildHSeams(rows: SnapRow[], gutter: number): HSeam[] {
  const out: HSeam[] = [];
  for (let i = 0; i + 1 < rows.length; i++) {
    const row = rows[i]!;
    const below = new Set(owned(rows[i + 1]!).map((c) => c.owner));
    const ys = row.top + row.height + gutter / 2;
    const y = ys - SEAM_REACH;
    const h = SEAM_REACH + gutter / 2 + SEAM_BELOW_EXTRA;
    const cells = owned(row);
    if (cells.length === 0) continue;
    if (!cells.some((c) => below.has(c.owner))) {
      const x = cells[0]!.x;
      const last = cells[cells.length - 1]!;
      out.push({ ys, zone: { x, y, w: last.x + last.width - x, h }, target: { kind: 'new', after: row.id }, key: `new:${row.id}` });
      continue;
    }
    let run: SnapCell[] = [];
    const flush = (): void => {
      if (run.length === 0) return;
      const x = run[0]!.x;
      const last = run[run.length - 1]!;
      const of = run.map((c) => c.owner as string);
      out.push({
        ys,
        zone: { x, y, w: last.x + last.width - x, h },
        target: { kind: 'stack-run', of, edge: 'below' },
        key: `run:${row.id}:${of.join(',')}`,
      });
      run = [];
    };
    for (const c of cells) {
      if (below.has(c.owner)) flush();
      else run.push(c);
    }
    flush();
  }
  return out;
}

export function buildZones(snapshot: Snapshot): Zones {
  const firstOwner = new Map<string, string | null>();
  const lastOwner = new Map<string, string | null>();
  for (const row of snapshot.rows) {
    const cells = owned(row);
    firstOwner.set(row.id, cells[0]?.owner ?? null);
    lastOwner.set(row.id, cells[cells.length - 1]?.owner ?? null);
  }
  return {
    width: snapshot.width,
    height: snapshot.height,
    windows: snapshot.windows,
    vseams: buildVSeams(snapshot.rows),
    hseams: buildHSeams(snapshot.rows, snapshot.gutter),
    rowIds: snapshot.rows.map((r) => r.id),
    firstOwner,
    lastOwner,
  };
}

function caretAt(strip: SnapStrip, tab: string | null, x: number): { index: number; zone: Rect; hold: Rect } | null {
  const centres = strip.tabs.filter((t) => t.id !== tab).map((t) => t.centre);
  const half = DEAD_BAND_PX / 2;
  const left = strip.x;
  const right = strip.x + strip.w;
  const top = strip.y + STRIP_TOP_PX;
  const height = strip.h - STRIP_TOP_PX;
  for (let i = 0; i <= centres.length; i++) {
    const lo = i === 0 ? left : centres[i - 1]! + half;
    const hi = i === centres.length ? right : centres[i]! - half;
    if (x < lo || x >= hi) continue;
    const hlo = i === 0 ? left : centres[i - 1]! - half;
    const hhi = i === centres.length ? right : centres[i]! + half;
    return { index: i, zone: { x: lo, y: top, w: hi - lo, h: height }, hold: { x: hlo, y: top, w: hhi - hlo, h: height } };
  }
  return null;
}

function bandCandidates(z: Zones, x: number, y: number): Candidate[] {
  const { width: W, height: H } = z;
  const reach = BAND_REACH_PX;
  const last = z.rowIds[z.rowIds.length - 1];
  const found: { dist: number; order: number; c: Candidate }[] = [];
  const column = (side: 'left' | 'right'): Candidate => ({
    key: `band:${side}`,
    target: {
      kind: 'seam',
      rows: z.rowIds.map((row) =>
        side === 'left'
          ? { row, left: null, right: z.firstOwner.get(row) ?? null }
          : { row, left: z.lastOwner.get(row) ?? null, right: null },
      ),
    },
    zone: side === 'left' ? { x: -reach, y: -reach, w: reach + BAND_SIDE, h: H + 2 * reach } : { x: W - BAND_SIDE, y: -reach, w: reach + BAND_SIDE, h: H + 2 * reach },
    hold: { x: 0, y: 0, w: 0, h: 0 },
    priority: PRIORITY.band,
    label: side === 'left' ? 'opscenter.drop.column_left' : 'opscenter.drop.column_right',
    reflows: true,
  });
  const row = (edge: 'top' | 'bottom'): Candidate => ({
    key: `band:${edge}`,
    target: { kind: 'new', after: edge === 'top' ? null : (last ?? null) },
    zone: edge === 'top' ? { x: -reach, y: -reach, w: W + 2 * reach, h: reach + BAND_TOP } : { x: -reach, y: H - BAND_BOTTOM, w: W + 2 * reach, h: reach + BAND_BOTTOM },
    hold: { x: 0, y: 0, w: 0, h: 0 },
    priority: PRIORITY.band,
    label: edge === 'top' ? 'opscenter.drop.row_top' : 'opscenter.drop.row_bottom',
    reflows: true,
  });
  const inY = y >= -reach && y <= H + reach;
  const inX = x >= -reach && x <= W + reach;
  if (z.rowIds.length > 0 && inY && x < BAND_SIDE) found.push({ dist: x, order: 0, c: column('left') });
  if (z.rowIds.length > 0 && inY && x > W - BAND_SIDE) found.push({ dist: W - x, order: 1, c: column('right') });
  if (inX && y < BAND_TOP) found.push({ dist: y, order: 2, c: row('top') });
  if (inX && z.rowIds.length > 0 && y > H - BAND_BOTTOM) found.push({ dist: H - y, order: 3, c: row('bottom') });
  found.sort((a, b) => a.dist - b.dist || a.order - b.order);
  return found.map((f) => ({ ...f.c, hold: f.c.zone }));
}

function seamCandidates(z: Zones, x: number, y: number): Candidate[] {
  const found: { dist: number; order: number; c: Candidate }[] = [];
  for (const v of z.vseams) {
    if (!within(v.zone, x, y)) continue;
    const key = `seam:${v.xs.toFixed(1)}:${v.rows.map((r) => r.row).join(',')}`;
    found.push({
      dist: Math.abs(x - v.xs),
      order: 0,
      c: { key, target: { kind: 'seam', rows: v.rows }, zone: v.zone, hold: v.zone, priority: PRIORITY.seam, label: 'opscenter.drop.column', reflows: true },
    });
  }
  for (const h of z.hseams) {
    if (!within(h.zone, x, y)) continue;
    found.push({
      dist: Math.abs(y - h.ys),
      order: 1,
      c: { key: h.key, target: h.target, zone: h.zone, hold: h.zone, priority: PRIORITY.seam, label: 'opscenter.drop.row', reflows: true },
    });
  }
  found.sort((a, b) => a.dist - b.dist || a.order - b.order);
  return found.map((f) => f.c);
}

function windowCandidates(w: SnapWindow, x: number, y: number, dragged: Dragged): Candidate[] {
  const geo = compassGeometry(w, dragged);
  const slot = geo?.slots.find((s) => s.allowed && within(s.rect, x, y));
  if (!slot) return [];
  const side = slot.dir === 'up' ? 'top' : slot.dir === 'down' ? 'bottom' : slot.dir;
  const target: GrammarTarget =
    slot.dir === 'centre'
      ? { kind: 'middle', slot: w.id }
      : slot.dir === 'left' || slot.dir === 'right'
        ? { kind: 'split', of: w.id, side: slot.dir }
        : { kind: 'stack', of: w.id, edge: slot.dir === 'up' ? 'above' : 'below' };
  return [
    {
      key: slot.dir === 'centre' ? `mid:${w.id}` : `${target.kind}:${w.id}:${side}`,
      target,
      zone: slot.rect,
      hold: slot.rect,
      priority: slot.dir === 'centre' ? PRIORITY.middle : PRIORITY.edge,
      label: slot.dir === 'centre' ? (dragged.kind === 'tab' ? 'opscenter.tabs.drop_center' : 'opscenter.drop.add_tabs') : `opscenter.tabs.drop_${side}`,
      reflows: slot.dir !== 'centre',
      compass: slot.dir,
    },
  ];
}

export function compassAt(zones: Zones, point: { x: number; y: number }, dragged: Dragged): CompassGeometry | null {
  for (const w of zones.windows) {
    if (dragged.kind === 'window' && w.id === dragged.id) continue;
    if (!within(bodyOf(w), point.x, point.y)) continue;
    return compassGeometry(w, dragged);
  }
  return null;
}

export function candidatesAt(zones: Zones, point: { x: number; y: number }, dragged: Dragged): Candidate[] {
  const { x, y } = point;
  if (x < -OUTSIDE_PX || x > zones.width + OUTSIDE_PX || y < -OUTSIDE_PX || y > zones.height + OUTSIDE_PX) return [];
  const out: Candidate[] = [];
  const ownWindow = dragged.kind === 'window' ? dragged.id : null;
  const tab = dragged.kind === 'tab' ? dragged.tab : null;
  for (const w of zones.windows) {
    if (w.id === ownWindow || !w.takesTabs || !w.strip) continue;
    const s = w.strip;
    if (!within({ x: s.x, y: s.y + STRIP_TOP_PX, w: s.w, h: s.h - STRIP_TOP_PX }, x, y)) continue;
    const caret = caretAt(s, tab, x);
    if (!caret) continue;
    out.push({
      key: `strip:${w.id}:${caret.index}`,
      target: { kind: 'strip', slot: w.id, index: caret.index },
      zone: caret.zone,
      hold: caret.hold,
      priority: PRIORITY.strip,
      label: '',
      reflows: false,
    });
  }
  out.push(...bandCandidates(zones, x, y), ...seamCandidates(zones, x, y));
  for (const w of zones.windows) {
    if (w.id === ownWindow) continue;
    out.push(...windowCandidates(w, x, y, dragged));
  }
  return out.sort((a, b) => a.priority - b.priority);
}

export function nextTarget(held: Candidate | null, fresh: Candidate | null, point: { x: number; y: number }, placeholder: Rect | null): Candidate | null {
  if (!held) return fresh;
  if (fresh && fresh.key === held.key) return held;
  if (fresh && fresh.priority < held.priority) return fresh;
  if (held.target.kind === 'strip' || held.compass) return within(held.hold, point.x, point.y) ? held : fresh;
  const inHold = within(inflate(held.hold, HOLD_PX), point.x, point.y)
    || (placeholder !== null && within(inflate(placeholder, HOLD_PX), point.x, point.y));
  return inHold ? held : fresh;
}
