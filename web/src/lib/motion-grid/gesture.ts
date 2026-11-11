import type { Env, Point, Source } from './types';

export const MOUSE_THRESHOLD = 4;
export const LONG_PRESS_MS = 320;
export const LONG_PRESS_SLOP = 10;
const CLICK_GUARD_MS = 60;
const INTERACTIVE =
  'button,input,select,textarea,label,summary,[contenteditable],[data-no-drag],[role=button],[role=slider],[role=radio],[role=tab],[role=switch],[role=checkbox],[role=menuitem]';

export interface GestureHooks {
  hit(el: Element, ev: PointerEvent): Source | null;
  begin(source: Source, pt: Point, capture: Element): boolean;
  move(pt: Point): void;
  end(cancelled: boolean, pt: Point): void;
}

export interface GestureController {
  beginExternal(source: Source, ev: PointerEvent, capture: Element): boolean;
  cancel(): void;
  active(): boolean;
  destroy(): void;
}

interface Press {
  pid: number;
  type: string;
  source: Source;
  capture: Element;
  x0: number;
  y0: number;
  x: number;
  y: number;
  timer: ReturnType<typeof setTimeout> | null;
}

export function createGestureController(
  env: Env,
  container: HTMLElement,
  enabled: () => boolean,
  hooks: GestureHooks,
): GestureController {
  const win = env.win;
  let press: Press | null = null;
  let live: { pid: number; capture: Element; last: Point } | null = null;
  let suppress = false;
  let suppressTimer: ReturnType<typeof setTimeout> | null = null;

  const pt = (e: PointerEvent): Point => ({ x: e.clientX, y: e.clientY });

  const dropPress = (): void => {
    if (press?.timer) clearTimeout(press.timer);
    press = null;
    win.removeEventListener('pointermove', onPressMove, true);
    win.removeEventListener('pointerup', onPressEnd, true);
    win.removeEventListener('pointercancel', onPressEnd, true);
  };

  const lift = (source: Source, p: Point, pid: number, capture: Element): boolean => {
    if (!hooks.begin(source, p, capture)) return false;
    live = { pid, capture, last: p };
    try {
      capture.setPointerCapture(pid);
    } catch {
    }
    try {
      win.getSelection()?.removeAllRanges();
    } catch {
    }
    suppress = true;
    if (suppressTimer) clearTimeout(suppressTimer);
    win.addEventListener('pointermove', onMove, true);
    win.addEventListener('pointerup', onUp, true);
    win.addEventListener('pointercancel', onLost, true);
    capture.addEventListener('lostpointercapture', onLostCapture);
    win.addEventListener('keydown', onKey, true);
    win.addEventListener('blur', onBlur);
    env.doc.addEventListener('visibilitychange', onVisibility);
    return true;
  };

  const finish = (cancelled: boolean): void => {
    const g = live;
    if (!g) return;
    live = null;
    win.removeEventListener('pointermove', onMove, true);
    win.removeEventListener('pointerup', onUp, true);
    win.removeEventListener('pointercancel', onLost, true);
    g.capture.removeEventListener('lostpointercapture', onLostCapture);
    win.removeEventListener('keydown', onKey, true);
    win.removeEventListener('blur', onBlur);
    env.doc.removeEventListener('visibilitychange', onVisibility);
    try {
      if (g.capture.hasPointerCapture(g.pid)) g.capture.releasePointerCapture(g.pid);
    } catch {
    }
    suppressTimer = setTimeout(() => {
      suppress = false;
      suppressTimer = null;
    }, CLICK_GUARD_MS);
    hooks.end(cancelled, g.last);
  };

  function onPressMove(e: PointerEvent): void {
    if (!press || e.pointerId !== press.pid) return;
    press.x = e.clientX;
    press.y = e.clientY;
    const dist = Math.hypot(e.clientX - press.x0, e.clientY - press.y0);
    if (press.type === 'touch') {
      if (dist > LONG_PRESS_SLOP) dropPress();
    } else if (dist > MOUSE_THRESHOLD) {
      const p = press;
      dropPress();
      lift(p.source, { x: p.x0, y: p.y0 }, p.pid, p.capture);
      hooks.move({ x: p.x, y: p.y });
      if (live) live.last = { x: p.x, y: p.y };
    }
  }

  function onPressEnd(e: PointerEvent): void {
    if (press && e.pointerId === press.pid) dropPress();
  }

  function onMove(e: PointerEvent): void {
    if (!live || e.pointerId !== live.pid) return;
    live.last = pt(e);
    hooks.move(live.last);
  }
  function onUp(e: PointerEvent): void {
    if (!live || e.pointerId !== live.pid) return;
    live.last = pt(e);
    finish(false);
  }
  function onLost(e: PointerEvent): void {
    if (live && e.pointerId === live.pid) finish(true);
  }
  function onLostCapture(e: Event): void {
    if (live && e.target === live.capture) finish(true);
  }
  function onKey(e: KeyboardEvent): void {
    if (e.key !== 'Escape') return;
    e.preventDefault();
    finish(true);
  }
  function onBlur(): void {
    finish(true);
  }
  function onVisibility(): void {
    if (env.doc.visibilityState === 'hidden') finish(true);
  }

  const onDown = (e: PointerEvent): void => {
    if (!enabled() || live || press || !e.isPrimary) return;
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    const el = e.target as Element | null;
    if (!el || !el.closest) return;
    const source = hooks.hit(el, e);
    if (!source) return;
    if (source.kind !== 'move') {
      e.preventDefault();
      lift(source, pt(e), e.pointerId, el);
      return;
    }
    if (el.closest(INTERACTIVE) && !el.closest('[data-motion-grab]')) return;
    press = { pid: e.pointerId, type: e.pointerType, source, capture: el, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, timer: null };
    win.addEventListener('pointermove', onPressMove, true);
    win.addEventListener('pointerup', onPressEnd, true);
    win.addEventListener('pointercancel', onPressEnd, true);
    if (e.pointerType === 'touch') {
      press.timer = setTimeout(() => {
        const p = press;
        if (!p) return;
        dropPress();
        try {
          win.navigator.vibrate?.(8);
        } catch {
        }
        lift(p.source, { x: p.x, y: p.y }, p.pid, p.capture);
      }, LONG_PRESS_MS);
    }
  };

  const onTouchMove = (e: TouchEvent): void => {
    if (live && e.cancelable) e.preventDefault();
  };
  const onClick = (e: MouseEvent): void => {
    if (!suppress) return;
    e.preventDefault();
    e.stopPropagation();
  };
  const onDragStart = (e: Event): void => e.preventDefault();

  container.addEventListener('pointerdown', onDown);
  container.addEventListener('click', onClick, true);
  container.addEventListener('dragstart', onDragStart);
  win.addEventListener('touchmove', onTouchMove, { passive: false });

  return {
    beginExternal(source, ev, capture) {
      if (live || press) return false;
      return lift(source, pt(ev), ev.pointerId, capture);
    },
    cancel: () => finish(true),
    active: () => live !== null,
    destroy() {
      finish(true);
      dropPress();
      if (suppressTimer) clearTimeout(suppressTimer);
      container.removeEventListener('pointerdown', onDown);
      container.removeEventListener('click', onClick, true);
      container.removeEventListener('dragstart', onDragStart);
      win.removeEventListener('touchmove', onTouchMove);
    },
  };
}
