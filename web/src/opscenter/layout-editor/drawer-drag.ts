
import { acquireCarryHold, acquireDragHold } from '../../lib/motion-grid/drag-hold';
import { beginGesture, captureRows, pickTarget } from '../engine/pointer';
import type { DropTarget, LayoutStore } from '../engine/layout.svelte';
import type { LayoutPage, SlotId } from '../engine/types';

export const CARD_THRESHOLD = 6;

export function insideBox(box: Pick<DOMRect, 'left' | 'right' | 'top' | 'bottom'>, x: number, y: number): boolean {
  return x >= box.left && x <= box.right && y >= box.top && y <= box.bottom;
}

export interface PressHandlers {
  onLift?(): void;
  onMove(event: PointerEvent): 'handoff' | void;
  onDrop(event: PointerEvent): void;
  onEnd(lifted: boolean): void;
}

let pressing = false;

export function beginPress(card: HTMLElement, event: PointerEvent, handlers: PressHandlers): boolean {
  if (pressing || (event.button !== 0 && event.pointerType === 'mouse')) return false;
  pressing = true;
  const doc = card.ownerDocument;
  const win = doc.defaultView ?? window;
  const pid = event.pointerId;
  const x0 = event.clientX;
  const y0 = event.clientY;
  const touch = card.style.touchAction;
  const select = card.style.userSelect;
  let lifted = false;
  let release: (() => void) | null = null;
  card.style.touchAction = 'none';
  card.style.userSelect = 'none';
  try {
    card.setPointerCapture(pid);
  } catch {
  }

  const end = (handoff = false): void => {
    win.removeEventListener('pointermove', move);
    win.removeEventListener('pointerup', up);
    win.removeEventListener('pointercancel', cancel);
    win.removeEventListener('keydown', key, true);
    try {
      card.releasePointerCapture(pid);
    } catch {
    }
    card.style.touchAction = touch;
    card.style.userSelect = select;
    if (handoff && release) setTimeout(release, 0);
    else release?.();
    release = null;
    pressing = false;
    handlers.onEnd(lifted);
  };
  const move = (e: PointerEvent): void => {
    if (e.pointerId !== pid) return;
    if (!lifted) {
      if (Math.hypot(e.clientX - x0, e.clientY - y0) < CARD_THRESHOLD) return;
      lifted = true;
      const holds = [acquireDragHold(doc), acquireCarryHold(doc)];
      release = () => holds.forEach((h) => h());
      handlers.onLift?.();
    }
    if (handlers.onMove(e) === 'handoff') end(true);
  };
  const up = (e: PointerEvent): void => {
    if (e.pointerId !== pid) return;
    if (lifted) handlers.onDrop(e);
    end();
  };
  const cancel = (e: PointerEvent): void => {
    if (e.pointerId === pid) end();
  };
  const key = (e: KeyboardEvent): void => {
    if (e.key !== 'Escape') return;
    e.preventDefault();
    e.stopPropagation();
    end();
  };
  win.addEventListener('pointermove', move);
  win.addEventListener('pointerup', up);
  win.addEventListener('pointercancel', cancel);
  win.addEventListener('keydown', key, true);
  return true;
}


export function surfaceRoot(page: LayoutPage, doc: Document = document): HTMLElement | null {
  const scope = page === 'home' ? '#launchpad-screen' : page === 'warroom' ? '#warroom-screen' : '#terminal-grid';
  return doc.querySelector<HTMLElement>(`${scope} .oc-surface`);
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

