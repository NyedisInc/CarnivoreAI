import { cellOf } from './column';
import { rowOfCell } from './model';
import { visualOrder } from './spans';
import type { DropTarget } from './layout.svelte';
import type { Layout, SlotId } from './types';

export type Zone = 'left' | 'right' | 'top' | 'bottom' | 'center';

export interface Box {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export const EDGE_SHARE = 0.25;

export function dropZone(box: Box, x: number, y: number): Zone | null {
  const width = box.right - box.left;
  const height = box.bottom - box.top;
  if (width <= 0 || height <= 0 || x < box.left || x > box.right || y < box.top || y > box.bottom) return null;
  const fx = (x - box.left) / width;
  const fy = (y - box.top) / height;
  const edges: [Zone, number][] = [
    ['left', fx],
    ['right', 1 - fx],
    ['top', fy],
    ['bottom', 1 - fy],
  ];
  const [zone, depth] = edges.reduce((best, edge) => (edge[1] < best[1] ? edge : best));
  return depth < EDGE_SHARE ? zone : 'center';
}

export function zoneTarget(layout: Layout, slot: SlotId, zone: Zone): DropTarget | null {
  if (zone === 'top' || zone === 'bottom') return { kind: 'stack', of: slot, edge: zone === 'top' ? 'above' : 'below' };
  if (zone === 'center') return null;
  const row = rowOfCell(layout, slot);
  if (!row) return null;
  const at = visualOrder(row).findIndex((entry) => cellOf(entry) === slot);
  if (at < 0) return null;
  return { kind: 'row', row: row.id, index: zone === 'left' ? at : at + 1 };
}

export function freeSlot(taken: readonly string[], candidates: readonly string[]): string | null {
  return candidates.find((id) => id.startsWith('terminal:') && !taken.includes(id)) ?? null;
}
