
import { motionReduced } from '../../../lib/motion/motion';

export interface TierDragOptions {
  onReorder?: (keys: string[]) => void;
  onHold?: (key: string, x: number, y: number) => void;
}

export const MOUSE_SLOP = 5;
export const HOLD_MS = 500;
export const TOUCH_SLOP = 8;
const EDGE = 24;
const GLIDE_MS = 180;
const MAX_TILT = 18;
const SWING_DECAY = 0.86;

export function nearestSlot(slots: readonly DOMRect[], x: number, y: number): number {
  let best = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  slots.forEach((r, i) => {
    const d = (r.left + r.width / 2 - x) ** 2 + (r.top + r.height / 2 - y) ** 2;
    if (d < bestDistance) { bestDistance = d; best = i; }
  });
  return best;
}

export function slotOf(i: number, from: number, to: number): number {
  if (from < to && i > from && i <= to) return i - 1;
  if (to < from && i >= to && i < from) return i + 1;
  return i;
}

export function moved(keys: readonly string[], from: number, to: number): string[] {
  const next = [...keys];
  const [key] = next.splice(from, 1);
  next.splice(to, 0, key as string);
  return next;
}

interface Drag {
  el: HTMLElement;
  items: HTMLElement[];
  slots: DOMRect[];
  from: number;
  to: number;
  pointerId: number;
  touch: boolean;
  startX: number;
  startY: number;
  x: number;
  y: number;
  lifted: boolean;
  moved: boolean;
  outside: boolean;
  tilt: number;
  swing: number;
  lastX: number;
  lastT: number;
  hold: ReturnType<typeof setTimeout> | null;
  frame: number;
}

