import { vi } from 'vitest';
import { mountMotion } from './index';
import type { Adapter, Env, GestureState, ItemId, MotionOptions, Rect, Target } from './types';

export function pev(type: string, x: number, y: number, init: { id?: number; pointerType?: string; button?: number } = {}): PointerEvent {
  const e = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: init.button ?? 0 });
  Object.defineProperty(e, 'pointerId', { value: init.id ?? 1 });
  Object.defineProperty(e, 'pointerType', { value: init.pointerType ?? 'mouse' });
  Object.defineProperty(e, 'isPrimary', { value: true });
  return e as unknown as PointerEvent;
}

export function makeKit(opts: MotionOptions = {}) {
  let clock = 0;
  const queue: ((t: number) => void)[] = [];
  const env: Env = {
    raf: (cb) => queue.push(cb),
    caf: () => {},
    now: () => clock,
    win: window,
    doc: document,
  };
  const container = document.createElement('div');
  document.body.appendChild(container);
  container.getBoundingClientRect = () =>
    ({ left: 0, top: 0, right: 400, bottom: 200, width: 400, height: 200, x: 0, y: 0, toJSON() {} }) as DOMRect;
  let order: ItemId[] = ['a', 'b', 'c'];
  const rectsFor = (o: ItemId[]): Map<ItemId, Rect> => new Map(o.map((id, i) => [id, { x: i * 110, y: 0, w: 100, h: 50 }]));
  const spies = {
    preview: vi.fn(),
    commit: vi.fn(),
    cancel: vi.fn(),
    step: vi.fn(),
    begin: vi.fn(),
  };
  const adapter: Adapter = {
    rects: () => rectsFor(order),
    hit(el) {
      const w = el.closest<HTMLElement>('[data-id]');
      if (!w) return null;
      const id = w.dataset.id as string;
      return el.closest('[data-handle]') ? { kind: 'resize', id, edge: 'e' } : { kind: 'move', id };
    },
    targetKey(g: GestureState) {
      if (g.source.kind === 'resize') return `w${Math.round(this.activeRect!(g).w / 10)}`;
      return String(Math.min(2, Math.max(0, Math.floor(g.pointer.x / 110))));
    },
    preview(g: GestureState, key: string): Target {
      spies.preview(key);
      if (g.source.kind === 'resize') return { key, rects: new Map([...g.base, [g.source.id, this.activeRect!(g)]]) };
      const id = (g.source as { id: string }).id;
      const next = order.filter((x) => x !== id);
      next.splice(+key, 0, id);
      return { key, rects: rectsFor(next), payload: next };
    },
    activeRect: (g) => ({ x: 0, y: 0, w: Math.min(300, Math.max(40, g.pointer.x)), h: 50 }),
    begin: spies.begin,
    commit(t, g) {
      spies.commit(t, g);
      if (Array.isArray(t.payload)) order = t.payload as ItemId[];
    },
    cancel: spies.cancel,
    step(id, s) {
      spies.step(id, s);
      const i = order.indexOf(id);
      const j = s.dir === 'right' ? i + 1 : s.dir === 'left' ? i - 1 : i;
      if (s.resize || j < 0 || j > 2) return { key: `r${id}`, rects: rectsFor(order) };
      const next = [...order];
      next.splice(i, 1);
      next.splice(j, 0, id);
      return { key: `k${j}`, rects: rectsFor(next), payload: next };
    },
    label: (id) => id,
  };
  const render = vi.fn();
  const handle = mountMotion(container, adapter, { env, render, translate: (k, p) => `${k}:${p?.name}`, ...opts });
  const els = new Map<ItemId, HTMLElement>();
  for (const id of order) {
    const el = document.createElement('div');
    el.dataset.id = id;
    el.tabIndex = 0;
    el.innerHTML = '<i data-handle="e"></i>';
    container.appendChild(el);
    els.set(id, el);
    handle.register(id, el);
  }
  handle.sync(true);
  const frames = (n: number, ms = 16): void => {
    for (let i = 0; i < n; i++) {
      clock += ms;
      const run = queue.splice(0);
      run.forEach((cb) => cb(clock));
    }
  };
  const rest = (): void => {
    for (let i = 0; i < 600 && queue.length; i++) frames(1);
  };
  frames(2);
  return { handle, container, els, frames, rest, spies, render, adapter, queue, getOrder: () => order, move: (x: number, y = 25) => window.dispatchEvent(pev('pointermove', x, y)) };
}

export function mountKeyboard(adapter: Adapter, ids: ItemId[]) {
  let clock = 0;
  const queue: ((t: number) => void)[] = [];
  const env: Env = { raf: (cb) => queue.push(cb), caf: () => {}, now: () => clock, win: window, doc: document };
  const container = document.createElement('div');
  document.body.appendChild(container);
  const handle = mountMotion(container, adapter, { env, translate: (k) => k, autoscroll: false });
  const els = new Map<ItemId, HTMLElement>();
  for (const id of ids) {
    const el = document.createElement('div');
    el.tabIndex = 0;
    container.appendChild(el);
    els.set(id, el);
    handle.register(id, el);
  }
  handle.sync(true);
  const frames = (n: number): void => {
    for (let i = 0; i < n; i++) {
      clock += 16;
      queue.splice(0).forEach((cb) => cb(clock));
    }
  };
  frames(2);
  const key = (id: ItemId, name: string, init: KeyboardEventInit = {}): void => {
    const el = els.get(id)!;
    el.focus();
    el.dispatchEvent(new KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true, ...init }));
  };
  return { handle, container, els, key, frames };
}
