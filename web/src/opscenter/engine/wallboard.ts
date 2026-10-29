import type { Layout, RowModel, SlotId } from './types';
import type { DragState, LayoutStore } from './layout.svelte';
import { GUTTER } from './tracks';

const FALLBACK_ROW_PX = 280;

const MIN_ROW_PX = 180;

export const WALLBOARD_PARAM = 'view';
export const WALLBOARD_VALUE = 'wallboard';

const READ_ONLY_MEMBERS: ReadonlySet<string> = new Set([
  'page',
  'session',
  'state',
  'drag',
  'announce',
  'announceLater',
  'hiddenCells',
  'isCollapsed',
  'spanRefusal',
  'snapshot',
]);

export function isWallboardSearch(search: string): boolean {
  return new URLSearchParams(search).get(WALLBOARD_PARAM) === WALLBOARD_VALUE;
}

export function wallboardLayout(layout: Layout, availablePx = 0): Layout {
  const kept = layout.rows
    .map((row): RowModel => ({
      id: row.id,
      kind: 'px',
      size: row.kind === 'px' ? row.size : FALLBACK_ROW_PX,
      slots: row.slots
        .filter((slot) => slot.id.startsWith('analytics:'))
        .map((slot) => ({ id: slot.id as SlotId, fr: slot.fr })),
    }))
    .filter((row) => row.slots.length > 0);
  const total = kept.reduce((sum, row) => sum + row.size, 0);
  const free = availablePx - Math.max(0, kept.length - 1) * GUTTER;
  const scale = total > 0 && free > 0 ? free / total : 1;
  const rows = kept.map((row) => {
    const width = row.slots.reduce((sum, slot) => sum + slot.fr, 0) || 1;
    return { ...row, size: Math.max(MIN_ROW_PX, Math.floor(row.size * scale)), slots: row.slots.map((slot) => ({ ...slot, fr: slot.fr / width })) };
  });
  return { ...layout, rows, hidden: [] };
}

export function readOnlyStore(source: LayoutStore, surfaceHeight: () => number = () => 0): LayoutStore {
  const drag: DragState = { id: null, dx: 0, dy: 0, target: null };
  let held: { layout: Layout; height: number; announcement: string; view: LayoutStore['state'] } | null = null;
  return new Proxy(source, {
    get(target, prop, receiver): unknown {
      if (prop === 'state') {
        const live = target.state;
        const height = surfaceHeight();
        if (!held || held.layout !== live.layout || held.height !== height || held.announcement !== live.announcement) {
          const view = { layout: wallboardLayout(live.layout, height), warning: '', announcement: live.announcement };
          held = { layout: live.layout, height, announcement: live.announcement, view };
        }
        return held.view;
      }
      if (prop === 'drag') return drag;
      const value = Reflect.get(target, prop, receiver) as unknown;
      if (typeof prop === 'string' && READ_ONLY_MEMBERS.has(prop)) {
        return typeof value === 'function' ? (value as (...a: unknown[]) => unknown).bind(target) : value;
      }
      return typeof value === 'function' ? () => undefined : value;
    },
    set(): boolean {
      return true;
    },
  });
}
