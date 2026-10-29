/*  hidden  */
import type { DropTarget } from '../engine/layout.svelte';
import { rowOfCell } from '../engine/model';
import { visualOrder } from '../engine/spans';
import type { Layout, SlotId } from '../engine/types';
import type { GallerySize } from '../viz/presets';

export function galleryTarget(layout: Layout, id: SlotId, focus: SlotId | null, size: GallerySize): DropTarget | null {
  const row = focus && focus !== id ? rowOfCell(layout, focus) : undefined;
  if (!row) {
    const last = layout.rows.at(-1);
    return last && last.slots.some((slot) => slot.id !== id) ? { kind: 'new', after: last.id } : null;
  }
  if (size === 'full') return { kind: 'new', after: row.id };
  const column = visualOrder(row).findIndex((cell) => cell.kind === 'slot' && cell.slot.id === focus);
  return column < 0 ? null : { kind: 'row', row: row.id, index: column + 1 };
}
