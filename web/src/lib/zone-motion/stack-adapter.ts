import type { Adapter, GestureState, ItemId, KeyStep, Rect, Source, Target } from '../motion-grid/types';

export interface StackItem {
  id: ItemId;
  w: number;
  h: number;
}

export interface StackResize {
  limits(id: ItemId): { min: number; max: number };
  commit(id: ItemId, h: number): void;
  step?: number;
}

export interface StackConfig {
  axis: 'y' | 'x';
  items(): readonly StackItem[];
  width(): number;
  pad?: { x: number; y: number };
  gap?: number;
  place(id: ItemId, index: number, external: boolean): void;
  resize?: StackResize;
  grab?: string;
  grabControls?: boolean;
  label?(id: ItemId): string;
}

export const NO_GRAB = 'button, a, input, select, textarea, [contenteditable], [role="menu"], [data-motion-nograb]';

export const STACK_ID_ATTR = 'data-stack-id';

export const STACK_RESIZE_ATTR = 'data-stack-resize';

type Payload = { id: ItemId; index?: number; h?: number; external?: boolean };

export function layoutStack(order: readonly StackItem[], cfg: StackConfig, width: number, override?: { id: ItemId; h: number }): Map<ItemId, Rect> {
  const pad = cfg.pad ?? { x: 0, y: 0 };
  const gap = cfg.gap ?? 0;
  const out = new Map<ItemId, Rect>();
  const heightOf = (it: StackItem): number => (override && override.id === it.id ? override.h : it.h);
  if (cfg.axis === 'y') {
    let y = pad.y;
    for (const it of order) {
      const h = heightOf(it);
      out.set(it.id, { x: pad.x, y, w: Math.max(0, width - 2 * pad.x), h });
      y += h + gap;
    }
  } else {
    const row = order.reduce((m, it) => Math.max(m, heightOf(it)), 0);
    let x = pad.x;
    for (const it of order) {
      const h = heightOf(it);
      out.set(it.id, { x, y: pad.y + (row - h) / 2, w: it.w, h });
      x += it.w + gap;
    }
  }
  return out;
}

export function stackExtent(rects: ReadonlyMap<ItemId, Rect>, cfg: StackConfig): number | null {
  const pad = cfg.pad ?? { x: 0, y: 0 };
  let bottom = 0;
  for (const r of rects.values()) bottom = Math.max(bottom, r.y + r.h);
  return rects.size === 0 ? pad.y * 2 : bottom + pad.y;
}

export function createStackAdapter(cfg: StackConfig): Adapter {
  const horizontal = cfg.axis === 'x';
  const others = (id: ItemId): StackItem[] => cfg.items().filter((it) => it.id !== id);
  const rectsNow = (): Map<ItemId, Rect> => layoutStack(cfg.items(), cfg, cfg.width());
  const along = (p: { x: number; y: number }): number => (horizontal ? p.x : p.y);
  const indexOf = (id: ItemId): number => cfg.items().findIndex((it) => it.id === id);

  const insertion = (g: GestureState, id: ItemId): number => {
    let n = 0;
    for (const it of others(id)) {
      const r = g.base.get(it.id);
      if (!r) continue;
      const mid = horizontal ? r.x + r.w / 2 : r.y + r.h / 2;
      if (along(g.pointer) > mid) n += 1;
    }
    return n;
  };

  const sized = (g: GestureState, id: ItemId): number => {
    const { min, max } = cfg.resize!.limits(id);
    const from = g.startRect?.h ?? 0;
    return Math.round(Math.min(max, Math.max(min, from + g.delta.y)));
  };

  const target = (order: readonly StackItem[], key: string, payload: Payload, override?: { id: ItemId; h: number }): Target => ({
    key,
    rects: layoutStack(order, cfg, cfg.width(), override),
    payload,
  });

  return {
    rects: rectsNow,
    hit(el: Element): Source | null {
      const cell = el.closest<HTMLElement>(`[${STACK_ID_ATTR}]`);
      if (!cell) return null;
      const id = cell.getAttribute(STACK_ID_ATTR) as ItemId;
      if (cfg.resize && el.closest(`[${STACK_RESIZE_ATTR}]`)) return { kind: 'resize', id, edge: 's' };
      const region = cfg.grab ? el.closest(cfg.grab) : cell;
      if (!region || !cell.contains(region)) return null;
      const control = el.closest(NO_GRAB);
      if (control && cell.contains(control) && !(cfg.grabControls && !el.closest('[data-motion-nograb]'))) return null;
      return { kind: 'move', id };
    },
    targetKey(g) {
      if (g.source.kind === 'resize') return `r${sized(g, g.source.id)}`;
      const id = (g.source as { id: ItemId }).id;
      return g.outside ? 'out' : String(insertion(g, id));
    },
    preview(g, key) {
      const source = g.source;
      if (source.kind === 'resize') {
        const h = sized(g, source.id);
        return target(cfg.items(), key, { id: source.id, h }, { id: source.id, h });
      }
      const id = (source as { id: ItemId }).id;
      if (key === 'out') return { key, rects: new Map(g.base), valid: false };
      const index = Number(key);
      const active = cfg.items().find((it) => it.id === id);
      const next = others(id);
      if (active) next.splice(index, 0, active);
      return target(next, key, { id, index, external: source.kind === 'external' });
    },
    activeRect(g) {
      const r = g.startRect ?? { x: 0, y: 0, w: 0, h: 0 };
      const id = (g.source as { id: ItemId }).id;
      return { ...r, h: cfg.resize ? sized(g, id) : r.h };
    },
    commit(t) {
      const p = t.payload as Payload | undefined;
      if (!p) return;
      const now = cfg.items().find((it) => it.id === p.id);
      if (p.index !== undefined && (p.external || indexOf(p.id) !== p.index)) cfg.place(p.id, p.index, !!p.external);
      if (p.h !== undefined && now && Math.round(now.h) !== p.h) cfg.resize?.commit(p.id, p.h);
    },
    cancel() {
      // there is nothing
    },
    stepFromTarget: true,
    step(id: ItemId, step: KeyStep, from?: Target | null): Target | null {
      const prev = from?.payload as Payload | undefined;
      let items: readonly StackItem[] = cfg.items();
      if (prev?.index !== undefined) {
        const held = items.find((it) => it.id === id);
        const reordered = others(id);
        if (held) reordered.splice(prev.index, 0, held);
        items = reordered;
      }
      const at = items.findIndex((it) => it.id === id);
      if (at < 0) return null;
      const forward = horizontal ? 'right' : 'down';
      const back = horizontal ? 'left' : 'up';
      if (step.resize) {
        if (!cfg.resize || horizontal || (step.dir !== 'down' && step.dir !== 'up')) return null;
        const { min, max } = cfg.resize.limits(id);
        const size = cfg.resize.step ?? 16;
        const now = prev?.h ?? items[at]!.h;
        const h = Math.min(max, Math.max(min, now + (step.dir === 'down' ? size : -size)));
        if (h === now) return null;
        return target(items, `k${prev?.index ?? ''}r${h}`, { id, index: prev?.index, h }, { id, h });
      }
      const to = step.dir === forward ? at + 1 : step.dir === back ? at - 1 : -1;
      if (to < 0 || to >= items.length) return null;
      const next = items.filter((it) => it.id !== id);
      next.splice(to, 0, items[at]!);
      return target(next, `k${to}r${prev?.h ?? ''}`, { id, index: to, h: prev?.h }, prev?.h === undefined ? undefined : { id, h: prev.h });
    },
    extent: (rects) => stackExtent(rects, cfg),
    label: cfg.label,
  };
}
