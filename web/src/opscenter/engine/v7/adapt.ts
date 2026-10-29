
import { clearSpan, repairSpans, spanOf, spanUp, visualOrder } from '../spans';
import type { Layout, LayoutPage, Reservation, RowModel, Slot, SlotId } from '../types';
import { EDGE_EPSILON, gridGeometry } from './grid-geometry';
import { rectsOf, type Rect } from './tree';
import type { LayoutV7 } from './types';
import { SCHEMA_VERSION_V7 } from './types';
import { validateV7, type SlotIdCheck } from './validate';

export type AdaptOutcome = 'adapted' | 'adapted_lossy';

export interface Adaptation {
  outcome: AdaptOutcome;
  layout: Layout;
  shortenedSpans: SlotId[];
}

const EDGE_RELATIVE = 1e-9;

export const MAX_SHORTENS = 4096;

export const ADAPT_DRIFT = 1e-9;

interface Placed {
  id: SlotId;
  top: number;
  bottom: number;
  x0: number;
  x1: number;
}

function edgesOf(rects: Iterable<Rect>, tolerance: number): number[] {
  const all: number[] = [];
  for (const rect of rects) all.push(rect.y0, rect.y1);
  all.sort((a, b) => a - b);
  const out: number[] = [];
  for (const one of all) if (out.length === 0 || one - (out[out.length - 1] as number) > tolerance) out.push(one);
  return out;
}

function edgeAt(edges: readonly number[], y: number): number {
  let best = 0;
  for (let at = 1; at < edges.length; at += 1) {
    if (Math.abs((edges[at] as number) - y) < Math.abs((edges[best] as number) - y)) best = at;
  }
  return best;
}

function gridOf(placed: readonly Placed[], sizes: readonly number[], page: LayoutPage, layout: LayoutV7): Layout {
  const rows: RowModel[] = sizes.map((size, rowAt) => {
    const own = placed.filter((cell) => cell.top === rowAt).sort((a, b) => a.x0 - b.x0);
    const crossing = placed.filter((cell) => cell.top < rowAt && cell.bottom > rowAt).sort((a, b) => a.x0 - b.x0);
    const total = own.reduce((sum, cell) => sum + (cell.x1 - cell.x0), 0);
    const slots: Slot[] = own.map((cell) => {
      const slot: Slot = { id: cell.id, fr: total > 0 ? (cell.x1 - cell.x0) / total : 1 / own.length };
      if (cell.bottom - cell.top >= 2) slot.span = cell.bottom - cell.top;
      return slot;
    });
    const reserved: Reservation[] = crossing.map((cell) => ({
      of: cell.id,
      at: own.filter((one) => one.x0 < cell.x0 - EDGE_EPSILON).length,
    }));
    const row: RowModel = { id: `r${rowAt + 1}` as `r${number}`, kind: page === 'home' ? 'px' : 'flex', size, slots };
    return reserved.length ? { ...row, reserved } : row;
  });
  return repairSpans({
    v: 6,
    rows,
    hidden: [...layout.hidden],
    collapsed: [...layout.collapsed],
    heroCollapsed: layout.heroCollapsed,
    ...(layout.headerOff?.length ? { headerOff: [...layout.headerOff] } : {}),
  });
}

export function placementDrift(grid: Layout, rects: ReadonlyMap<SlotId, Rect>): number {
  const geometry = gridGeometry(grid);
  if (!geometry) return Number.POSITIVE_INFINITY;
  const tops = [0];
  for (const size of geometry.rowSizes) tops.push((tops[tops.length - 1] as number) + size);
  const height = Math.max(1, tops[tops.length - 1] as number);
  let worst = 0;
  let seen = 0;
  for (const cell of geometry.cells) {
    if (cell.id === null) continue;
    const want = rects.get(cell.id);
    if (!want) return Number.POSITIVE_INFINITY;
    seen += 1;
    worst = Math.max(
      worst,
      Math.abs(cell.x0 - want.x0),
      Math.abs(cell.x1 - want.x1),
      Math.abs((tops[cell.top] as number) - want.y0) / height,
      Math.abs((tops[cell.bottom] as number) - want.y1) / height,
    );
  }
  return seen === rects.size ? worst : Number.POSITIVE_INFINITY;
}

export function toV6(layout: LayoutV7, page: LayoutPage): Adaptation {
  const rects = rectsOf(layout.variants.wide.root);
  let height = 0;
  for (const rect of rects.values()) height = Math.max(height, rect.y1);
  const edges = edgesOf(rects.values(), EDGE_RELATIVE * Math.max(1, height));
  const sizes = edges.slice(1).map((edge, at) => edge - (edges[at] as number));
  const placed: Placed[] = [];
  for (const [id, rect] of rects) {
    placed.push({ id, top: edgeAt(edges, rect.y0), bottom: edgeAt(edges, rect.y1), x0: rect.x0, x1: rect.x1 });
  }
  let grid = gridOf(placed, sizes, page, layout);
  if (placementDrift(grid, rects) <= ADAPT_DRIFT) return { outcome: 'adapted', layout: grid, shortenedSpans: [] };
  const shortened: SlotId[] = [];
  for (let step = 0; step < MAX_SHORTENS && !gridGeometry(grid); step += 1) {
    const culprit = inversionOf(grid, rects);
    if (!culprit) break;
    grid = spanUp(grid, culprit);
    if (!shortened.includes(culprit)) shortened.push(culprit);
  }
  if (!gridGeometry(grid)) {
    for (const row of grid.rows) {
      for (const one of row.slots) {
        if (spanOf(one) >= 2 && !shortened.includes(one.id)) shortened.push(one.id);
      }
    }
    for (const id of shortened) grid = clearSpan(grid, id);
  }
  return { outcome: 'adapted_lossy', layout: grid, shortenedSpans: shortened };
}

function inversionOf(grid: Layout, rects: ReadonlyMap<SlotId, Rect>): SlotId | null {
  for (const row of grid.rows) {
    let previous = Number.NEGATIVE_INFINITY;
    for (const entry of visualOrder(row)) {
      if (entry.kind !== 'reserved') continue;
      const x = rects.get(entry.of)?.x0 ?? Number.NaN;
      if (x < previous - EDGE_EPSILON) return entry.of;
      previous = x;
    }
  }
  return null;
}

export type StoredGrid =
  | { kind: 'v6'; grid: unknown }
  | { kind: 'v7'; grid: Layout; adaptation: Adaptation }
  | { kind: 'v7-refused'; refusal: string; detail: string };

export function readStoredGrid(raw: unknown, page: LayoutPage, isSlotId?: SlotIdCheck): StoredGrid {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || (raw as { v?: unknown }).v !== SCHEMA_VERSION_V7) {
    return { kind: 'v6', grid: raw };
  }
  const checked = validateV7(raw, page, isSlotId);
  if (!checked.ok) return { kind: 'v7-refused', refusal: checked.refusal, detail: checked.detail };
  const adaptation = toV6(checked.layout, page);
  return { kind: 'v7', grid: adaptation.layout, adaptation };
}
