
import { tick } from 'svelte';
import { META, metaFor } from './meta';
import { flipCells, measureCells } from './flip';
import { columnDropAt } from './drop';
import type { DropTarget, LayoutStore } from './layout.svelte';
import type { RowId, SlotId } from './types';
import { t } from '../../lib/i18n/index.svelte';
import { tearOffCell } from '../../lib/tearoff/tearoff';

export interface GestureHandlers {
  threshold?: number;
  coalesce?: boolean;
  onLift?: (event: PointerEvent) => void;
  onMove: (dx: number, dy: number, event: PointerEvent) => void;
  onDrop?: (dx: number, dy: number, event: PointerEvent) => void;
  onCancel?: () => void;
  onEnd?: (lifted: boolean) => void;
}

interface ActiveGesture {
  element: HTMLElement;
  pointerId: number;
  originX: number;
  originY: number;
  lifted: boolean;
  finished: boolean;
  handlers: GestureHandlers;
  touchAction: string;
  userSelect: string;
}

let active: ActiveGesture | null = null;

let abandonActive: (() => void) | null = null;

export function abandonGesture(): boolean {
  if (!abandonActive) return false;
  abandonActive();
  return true;
}

export function gestureActive(): boolean {
  return active !== null;
}

function setDragging(on: boolean): void {
  if (typeof document === 'undefined') return;
  document.body.classList.toggle('grid-dragging', on);
}

export function beginGesture(element: HTMLElement, event: PointerEvent, handlers: GestureHandlers): boolean {
  if (active) return false;
  if (event.button !== 0 && event.pointerType === 'mouse') return false;

  const gesture: ActiveGesture = {
    element,
    pointerId: event.pointerId,
    originX: event.clientX,
    originY: event.clientY,
    lifted: false,
    finished: false,
    handlers,
    touchAction: element.style.touchAction,
    userSelect: element.style.userSelect,
  };
  active = gesture;

  element.style.touchAction = 'none';
  element.style.userSelect = 'none';
  try {
    element.setPointerCapture(event.pointerId);
  } catch {
  }

  const threshold = handlers.threshold ?? 0;

  const lift = (moveEvent: PointerEvent): void => {
    gesture.lifted = true;
    setDragging(true);
    handlers.onLift?.(moveEvent);
  };

  const onMove = (moveEvent: PointerEvent): void => {
    if (gesture.finished || moveEvent.pointerId !== gesture.pointerId) return;
    const dx = moveEvent.clientX - gesture.originX;
    const dy = moveEvent.clientY - gesture.originY;
    if (!gesture.lifted) {
      if (Math.abs(dx) < threshold && Math.abs(dy) < threshold) return;
      lift(moveEvent);
    }
    if (!handlers.coalesce) {
      handlers.onMove(dx, dy, moveEvent);
      return;
    }
    pending = { dx, dy, event: moveEvent };
    if (frame === 0) {
      frame = requestAnimationFrame(() => {
        frame = 0;
        const next = pending;
        pending = null;
        if (next && !gesture.finished) handlers.onMove(next.dx, next.dy, next.event);
      });
    }
  };

  let frame = 0;
  let pending: { dx: number; dy: number; event: PointerEvent } | null = null;
  const clearFrame = (): void => {
    if (frame !== 0) cancelAnimationFrame(frame);
    frame = 0;
    pending = null;
  };

  const onUp = (upEvent: PointerEvent): void => {
    if (upEvent.pointerId !== gesture.pointerId) return;
    const dx = upEvent.clientX - gesture.originX;
    const dy = upEvent.clientY - gesture.originY;
    if (gesture.lifted) {
      if (handlers.coalesce) {
        clearFrame();
        handlers.onMove(dx, dy, upEvent);
      }
      handlers.onDrop?.(dx, dy, upEvent);
    }
    finish(false);
  };

  const onLost = (lostEvent: PointerEvent): void => {
    if (lostEvent.pointerId !== gesture.pointerId) return;
    if (lostEvent.type === 'lostpointercapture' && lostEvent.target !== element) return;
    finish(true);
  };

  const onKey = (keyEvent: KeyboardEvent): void => {
    if (keyEvent.key !== 'Escape') return;
    keyEvent.preventDefault();
    finish(true);
  };

  const onBlur = (): void => finish(true);
  const onVisibility = (): void => {
    if (document.visibilityState === 'hidden') finish(true);
  };

  let abandoned = false;

  function finish(cancelled: boolean): void {
    if (gesture.finished) return;
    gesture.finished = true;
    clearFrame();
    element.removeEventListener('pointermove', onMove);
    element.removeEventListener('pointerup', onUp);
    element.removeEventListener('pointercancel', onLost);
    element.removeEventListener('lostpointercapture', onLost);
    window.removeEventListener('keydown', onKey, true);
    window.removeEventListener('blur', onBlur);
    document.removeEventListener('visibilitychange', onVisibility);
    try {
      if (element.hasPointerCapture(gesture.pointerId)) element.releasePointerCapture(gesture.pointerId);
    } catch {
    }
    element.style.touchAction = gesture.touchAction;
    element.style.userSelect = gesture.userSelect;
    setDragging(false);
    active = null;
    abandonActive = null;
    if (cancelled && !abandoned) handlers.onCancel?.();
    handlers.onEnd?.(gesture.lifted);
  }

  element.addEventListener('pointermove', onMove);
  element.addEventListener('pointerup', onUp);
  element.addEventListener('pointercancel', onLost);
  element.addEventListener('lostpointercapture', onLost);
  window.addEventListener('keydown', onKey, true);
  window.addEventListener('blur', onBlur);
  document.addEventListener('visibilitychange', onVisibility);

  abandonActive = () => {
    abandoned = true;
    finish(true);
  };
  if (threshold === 0) lift(event);
  return true;
}



