import type { Adapter, GestureState, ItemId, KeyStep, Rect, Target } from '../../../lib/motion-grid';

export interface StripAdapterDeps {
  order(): string[];
  measured(): ReadonlyMap<ItemId, Rect>;
  onDrop(id: ItemId, index: number): void;
  name?(id: ItemId): string;
}

export function flow(order: readonly ItemId[], measured: ReadonlyMap<ItemId, Rect>, gap: number): Map<ItemId, Rect> {
  const out = new Map<ItemId, Rect>();
  let x = 0;
  for (const id of order) {
    const r = measured.get(id);
    if (!r) continue;
    out.set(id, { x, y: r.y, w: r.w, h: r.h });
    x += r.w + gap;
  }
  return out;
}

export function insertionIndex(others: readonly ItemId[], rects: ReadonlyMap<ItemId, Rect>, x: number): number {
  return others.filter((id) => {
    const r = rects.get(id);
    return r !== undefined && x > r.x + r.w / 2;
  }).length;
}

export function createStripAdapter(deps: StripAdapterDeps, gap: number): Adapter {
  const gapPx = gap;
  const place = (id: ItemId, index: number, key: string): Target => {
    const others = deps.order().filter((one) => one !== id);
    const next = [...others.slice(0, index), id, ...others.slice(index)];
    const rects = flow(next, deps.measured(), gapPx);
    return { key, rects, landing: null, payload: { id, index } };
  };

  return {
    rects: () => flow(deps.order(), deps.measured(), gapPx),

    hit: () => null,

    targetKey(g: GestureState) {
      const id = (g.source as { id: string }).id;
      const others = deps.order().filter((one) => one !== id);
      return String(insertionIndex(others, g.base, g.pointer.x));
    },

    preview: (g, key) => place((g.source as { id: string }).id, Number(key), key),

    commit(target) {
      const payload = target.payload as { id: ItemId; index: number } | undefined;
      if (payload) deps.onDrop(payload.id, payload.index);
    },

    cancel() {
      // there is nothing
    },

    stepFromTarget: true,
    step(id: ItemId, step: KeyStep, from?: Target | null) {
      if (step.resize || (step.dir !== 'left' && step.dir !== 'right')) return null;
      const order = deps.order();
      const at = from ? (from.payload as { index: number }).index : order.indexOf(id);
      const to = at + (step.dir === 'left' ? -1 : 1);
      if (at < 0 || to < 0 || to >= order.length) return null;
      return place(id, to, `k:${to}`);
    },

    label: (id) => deps.name?.(id) ?? id,
  };
}
