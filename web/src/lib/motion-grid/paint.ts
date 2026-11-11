import { makeSpring, springActive, stepSpring, type Spring } from './spring';
import type { Rect } from './types';

export interface ItemState {
  id: string;
  el: HTMLElement;
  x: Spring;
  y: Spring;
  w: Spring;
  h: Spring;
  r: Spring;
  s: Spring;
  o: Spring;
  tf: string;
  cw: string;
  ch: string;
  co: string;
  rw: number;
  rh: number;
  lastR: number;
  dirty: boolean;
  mounted: boolean;
  fresh: boolean;
  settle: boolean;
  leaving: boolean;
  keepOpacity: boolean;
  flip: boolean;
  fw: number;
  fh: number;
  gx: number;
  gy: number;
  pv: Float64Array;
}

const KEYS = ['x', 'y', 'w', 'h', 'r', 's', 'o'] as const;

export function createItem(id: string, el: HTMLElement, flip = false): ItemState {
  return {
    id, el,
    x: makeSpring(0, 'pos'), y: makeSpring(0, 'pos'), w: makeSpring(0, 'size'), h: makeSpring(0, 'size'),
    r: makeSpring(0, 'rot'), s: makeSpring(1, 'sc'), o: makeSpring(1, 'op'),
    tf: '', cw: '', ch: '', co: '',
    rw: -1, rh: -1, lastR: 0, dirty: false, mounted: false, fresh: true, settle: false, leaving: false, keepOpacity: false,
    flip, fw: 0, fh: 0, gx: 0, gy: 0, pv: new Float64Array(8).fill(NaN),
  };
}

export function sizeMoving(it: ItemState): boolean {
  return springActive(it.w) || springActive(it.h);
}

export function itemMoving(it: ItemState): boolean {
  return KEYS.some((k) => springActive(it[k]));
}

export function stepItem(it: ItemState, dt: number, snap: boolean): boolean {
  let moving = false;
  for (const k of KEYS) if (stepSpring(it[k], dt, snap)) moving = true;
  return moving;
}

export function paintItem(it: ItemState): void {
  const sz = it.flip && it.fw > 0 && it.fh > 0 && sizeMoving(it);
  const p = it.pv;
  const { x, y, w, h, s, r, o } = { x: it.x.v, y: it.y.v, w: it.w.v, h: it.h.v, s: it.s.v, r: it.r.v, o: it.o.v };
  if (p[0] === x && p[1] === y && p[2] === w && p[3] === h && p[4] === s && p[5] === r && p[6] === o && p[7] === +sz) return;
  p[0] = x; p[1] = y; p[2] = w; p[3] = h; p[4] = s; p[5] = r; p[6] = o; p[7] = +sz;
  const spun = Math.abs(r) > 0.02;
  const scaled = Math.abs(s - 1) > 0.0005;
  let tx = x;
  let ty = y;
  if (it.flip && (it.gx || it.gy) && (spun || scaled)) {
    const a = (r * Math.PI) / 180;
    tx += it.gx - s * (it.gx * Math.cos(a) - it.gy * Math.sin(a));
    ty += it.gy - s * (it.gx * Math.sin(a) + it.gy * Math.cos(a));
  }
  let tf = `translate3d(${tx.toFixed(2)}px,${ty.toFixed(2)}px,0)`;
  if (spun) tf += ` rotate(${r.toFixed(2)}deg)`;
  if (scaled) tf += ` scale(${s.toFixed(4)})`;
  if (sz) {
    const sx = w / it.fw;
    const sy = h / it.fh;
    if (Math.abs(sx - 1) > 0.0005 || Math.abs(sy - 1) > 0.0005) tf += ` scale(${sx.toFixed(4)},${sy.toFixed(4)})`;
  }
  if (tf !== it.tf) {
    it.el.style.transform = tf;
    it.tf = tf;
  }
  if (!sz) {
    const ws = `${w.toFixed(1)}px`;
    const hs = `${h.toFixed(1)}px`;
    if (ws !== it.cw) {
      it.el.style.width = ws;
      it.cw = ws;
      it.fw = +w.toFixed(1);
    }
    if (hs !== it.ch) {
      it.el.style.height = hs;
      it.ch = hs;
      it.fh = +h.toFixed(1);
    }
  }
  const op = o.toFixed(3);
  if (op !== it.co) {
    it.el.style.opacity = op === '1.000' && !it.keepOpacity ? '' : op;
    it.co = op;
  }
}

export interface ItemRegistry {
  register(id: string, el: HTMLElement): ItemState;
  unregister(id: string): void;
  get(id: string): ItemState | undefined;
  idOf(el: Element): string | null;
  all(): IterableIterator<ItemState>;
}

export function createRegistry(flip = false): ItemRegistry {
  const byId = new Map<string, ItemState>();
  const byEl = new WeakMap<Element, string>();
  return {
    register(id, el) {
      const old = byId.get(id);
      if (old) byEl.delete(old.el);
      const it = createItem(id, el, flip);
      if (flip) el.style.transformOrigin = '0 0';
      byId.set(id, it);
      byEl.set(el, id);
      return it;
    },
    unregister(id) {
      const it = byId.get(id);
      if (it) byEl.delete(it.el);
      byId.delete(id);
    },
    get: (id) => byId.get(id),
    idOf: (el) => byEl.get(el) ?? null,
    all: () => byId.values(),
  };
}

export function setRect(it: ItemState, r: Rect, instant: boolean): void {
  const to: [Spring, number][] = [[it.x, r.x], [it.y, r.y], [it.w, r.w], [it.h, r.h]];
  for (const [s, v] of to) {
    s.t = v;
    if (instant) {
      s.v = v;
      s.vel = 0;
    }
  }
}

export function applyRects(reg: ItemRegistry, rects: ReadonlyMap<string, Rect>, instant: boolean, skip: string | null): void {
  for (const [id, r] of rects) {
    if (id === skip) continue;
    const it = reg.get(id);
    if (!it) continue;
    setRect(it, r, instant || it.fresh);
    it.fresh = false;
  }
}
