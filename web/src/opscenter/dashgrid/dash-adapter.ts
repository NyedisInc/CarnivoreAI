import { pack, type PackItem } from '../../lib/motion-grid/pack';
import type { Adapter, Edge, GestureState, ItemId, KeyStep, Rect, Source, Target, Via } from '../../lib/motion-grid/types';
import { GUTTER } from '../engine/tracks';
import { GRID_PITCH, MAX_H, type GridItem } from './format/grid-format';
import type { Cols } from './grid-data';

export const BREAKPOINTS = { wide: 1100, mid: 720 } as const;

export interface DashDeps {
  cols(): Cols;
  width(): number;
  items(): readonly GridItem[];
  commit(items: GridItem[]): void;
  cancelExternal?(id: ItemId): void;
  label?(id: ItemId): string;
}

export function colsFor(width: number): Cols {
  return width >= BREAKPOINTS.wide ? 24 : width >= BREAKPOINTS.mid ? 12 : 1;
}

const EDGES: readonly Edge[] = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'];

const NO_GRAB = 'button, a, input, select, textarea, [contenteditable], [role="menu"], [data-motion-nograb]';

function minSize(cols: Cols): { w: number; h: number } {
  return { w: cols === 1 ? 1 : cols === 12 ? 2 : 3, h: 3 };
}

function clamp(v: number, a: number, b: number): number {
  return Math.max(a, Math.min(b, v));
}

