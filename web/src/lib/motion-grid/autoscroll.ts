
export const EDGE = 76;
export const MAX_SPEED = 1100;

export function edgeFactor(pos: number, lo: number, hi: number, edge = EDGE): number {
  if (pos < lo + edge) return -(1 - Math.max(pos - lo, 0) / edge);
  if (pos > hi - edge) return 1 - Math.max(hi - pos, 0) / edge;
  return 0;
}

export interface Autoscroll {
  step(clientY: number, dt: number): boolean;
  reset(): void;
}

export function createAutoscroll(win: Window, scroller: HTMLElement | null, enabled: () => boolean): Autoscroll {
  let box: DOMRect | null = null;
  return {
    reset() {
      box = null;
    },
    step(clientY, dt) {
      if (!enabled()) return false;
      let lo = 0;
      let hi = win.innerHeight;
      if (scroller) {
        const b = (box ??= scroller.getBoundingClientRect());
        lo = b.top;
        hi = b.bottom;
      }
      const f = edgeFactor(clientY, lo, hi);
      if (!f) return false;
      const dy = f * MAX_SPEED * dt;
      if (scroller) scroller.scrollTop += dy;
      else win.scrollBy(0, dy);
      return true;
    },
  };
}