export function tierDrag(grid: HTMLElement, options: TierDragOptions = {}): { update: (next: TierDragOptions) => void; destroy: () => void } {
  let opts = options;
  let drag: Drag | null = null;
  let swallowUntil = 0;
  const reduced = (): boolean => motionReduced();
  const itemsOf = (): HTMLElement[] => [...grid.children].filter((c): c is HTMLElement => c instanceof HTMLElement && c.dataset.swarmKey !== undefined);

  function paint(d: Drag): void {
    const still = reduced();
    const dx = d.x - d.startX;
    const dy = d.y - d.startY;
    d.el.style.transform = still ? `translate(${dx}px, ${dy}px)` : `translate(${dx}px, ${dy - 6}px) rotate(${d.tilt.toFixed(2)}deg) scale(1.08)`;
    d.items.forEach((item, i) => {
      if (i === d.from) return;
      const own = d.slots[i] as DOMRect;
      const to = d.slots[d.outside ? i : slotOf(i, d.from, d.to)] as DOMRect;
      item.style.transform = to === own ? '' : `translate(${to.left - own.left}px, ${to.top - own.top}px)`;
    });
  }

  function swingFrame(): void {
    const d = drag;
    if (!d || !d.lifted) return;
    d.swing *= SWING_DECAY;
    d.tilt += (d.swing - d.tilt) * 0.25;
    paint(d);
    d.frame = requestAnimationFrame(swingFrame);
  }

  function lift(d: Drag): void {
    d.items = itemsOf();
    d.from = d.items.indexOf(d.el);
    if (d.from < 0) return end(false);
    d.to = d.from;
    d.slots = d.items.map((i) => i.getBoundingClientRect());
    d.lifted = true;
    const r = d.slots[d.from] as DOMRect;
    d.el.style.transformOrigin = `${d.startX - r.left}px ${d.startY - r.top}px`;
    grid.classList.add('pkp-drag-on');
    d.el.classList.add('pkp-drag-lift');
    d.el.setAttribute('aria-grabbed', 'true');
    window.getSelection?.()?.removeAllRanges();
    try { grid.setPointerCapture(d.pointerId); } catch {  }
    paint(d);
    if (!reduced()) d.frame = requestAnimationFrame(swingFrame);
  }

  function clear(d: Drag): void {
    cancelAnimationFrame(d.frame);
    for (const item of d.items) { item.style.transform = ''; item.style.transformOrigin = ''; }
    d.el.classList.remove('pkp-drag-lift', 'pkp-drag-home');
    d.el.removeAttribute('aria-grabbed');
    grid.classList.remove('pkp-drag-on');
  }

  function end(drop: boolean): void {
    const d = drag;
    drag = null;
    window.removeEventListener('keydown', onKey, true);
    if (!d) return;
    if (d.hold) clearTimeout(d.hold);
    if (!d.lifted) return;
    swallowUntil = performance.now() + 400;
    try { grid.releasePointerCapture(d.pointerId); } catch {  }
    if (d.touch && !d.moved && drop) {
      clear(d);
      opts.onHold?.(d.el.dataset.swarmKey as string, d.x, d.y);
      return;
    }
    const changed = itemsOf();
    const same = changed.length === d.items.length && changed.every((c, i) => c === d.items[i]);
    const commit = drop && same && !d.outside && d.to !== d.from && opts.onReorder !== undefined;
    cancelAnimationFrame(d.frame);
    if (reduced()) {
      clear(d);
      if (commit) opts.onReorder?.(moved(changed.map((c) => c.dataset.swarmKey as string), d.from, d.to));
      return;
    }
    const own = d.slots[d.from] as DOMRect;
    const gap = d.slots[commit ? d.to : d.from] as DOMRect;
    d.el.classList.add('pkp-drag-home');
    d.el.style.transform = `translate(${gap.left - own.left}px, ${gap.top - own.top}px)`;
    if (!commit) for (const item of d.items) if (item !== d.el) item.style.transform = '';
    setTimeout(() => {
      clear(d);
      if (!commit) return;
      opts.onReorder?.(moved(changed.map((c) => c.dataset.swarmKey as string), d.from, d.to));
      d.el.classList.add('pkp-drag-plop');
      d.el.addEventListener('animationend', () => d.el.classList.remove('pkp-drag-plop'), { once: true });
      setTimeout(() => d.el.classList.remove('pkp-drag-plop'), 600);
    }, GLIDE_MS);
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || !drag) return;
    event.preventDefault();
    event.stopPropagation();
    end(false);
  }

  function onDown(event: PointerEvent): void {
    if (drag || (!opts.onReorder && !opts.onHold)) return;
    if (event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.pointerType !== 'touch' && event.button !== 0) return;
    const el = (event.target as Element | null)?.closest?.('[data-swarm-key]');
    if (!(el instanceof HTMLElement) || el.parentElement !== grid) return;
    const touch = event.pointerType === 'touch';
    drag = {
      el, items: [], slots: [], from: -1, to: -1, pointerId: event.pointerId, touch, startX: event.clientX, startY: event.clientY,
      x: event.clientX, y: event.clientY, lifted: false, moved: false, outside: false, tilt: 0, swing: 0, lastX: event.clientX,
      lastT: event.timeStamp, hold: null, frame: 0,
    };
    window.addEventListener('keydown', onKey, true);
    if (touch) {
      const d = drag;
      d.hold = setTimeout(() => {
        d.hold = null;
        if (drag === d) lift(d);
      }, HOLD_MS);
    }
  }

  function onMove(event: PointerEvent): void {
    const d = drag;
    if (!d || event.pointerId !== d.pointerId) return;
    d.x = event.clientX;
    d.y = event.clientY;
    const far = Math.hypot(d.x - d.startX, d.y - d.startY);
    if (!d.lifted) {
      if (d.touch) { if (far > TOUCH_SLOP) end(false); return; }
      if (far <= MOUSE_SLOP || !opts.onReorder) return;
      lift(d);
      if (!drag) return;
    }
    if (far > TOUCH_SLOP) d.moved = true;
    if (d.touch && !d.moved) return;
    if (!opts.onReorder) return;
    event.preventDefault();
    const dt = Math.max(1, event.timeStamp - d.lastT);
    const speed = (d.x - d.lastX) / dt;
    d.lastX = d.x;
    d.lastT = event.timeStamp;
    if (!reduced()) d.swing = Math.max(-MAX_TILT, Math.min(MAX_TILT, -speed * 14));
    const box = grid.getBoundingClientRect();
    d.outside = d.x < box.left - EDGE || d.x > box.right + EDGE || d.y < box.top - EDGE || d.y > box.bottom + EDGE;
    d.to = d.outside ? d.from : nearestSlot(d.slots, d.x, d.y);
    if (reduced()) paint(d);
  }

  function onUp(event: PointerEvent): void {
    if (drag && event.pointerId === drag.pointerId) end(true);
  }

  function onCancel(event: PointerEvent): void {
    if (drag && event.pointerId === drag.pointerId) end(false);
  }

  function onClick(event: MouseEvent): void {
    if (performance.now() >= swallowUntil) return;
    swallowUntil = 0;
    event.preventDefault();
    event.stopPropagation();
  }

  function onTouchMove(event: TouchEvent): void {
    if (drag?.lifted) event.preventDefault();
  }

  const noNativeDrag = (event: DragEvent): void => event.preventDefault();

  grid.addEventListener('pointerdown', onDown);
  window.addEventListener('pointermove', onMove, { passive: false });
  window.addEventListener('pointerup', onUp);
  window.addEventListener('pointercancel', onCancel);
  grid.addEventListener('click', onClick, true);
  grid.addEventListener('touchmove', onTouchMove, { passive: false });
  grid.addEventListener('dragstart', noNativeDrag);

  return {
    update(next: TierDragOptions): void { opts = next; },
    destroy(): void {
      if (drag) { const d = drag; drag = null; if (d.hold) clearTimeout(d.hold); if (d.lifted) clear(d); }
      window.removeEventListener('keydown', onKey, true);
      grid.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onCancel);
      grid.removeEventListener('click', onClick, true);
      grid.removeEventListener('touchmove', onTouchMove);
      grid.removeEventListener('dragstart', noNativeDrag);
    },
  };
}