export interface RowTarget {
  id: RowId;
  top: number;
  bottom: number;
  centres: number[];
  reserved: [number, number][];
}

export interface CellDragMerge {
  aim(clientX: number, clientY: number): boolean;
  drop(): boolean;
  end(): void;
}

const CELL_THRESHOLD = 6;

const EDGE = 6;

const STACK_BAND = 0.25;

export interface CellTarget {
  id: SlotId;
  left: number;
  right: number;
  top: number;
  bottom: number;
}

const AUTOSCROLL_EDGE = 48;

const AUTOSCROLL_DIVISOR = 4;

function cellTitle(id: SlotId): string {
  const meta = metaFor(id, META);
  return meta.titleName ?? t(meta.titleKey);
}

/* at the same time */
export function captureRows(
  store: LayoutStore,
  root: ParentNode,
  scroller: HTMLElement | null,
  scrollTop: number,
): { rows: RowTarget[]; cells: CellTarget[] } {
  const origin = scroller ? scroller.getBoundingClientRect().top - scrollTop : 0;
  const targets: RowTarget[] = [];
  const cells: CellTarget[] = [];
  for (const row of store.state.layout.rows) {
    const element = root.querySelector<HTMLElement>(`.oc-row[data-row="${row.id}"]`);
    if (!element) continue;
    const rect = element.getBoundingClientRect();
    const centres: number[] = [];
    const reserved: [number, number][] = [];
    for (const cell of element.querySelectorAll<HTMLElement>('.oc-cellslot')) {
      const box = cell.getBoundingClientRect();
      centres.push(box.x + box.width / 2);
      if (cell.classList.contains('oc-cellslot-reserved')) reserved.push([box.x, box.x + box.width]);
      const slot = cell.dataset['slot'];
      if (slot) {
        cells.push({ id: slot as SlotId, left: box.x, right: box.x + box.width, top: box.top - origin, bottom: box.bottom - origin });
      }
    }
    targets.push({ id: row.id, top: rect.top - origin, bottom: rect.bottom - origin, centres, reserved });
  }
  return { rows: targets, cells };
}

