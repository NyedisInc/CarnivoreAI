
import { beginGesture } from '../../opscenter/engine/pointer';
import { DRAWER_LEDGER_ID } from '../drawer-tabs/drawer-tabs';

export const ZONE_DRAG_THRESHOLD = 6;

export interface AreaDragState {
  index: number | null;
  carrying: boolean;
}

export interface ZoneDragHandlers {
  onMove?: (x: number, y: number, over: boolean) => void;
  onDrop: (index: number) => void;
  /* the glance area */
  onEnd?: (lifted: boolean, over?: boolean) => void;
}

export interface AreaDrag {
  readonly state: AreaDragState;
  element(doc?: Document): HTMLElement | null;
  indexAt(x: number, y: number, skip?: string | null, doc?: Document): number | null;
  beginCard(card: HTMLElement, event: PointerEvent, handlers: ZoneDragHandlers): boolean;
  beginItem(handle: HTMLElement, event: PointerEvent, key: string, handlers: ZoneDragHandlers): boolean;
}

export function indexInArea(root: HTMLElement | null, x: number, y: number, skip: string | null = null, axis: 'x' | 'y' = 'y'): number | null {
  if (!root || root.hidden) return null;
  const box = root.getBoundingClientRect();
  if (x < box.left || x > box.right || y < box.top || y > box.bottom) return null;
  const glance = root.querySelector<HTMLElement>('[data-glance-area]')?.getBoundingClientRect();
  if (glance && x >= glance.left && x <= glance.right && y >= glance.top && y <= glance.bottom) return null;
  let index = 0;
  for (const item of root.querySelectorAll<HTMLElement>('[data-zone-item]')) {
    if (item.dataset['zoneItem'] === skip) continue;
    const rect = item.getBoundingClientRect();
    if (axis === 'y' ? y > rect.top + rect.height / 2 : x > rect.left + rect.width / 2) index += 1;
  }
  return index;
}

export function createAreaDrag(elementId: string, axis: 'x' | 'y' = 'y'): AreaDrag {
  const state: AreaDragState = $state({ index: null, carrying: false });
  const element = (doc: Document = document): HTMLElement | null => doc.getElementById(elementId);
  const indexAt = (x: number, y: number, skip: string | null = null, doc: Document = document): number | null =>
    indexInArea(element(doc), x, y, skip, axis);

  function begin(pressed: HTMLElement, event: PointerEvent, skip: string | null, handlers: ZoneDragHandlers): boolean {
    let over = false;
    return beginGesture(pressed, event, {
      threshold: ZONE_DRAG_THRESHOLD,
      onLift: () => {
        state.carrying = true;
      },
      onMove: (_dx, _dy, move) => {
        const index = indexAt(move.clientX, move.clientY, skip, pressed.ownerDocument);
        state.index = index;
        over = index !== null;
        handlers.onMove?.(move.clientX, move.clientY, over);
      },
      onDrop: () => {
        const index = state.index;
        state.index = null;
        if (index !== null) handlers.onDrop(index);
      },
      onEnd: (lifted) => {
        state.index = null;
        state.carrying = false;
        handlers.onEnd?.(lifted, over);
      },
    });
  }

  return {
    state,
    element,
    indexAt,
    beginCard: (card, event, handlers) => begin(card, event, null, handlers),
    beginItem: (handle, event, key, handlers) => begin(handle, event, key, handlers),
  };
}

const drawerArea = createAreaDrag(DRAWER_LEDGER_ID);

export const zoneDrag: AreaDragState = drawerArea.state;

export function zoneIndexAt(x: number, y: number, skip: string | null = null, doc: Document = document): number | null {
  return drawerArea.indexAt(x, y, skip, doc);
}

export function beginZoneCardDrag(card: HTMLElement, event: PointerEvent, handlers: ZoneDragHandlers): boolean {
  return drawerArea.beginCard(card, event, handlers);
}

export function beginZoneItemDrag(
  handle: HTMLElement,
  event: PointerEvent,
  widget: string,
  handlers: ZoneDragHandlers,
): boolean {
  return drawerArea.beginItem(handle, event, widget, handlers);
}