export function createDashAdapter(deps: DashDeps): Adapter {
  let start: GridItem[] = [];
  let via: Via = 'pointer';
  let activeId = '';

  const geo = (): { colW: number; stepX: number; cols: Cols } => {
    const cols = deps.cols();
    const colW = Math.max(1, (deps.width() - GUTTER * (cols - 1)) / cols);
    return { colW, stepX: colW + GUTTER, cols };
  };

  const rectOf = (i: PackItem): Rect => {
    const { colW, stepX } = geo();
    return { x: i.x * stepX, y: i.y * GRID_PITCH, w: i.w * colW + (i.w - 1) * GUTTER, h: i.h * GRID_PITCH - GUTTER };
  };

  const rectsOf = (items: readonly PackItem[]): Map<ItemId, Rect> => new Map(items.map((i) => [i.id, rectOf(i)]));

  const cellAt = (g: GestureState): { id: string; x: number; y: number } => {
    const { stepX, cols } = geo();
    const id = (g.source as { id: string }).id;
    const it = start.find((s) => s.id === id);
    const w = it?.w ?? 1;
    return {
      id,
      x: clamp(Math.round((g.pointer.x - g.grab.x) / stepX), 0, cols - w),
      y: Math.max(0, Math.round((g.pointer.y - g.grab.y) / GRID_PITCH)),
    };
  };

  const sizeRect = (g: GestureState): Rect => {
    const { colW, stepX, cols } = geo();
    const src = g.source as { id: string; edge: Edge };
    const it = start.find((s) => s.id === src.id)!;
    const r0 = g.startRect ?? rectOf(it);
    const min = minSize(cols);
    const minW = min.w * colW + (min.w - 1) * GUTTER;
    const minH = min.h * GRID_PITCH - GUTTER;
    const maxH = MAX_H * GRID_PITCH - GUTTER;
    let { x, y, w, h } = r0;
    if (src.edge.includes('e')) w = clamp(r0.w + g.delta.x, minW, (cols - it.x) * stepX - GUTTER);
    if (src.edge.includes('w')) {
      x = clamp(r0.x + g.delta.x, 0, r0.x + r0.w - minW);
      w = r0.x + r0.w - x;
    }
    if (src.edge.includes('s')) h = clamp(r0.h + g.delta.y, minH, maxH);
    if (src.edge.includes('n')) {
      y = clamp(r0.y + g.delta.y, Math.max(0, r0.y + r0.h - maxH), r0.y + r0.h - minH);
      h = r0.y + r0.h - y;
    }
    return { x, y, w, h };
  };

  const cellsOf = (r: Rect): { x: number; y: number; w: number; h: number } => {
    const { stepX, cols } = geo();
    const x = clamp(Math.round(r.x / stepX), 0, cols - 1);
    const y = Math.max(0, Math.round(r.y / GRID_PITCH));
    const right = clamp(Math.round((r.x + r.w + GUTTER) / stepX), x + 1, cols);
    const bottom = Math.max(y + 1, Math.round((r.y + r.h + GUTTER) / GRID_PITCH));
    return { x, y, w: right - x, h: bottom - y };
  };

  const packed = (items: readonly GridItem[], id: string, next: Partial<GridItem>): GridItem[] => {
    const moved = items.map((i) => (i.id === id ? { ...i, ...next } : i));
    const held = moved.find((i) => i.id === id)!;
    return pack(moved, deps.cols(), { id, x: held.x, y: held.y }) as GridItem[];
  };

  return {
    rects: () => rectsOf(deps.items()),
    hit(el: Element): Source | null {
      if (el.closest(NO_GRAB)) return null;
      const wrap = el.closest<HTMLElement>('[data-dash-id]');
      if (!wrap) return null;
      const id = wrap.dataset['dashId'] as string;
      const edge = el.closest<HTMLElement>('[data-dash-resize]')?.dataset['dashResize'];
      if (edge && EDGES.includes(edge as Edge)) return { kind: 'resize', id, edge: edge as Edge };
      return { kind: 'move', id };
    },
    begin(source, how) {
      start = [...deps.items()];
      via = how;
      activeId = (source as { id?: string }).id ?? '';
    },
    targetKey(g) {
      if (g.source.kind === 'resize') {
        const c = cellsOf(sizeRect(g));
        return `r:${c.x},${c.y},${c.w},${c.h}`;
      }
      const c = cellAt(g);
      return `m:${c.x},${c.y}`;
    },
    preview(g, key): Target {
      const id = (g.source as { id: string }).id;
      const next = g.source.kind === 'resize' ? packed(start, id, cellsOf(sizeRect(g))) : (() => {
        const c = cellAt(g);
        return packed(start, id, { x: c.x, y: c.y });
      })();
      const rects = rectsOf(next);
      return { key, rects, landing: rects.get(id) ?? null, valid: !g.outside, payload: next };
    },
    activeRect: sizeRect,
    commit(target) {
      if (Array.isArray(target.payload)) deps.commit(target.payload as GridItem[]);
    },
    cancel() {
      if (via === 'external' && activeId) deps.cancelExternal?.(activeId);
    },
    stepFromTarget: true,
    step(id, step: KeyStep, from): Target | null {
      const items = Array.isArray(from?.payload) ? (from.payload as GridItem[]) : deps.items();
      const it = items.find((i) => i.id === id);
      if (!it) return null;
      const { cols } = geo();
      const min = minSize(cols);
      const dx = step.dir === 'left' ? -1 : step.dir === 'right' ? 1 : 0;
      const dy = step.dir === 'up' ? -1 : step.dir === 'down' ? 1 : 0;
      const next = step.resize
        ? { w: clamp(it.w + dx, min.w, cols - it.x), h: clamp(it.h + dy, min.h, MAX_H) }
        : { x: clamp(it.x + dx, 0, cols - it.w), y: Math.max(0, it.y + dy) };
      if (Object.entries(next).every(([k, v]) => it[k as keyof GridItem] === v)) return null;
      const out = packed(items, id, next);
      const rects = rectsOf(out);
      return { key: `k:${id}:${JSON.stringify(next)}`, rects, landing: rects.get(id) ?? null, payload: out };
    },
    extent(rects) {
      let bottom = 0;
      for (const r of rects.values()) bottom = Math.max(bottom, r.y + r.h);
      return bottom;
    },
    label: (id) => deps.label?.(id) ?? id,
  };
}
