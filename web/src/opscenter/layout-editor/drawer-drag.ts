
import { beginGesture, captureRows, pickTarget } from '../engine/pointer';
import type { DropTarget, LayoutStore } from '../engine/layout.svelte';
import type { LayoutPage, SlotId } from '../engine/types';

export const CARD_THRESHOLD = 6;

export function surfaceRoot(page: LayoutPage, doc: Document = document): HTMLElement | null {
  const scope = page === 'home' ? '#launchpad-screen' : page === 'warroom' ? '#warroom-screen' : '#terminal-grid';
  return doc.querySelector<HTMLElement>(`${scope} .oc-surface`);
}

export function insideBox(box: Pick<DOMRect, 'left' | 'right' | 'top' | 'bottom'>, x: number, y: number): boolean {
  return x >= box.left && x <= box.right && y >= box.top && y <= box.bottom;
}

export interface CardDragHandlers {
  onMove: (x: number, y: number, target: DropTarget | null) => void;
  onDrop: (target: DropTarget) => void;
  onEnd: (lifted: boolean) => void;
}

export function beginCardDrag(
  card: HTMLElement,
  event: PointerEvent,
  id: SlotId,
  store: LayoutStore,
  page: LayoutPage,
  drawer: HTMLElement | null,
  handlers: CardDragHandlers,
): boolean {
  const root = surfaceRoot(page, card.ownerDocument);
  if (!root) return false;
  const scroller = root.closest<HTMLElement>('.oc-content');
  let rows: ReturnType<typeof captureRows>['rows'] = [];
  let cells: ReturnType<typeof captureRows>['cells'] = [];

  const contentY = (clientY: number): number =>
    scroller ? clientY - scroller.getBoundingClientRect().top + scroller.scrollTop : clientY;

  const overDrawer = (x: number, y: number): boolean => !!drawer && insideBox(drawer.getBoundingClientRect(), x, y);

  return beginGesture(card, event, {
    threshold: CARD_THRESHOLD,
    onLift: () => {
      ({ rows, cells } = captureRows(store, root, scroller, scroller?.scrollTop ?? 0));
      store.drag.target = null;
    },
    onMove: (_dx, _dy, move) => {
      const target = overDrawer(move.clientX, move.clientY)
        ? null
        : pickTarget(rows, cells, contentY(move.clientY), move.clientX, null);
      store.drag.target = target;
      handlers.onMove(move.clientX, move.clientY, target);
    },
    onDrop: () => {
      const target = store.drag.target;
      store.clearDrag();
      if (target) handlers.onDrop(target);
    },
    onEnd: (lifted) => {
      store.clearDrag();
      handlers.onEnd(lifted);
    },
  });
}

