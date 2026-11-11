/* a wrapping row */

import { beginGesture } from '../../opscenter/engine/pointer';
import { ZONE_DRAG_THRESHOLD, type ZoneDragHandlers } from '../zone-motion/area-drag.svelte';

export const glanceDrag: { index: number | null; carrying: boolean } = $state({
  index: null,
  carrying: false,
});

export function glanceAreaElement(doc: Document = document): HTMLElement | null {
  return doc.querySelector<HTMLElement>('[data-zone-glances]');
}

export function glanceIndexAt(x: number, y: number, skip: string | null = null, doc: Document = document): number | null {
  const root = glanceAreaElement(doc);
  if (!root) return null;
  const box = root.getBoundingClientRect();
  if (x < box.left || x > box.right || y < box.top || y > box.bottom) return null;
  let index = 0;
  for (const item of root.querySelectorAll<HTMLElement>('[data-glance-row-place]')) {
    if (item.dataset['glanceRowPlace'] === skip) continue;
    const rect = item.getBoundingClientRect();
    const rowAbove = rect.bottom <= y;
    const sameRow = y >= rect.top && y < rect.bottom;
    if (rowAbove || (sameRow && x > rect.left + rect.width / 2)) index += 1;
  }
  return index;
}

function beginGlanceDrag(element: HTMLElement, event: PointerEvent, skip: string | null, handlers: ZoneDragHandlers): boolean {
  return beginGesture(element, event, {
    threshold: ZONE_DRAG_THRESHOLD,
    onLift: () => {
      glanceDrag.carrying = true;
    },
    onMove: (_dx, _dy, move) => {
      const index = glanceIndexAt(move.clientX, move.clientY, skip, element.ownerDocument);
      glanceDrag.index = index;
      handlers.onMove?.(move.clientX, move.clientY, index !== null);
    },
    onDrop: () => {
      const index = glanceDrag.index;
      glanceDrag.index = null;
      if (index !== null) handlers.onDrop(index);
    },
    onEnd: (lifted) => {
      glanceDrag.index = null;
      glanceDrag.carrying = false;
      handlers.onEnd?.(lifted);
    },
  });
}

export function beginGlancePlacementDrag(handle: HTMLElement, event: PointerEvent, id: string, handlers: ZoneDragHandlers): boolean {
  return beginGlanceDrag(handle, event, id, handlers);
}
