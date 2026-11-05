import { motionReduced } from '../motion/motion';
import { animationTypeOff } from '../motion/animation-types';
import { menuDragActive } from '../drawer-tabs/menu-drag';
import { railPeakScale } from './rail-magnify';

const RADIUS_PX = 76;
export const DOCK_ZOOM = 2;
const SETTLE_SLACK_MS = 50;

export interface DockHost {
  nav: () => HTMLElement | null;
  editing: () => boolean;
  onRest: () => void;
}

export interface Dock {
  measure: () => void;
  onPointerMove: (event: PointerEvent) => void;
  rest: () => void;
  stop: () => void;
  watch: () => () => void;
  restingY: (cell: HTMLElement) => number | undefined;
  destroy: () => void;
}

interface DockCell {
  el: HTMLElement;
  y: number;
  w: number;
  h: number;
}

function easeMs(nav: HTMLElement): number {
  const m = /^\s*(-?[\d.]+)\s*(ms|s)\s*$/.exec(getComputedStyle(nav).getPropertyValue('--dock-ease'));
  if (!m) return 0;
  const n = parseFloat(m[1]!);
  return Number.isFinite(n) ? (m[2] === 's' ? n * 1000 : n) : 0;
}

export function createDock(host: DockHost): Dock {
  let cells: DockCell[] = [];
  let frozen: DockCell[] = [];
  let frame = 0;
  let pointerY = 0;
  let undock = 0;
  let docked = false;

  function measure(): void {
    cells = [...(host.nav()?.querySelectorAll<HTMLElement>('[data-dock-name]') ?? [])].map((el) => {
      const r = el.getBoundingClientRect();
      return { el, y: r.top + r.height / 2, w: r.width, h: r.height };
    });
  }

  function dockIn(nav: HTMLElement): void {
    clearTimeout(undock);
    if (docked) return;
    docked = true;
    frozen = cells;
    for (const c of frozen) {
      c.el.style.setProperty('--dock-w', `${c.w}px`);
      c.el.style.setProperty('--dock-h', `${c.h}px`);
    }
    if (nav.scrollHeight <= nav.clientHeight + 1) nav.setAttribute('data-dock-spill', '');
    nav.setAttribute('data-docking', '');
    void nav.offsetWidth;
    nav.setAttribute('data-dock-live', '');
    void nav.offsetWidth;
  }

  function dockOut(): void {
    clearTimeout(undock);
    const nav = host.nav();
    nav?.removeAttribute('data-dock-live');
    nav?.removeAttribute('data-docking');
    nav?.removeAttribute('data-dock-spill');
    for (const c of frozen) {
      c.el.style.removeProperty('--dock-w');
      c.el.style.removeProperty('--dock-h');
    }
    frozen = [];
    docked = false;
  }

  function magnify(): void {
    frame = 0;
    const peak = railPeakScale();
    for (const c of cells) {
      const d = Math.abs(pointerY - c.y);
      const k = d >= RADIUS_PX ? 0 : (Math.cos((Math.PI * d) / RADIUS_PX) + 1) / 2;
      c.el.style.setProperty('--dock-s', String(1 + (peak - 1) * k));
    }
  }

  function onPointerMove(event: PointerEvent): void {
    if (event.pointerType === 'touch' || motionReduced() || animationTypeOff('transitions') || menuDragActive() || host.editing()) return;
    const nav = host.nav();
    if (!nav) return;
    if (railPeakScale() <= 1) {
      if (docked) stop();
      return;
    }
    if (cells.length === 0) measure();
    pointerY = event.clientY;
    dockIn(nav);
    if (frame === 0) frame = requestAnimationFrame(magnify);
  }

  function rest(): void {
    if (frame !== 0) cancelAnimationFrame(frame);
    frame = 0;
    for (const c of cells) c.el.style.removeProperty('--dock-s');
    cells = [];
    host.onRest();
    clearTimeout(undock);
    const nav = host.nav();
    if (docked && nav) undock = window.setTimeout(dockOut, easeMs(nav) + SETTLE_SLACK_MS);
  }

  function stop(): void {
    if (frame !== 0) cancelAnimationFrame(frame);
    frame = 0;
    for (const c of cells) c.el.style.removeProperty('--dock-s');
    cells = [];
    host.onRest();
    dockOut();
  }

  function watch(): () => void {
    const nav = host.nav();
    if (!nav) return () => {};
    const observer = new MutationObserver(() => {
      if (!docked) return;
      const now = [...nav.querySelectorAll<HTMLElement>('[data-dock-name]')];
      if (now.length !== frozen.length || now.some((el, i) => el !== frozen[i]?.el)) stop();
    });
    observer.observe(nav, { childList: true, subtree: true });
    return () => observer.disconnect();
  }

  function destroy(): void {
    stop();
  }

  return { measure, onPointerMove, rest, stop, watch, restingY: (cell) => cells.find((c) => c.el === cell)?.y, destroy };
}
