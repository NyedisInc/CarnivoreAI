
import { DRAWER_LEDGER_ID } from '../drawer-tabs/drawer-tabs';
import { createAreaDrag, type AreaDragState, type ZoneDragHandlers } from '../zone-motion/area-drag.svelte';

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
