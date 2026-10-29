
import { spanOf, visualOrder } from '../spans';
import type { Layout, SlotId } from '../types';

export const EDGE_EPSILON = 1e-9;

export interface GridCell {
  id: SlotId | null;
  top: number;
  bottom: number;
  x0: number;
  x1: number;
}

export interface GridGeometry {
  cells: GridCell[];
  rowSizes: number[];
}

function shares(frs: readonly number[]): number[] {
  const total = frs.reduce((sum, one) => (Number.isFinite(one) && one > 0 ? sum + one : sum), 0);
  if (total <= 0) return frs.map(() => 1 / frs.length);
  return frs.map((one) => (Number.isFinite(one) && one > 0 ? one / total : 0));
}

export function gridGeometry(layout: Layout): GridGeometry | null {
  const rows = layout.rows;
  const cells: GridCell[] = [];
  const pins = new Map<SlotId, { x: number; width: number }>();

  for (let rowAt = 0; rowAt < rows.length; rowAt += 1) {
    const row = rows[rowAt];
    if (!row) return null;
    const order = visualOrder(row);
    let cursor = 0;
    let at = 0;
    const hole = (to: number): void => {
      if (to - cursor > EDGE_EPSILON) cells.push({ id: null, top: rowAt, bottom: rowAt + 1, x0: cursor, x1: to });
    };
    while (at < order.length) {
      const entry = order[at];
      if (!entry) return null;
      if (entry.kind === 'reserved') {
        const pin = pins.get(entry.of);
        if (!pin || pin.x < cursor - EDGE_EPSILON || pin.x + pin.width > 1 + EDGE_EPSILON) return null;
        hole(pin.x);
        cursor = pin.x + pin.width;
        at += 1;
        continue;
      }
      let end = at;
      while (end < order.length && order[end]?.kind !== 'reserved') end += 1;
      const pocket = order.slice(at, end).flatMap((one) => (one.kind === 'slot' ? [one] : []));
      const next = order[end];
      const edge = next && next.kind === 'reserved' ? pins.get(next.of)?.x : 1;
      if (edge === undefined) return null;
      const space = edge - cursor;
      if (space <= EDGE_EPSILON * pocket.length) return null;
      const split = shares(pocket.map((one) => one.slot.fr));
      pocket.forEach((one, step) => {
        const width = (split[step] ?? 0) * space;
        const reach = Math.min(spanOf(one.slot), rows.length - rowAt);
        const x1 = step === pocket.length - 1 ? edge : cursor + width;
        cells.push({ id: one.slot.id, top: rowAt, bottom: rowAt + reach, x0: cursor, x1 });
        if (reach >= 2) pins.set(one.slot.id, { x: cursor, width: x1 - cursor });
        cursor = x1;
      });
      at = end;
    }
    if (cursor > 1 + EDGE_EPSILON) return null;
    hole(1);
  }
  if (cells.some((cell) => cell.id !== null && cell.x1 - cell.x0 <= EDGE_EPSILON)) return null;
  return { cells, rowSizes: rows.map((row) => row.size) };
}