export function pickTarget(
  rows: readonly RowTarget[],
  cells: readonly CellTarget[],
  contentY: number,
  clientX: number,
  dragged: SlotId | null,
): DropTarget | null {
  const first = rows[0];
  const last = rows[rows.length - 1];
  if (!first || !last) return null;
  if (contentY < first.top + EDGE) return { kind: 'new', after: null };
  if (contentY > last.bottom - EDGE) return { kind: 'new', after: last.id };
  for (let at = 0; at < rows.length - 1; at += 1) {
    const above = rows[at];
    const below = rows[at + 1];
    if (!above || !below) continue;
    if (contentY > above.bottom - EDGE && contentY < below.top + EDGE) return { kind: 'new', after: above.id };
  }
  const over = cells.find(
    (cell) =>
      cell.id !== dragged &&
      clientX >= cell.left &&
      clientX <= cell.right &&
      contentY >= cell.top &&
      contentY <= cell.bottom,
  );
  if (over) {
    const band = (over.bottom - over.top) * STACK_BAND;
    if (contentY < over.top + band) return { kind: 'stack', of: over.id, edge: 'above' };
    if (contentY > over.bottom - band) return { kind: 'stack', of: over.id, edge: 'below' };
  }
  const row = rows.find(
    (entry) =>
      contentY >= entry.top &&
      contentY <= entry.bottom &&
      !entry.reserved.some(([start, end]) => clientX >= start && clientX <= end),
  );
  if (!row) return null;
  let index = 0;
  for (const centre of row.centres) {
    if (clientX > centre) index += 1;
  }
  return { kind: 'row', row: row.id, index };
}

export function beginCellDrag(
  handle: HTMLElement,
  event: PointerEvent,
  id: SlotId,
  store: LayoutStore,
  merge?: CellDragMerge,
): boolean {
  let rows: RowTarget[] = [];
  let cells: CellTarget[] = [];
  const dragState = store.drag;
  const root: ParentNode = handle.closest('.oc-surface') ?? handle.ownerDocument;
  const scroller = handle.closest<HTMLElement>('.oc-content');
  let frame = 0;
  let lastX = 0;
  let lastY = 0;

  const contentY = (clientY: number): number =>
    scroller ? clientY - scroller.getBoundingClientRect().top + scroller.scrollTop : clientY;

  const aim = (): void => {
    if (merge?.aim(lastX, lastY)) {
      dragState.target = null;
      return;
    }
    const picked = pickTarget(rows, cells, contentY(lastY), lastX, id);
    const column = picked?.kind === 'row' ? columnDropAt(store.state.layout, picked.row, picked.index, id) : null;
    dragState.target = column ?? picked;
  };

  const creep = (): void => {
    frame = 0;
    if (!scroller) return;
    const box = scroller.getBoundingClientRect();
    let step = 0;
    if (lastY < box.top + AUTOSCROLL_EDGE) step = -(box.top + AUTOSCROLL_EDGE - lastY) / AUTOSCROLL_DIVISOR;
    else if (lastY > box.bottom - AUTOSCROLL_EDGE) step = (lastY - (box.bottom - AUTOSCROLL_EDGE)) / AUTOSCROLL_DIVISOR;
    if (step !== 0) {
      scroller.scrollTop += step;
      aim();
    }
    frame = requestAnimationFrame(creep);
  };

  return beginGesture(handle, event, {
    threshold: CELL_THRESHOLD,
    onLift: () => {
      ({ rows, cells } = captureRows(store, root, scroller, scroller?.scrollTop ?? 0));
      dragState.id = id;
      dragState.dx = 0;
      dragState.dy = 0;
      dragState.target = null;
      if (scroller && typeof requestAnimationFrame === 'function') frame = requestAnimationFrame(creep);
    },
    onMove: (dx, dy, moveEvent) => {
      dragState.dx = dx;
      dragState.dy = dy;
      lastX = moveEvent.clientX;
      lastY = moveEvent.clientY;
      aim();
    },
    onDrop: (_dx, _dy, up) => {
      if (tearOffCell(id, up)) return;
      if (merge?.drop()) return;
      const target = dragState.target;
      if (!target) return;
      const before = measureCells();
      const scrolledFrom = scroller?.scrollTop ?? 0;
      const moved = store.moveTo(id, target);
      store.clearDrag();
      if (!moved) return;
      if (target.kind === 'stack') {
        store.announce(
          t(target.edge === 'above' ? 'opscenter.layout.cell_stacked_above' : 'opscenter.layout.cell_stacked_below', {
            title: cellTitle(id),
            other: cellTitle(target.of),
          }),
        );
      } else {
        store.announce(
          t(target.kind === 'new' ? 'opscenter.layout.row_added' : 'opscenter.layout.cell_moved', {
            title: cellTitle(id),
          }),
        );
      }
      void tick().then(() => flipCells(before, (scroller?.scrollTop ?? 0) - scrolledFrom));
    },
    onEnd: () => {
      merge?.end();
      if (frame && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(frame);
      frame = 0;
      store.clearDrag();
    },
  });
}
