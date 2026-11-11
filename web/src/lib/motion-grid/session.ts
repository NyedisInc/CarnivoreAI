import type { Announcer } from './announcer';
import { acquireCarryHold, acquireDragHold } from './drag-hold';
import type { Autoscroll } from './autoscroll';
import { applyRects, setRect, type ItemRegistry, type ItemState } from './paint';
import type { RectCache } from './rect-cache';
import { setKind, snapTo, type Spring } from './spring';
import type { Adapter, Env, GestureState, ItemId, Point, Rect, Source, Target } from './types';

const OUTSIDE = 48;
const DROP_MS = 600;
const TILT = 3;

export interface SessionDeps {
  env: Env;
  container: HTMLElement;
  adapter: Adapter;
  registry: ItemRegistry;
  landing: ItemState;
  cache: RectCache;
  autoscroll: Autoscroll;
  announcer: Announcer;
  reduced(): boolean;
  wake(): void;
  emit(event: 'dragstart' | 'dragend' | 'resizestart' | 'resizeend' | 'settle', detail: { id: string; cancelled?: boolean }): void;
  setExtent(h: number | null): void;
  flip: boolean;
  lift?: { tilt: boolean; maxW: number; maxH: number };
}

export interface ExternalEntry {
  rect: Rect;
  grab: Point;
}

export interface Session {
  active(): boolean;
  busy(): boolean;
  begin(source: Source, client: Point, external?: ExternalEntry, leaveOnDrop?: boolean): boolean;
  move(client: Point): void;
  end(cancelled: boolean): void;
  tick(dt: number): void;
  dispose(): void;
  settleCheck(moving: boolean): void;
  applyTarget(target: Target, activeId: ItemId | null): void;
}

interface Run {
  source: Source;
  id: ItemId | null;
  base: Map<ItemId, Rect>;
  startRect: Rect | null;
  grab: Point;
  start: Point;
  client: Point;
  pinned: Point | null;
  lastPx: number;
  vx: number;
  key: string | null;
  target: Target | null;
  outside: boolean;
  item: ItemState | null;
  leave: boolean;
}

export function createSession(deps: SessionDeps): Session {
  const { env, container, adapter, registry, landing, cache } = deps;
  let run: Run | null = null;
  let settling: { id: ItemId | null; item: ItemState | null } | null = null;
  let revert: ReturnType<typeof setTimeout> | null = null;
  let release: (() => void) | null = null;
  let releaseCarry: (() => void) | null = null;
  let markLabel: string | null = null;
  let markKind: string | null = null;

  const idOf = (s: Source): ItemId | null => (s.kind === 'divider' ? null : s.id);
  const nameOf = (id: ItemId | null): string => (id ? adapter.label?.(id) ?? id : '');

  const state = (r: Run): GestureState => {
    const pointer = pointerOf(r);
    return {
      source: r.source,
      pointer,
      start: r.start,
      delta: { x: pointer.x - r.start.x, y: pointer.y - r.start.y },
      grab: r.grab,
      startRect: r.startRect,
      base: r.base,
      bounds: { w: cache.get().width, h: cache.get().height },
      outside: r.outside,
    };
  };

  const originOf = (): Point => {
    const c = cache.get();
    return { x: c.left - container.scrollLeft, y: c.top - container.scrollTop };
  };

  const pointerOf = (r: Run): Point => {
    const o = r.pinned ?? originOf();
    return { x: r.client.x - o.x, y: r.client.y - o.y };
  };

  const hold = (...ss: Spring[]): void => {
    for (const s of ss) snapTo(s, s.v);
  };

  const dropHold = (): void => {
    release?.();
    release = null;
    dropCarry();
  };

  const dropCarry = (): void => {
    releaseCarry?.();
    releaseCarry = null;
  };

  const setMark = (m: Target['mark']): void => {
    const label = m?.label ?? null;
    const kind = m?.kind ?? null;
    if (label !== markLabel) {
      markLabel = label;
      if (label === null) landing.el.removeAttribute('data-label');
      else landing.el.setAttribute('data-label', label);
    }
    if (kind !== markKind) {
      markKind = kind;
      if (kind === null) landing.el.removeAttribute('data-kind');
      else landing.el.setAttribute('data-kind', kind);
    }
  };

  const finishSettle = (): void => {
    const s = settling;
    if (!s) return;
    settling = null;
    if (s.item) {
      s.item.settle = false;
      s.item.el.classList.remove('motion-lifted', 'motion-resizing');
      s.item.el.style.zIndex = '';
      if (deps.flip) s.item.gx = s.item.gy = 0;
      else s.item.el.style.transformOrigin = '';
    }
    landing.o.t = 0;
    snapTo(landing.o, 0);
    dropHold();
    container.classList.remove('motion-busy');
    deps.emit('settle', { id: s.id ?? '' });
  };

  const api: Session = {
    active: () => run !== null,
    busy: () => run !== null || settling !== null,

    begin(source, client, external, leaveOnDrop) {
      if (run) return false;
      finishSettle();
      const id = idOf(source);
      const item = id ? registry.get(id) ?? null : null;
      if (id && !item) return false;
      cache.invalidate();
      deps.autoscroll.reset();
      const o = originOf();
      const base = new Map(adapter.rects());
      let startRect: Rect | null = id ? external?.rect ?? base.get(id) ?? null : null;
      if (item && !startRect) startRect = { x: item.x.v, y: item.y.v, w: item.w.v, h: item.h.v };
      let grab: Point = { x: 0, y: 0 };
      if (item && startRect && (source.kind === 'move' || source.kind === 'external')) {
        grab = external
          ? external.grab
          : {
              x: Math.min(Math.max(client.x - o.x - item.x.v, 0), item.w.v),
              y: Math.min(Math.max(client.y - o.y - item.y.v, 0), item.h.v),
            };
      }
      run = {
        source, id, base, startRect, grab,
        start: { x: client.x - o.x, y: client.y - o.y }, client, pinned: source.kind === 'resize' ? o : null,
        lastPx: client.x - o.x, vx: 0, key: null, target: null, outside: false, item, leave: leaveOnDrop === true,
      };
      setMark(undefined);
      adapter.begin?.(source, source.kind === 'external' ? 'external' : 'pointer');
      release = acquireDragHold(env.doc);
      releaseCarry = acquireCarryHold(env.doc);
      container.classList.add('motion-busy');
      const reduced = deps.reduced();
      if (item && startRect) {
        const lift = source.kind === 'move' || source.kind === 'external';
        item.settle = false;
        item.leaving = false;
        item.el.classList.add(lift ? 'motion-lifted' : 'motion-resizing');
        item.el.style.zIndex = source.kind === 'external' ? '120' : lift ? '30' : '20';
        if (lift) {
          if (deps.flip) {
            item.gx = grab.x;
            item.gy = grab.y;
          } else item.el.style.transformOrigin = `${grab.x.toFixed(0)}px ${grab.y.toFixed(0)}px`;
          if (external) {
            setRect(item, { x: client.x - o.x - grab.x, y: client.y - o.y - grab.y, w: startRect.w, h: startRect.h }, true);
            item.fresh = false;
            item.rw = -1;
            item.s.v = reduced ? 1 : 0.92;
            item.o.v = 0.45;
          }
          hold(item.x, item.y);
          item.s.t = reduced ? 1 : deps.lift ? Math.min(1, deps.lift.maxW / Math.max(startRect.w, 1), deps.lift.maxH / Math.max(startRect.h, 1)) : 1.03;
          item.o.t = 0.86;
          item.r.t = reduced || deps.lift?.tilt === false ? 0 : TILT;
        }
        setRect(landing, startRect, true);
        landing.fresh = false;
        landing.o.t = lift && external ? 0 : 1;
        snapTo(landing.o, landing.o.t);
      }
      if (source.kind === 'move' || source.kind === 'external') deps.announcer.say('motion.picked', nameOf(id));
      deps.emit(source.kind === 'move' || source.kind === 'external' ? 'dragstart' : 'resizestart', { id: id ?? (source as { id: string }).id });
      deps.wake();
      return true;
    },

    move(client) {
      if (!run) return;
      run.client = client;
      deps.wake();
    },

    tick(dt) {
      const r = run;
      if (!r) return;
      if (deps.autoscroll.step(r.client.y, dt)) cache.invalidate();
      const c = cache.get();
      const p = pointerOf(r);
      const vx = r.client.x - c.left;
      const vy = r.client.y - c.top;
      r.outside = vx < -OUTSIDE || vx > c.width + OUTSIDE || vy < -OUTSIDE || vy > c.height + OUTSIDE;
      const it = r.item;
      if (it && (r.source.kind === 'move' || r.source.kind === 'external')) {
        it.x.v = it.x.t = p.x - r.grab.x;
        it.y.v = it.y.t = p.y - r.grab.y;
        it.x.vel = it.y.vel = 0;
        const vel = (p.x - r.lastPx) / Math.max(dt, 0.001);
        r.lastPx = p.x;
        r.vx += (vel - r.vx) * Math.min(1, dt * 9);
        it.r.t = deps.reduced() || deps.lift?.tilt === false ? 0 : TILT + Math.min(Math.max(r.vx / 380, -4), 4);
      } else if (it && r.source.kind === 'resize' && adapter.activeRect) {
        const a = adapter.activeRect(state(r));
        it.x.v = it.x.t = a.x;
        it.y.v = it.y.t = a.y;
        it.w.v = it.w.t = a.w;
        it.h.v = it.h.t = a.h;
        it.x.vel = it.y.vel = it.w.vel = it.h.vel = 0;
      }
      const g = state(r);
      const key = adapter.targetKey(g);
      if (key !== r.key) {
        r.key = key;
        r.target = adapter.preview(g, key);
        api.applyTarget(r.target, r.id);
      }
    },

    applyTarget(target, activeId) {
      applyRects(registry, target.rects, target.instant === true, activeId);
      const valid = target.valid !== false;
      const land = target.landing === undefined ? (activeId ? target.rects.get(activeId) : undefined) : target.landing;
      if (activeId) {
        setMark(target.mark);
        if (land && valid) {
          setRect(landing, land, target.mark !== undefined || landing.o.v < 0.05);
          landing.o.t = 1;
        } else landing.o.t = 0;
        const it = registry.get(activeId);
        if (it && run && (run.source.kind === 'move' || run.source.kind === 'external')) it.o.t = valid ? 0.86 : 0.6;
      }
      const h = adapter.extent?.(target.rects);
      if (h !== undefined) deps.setExtent(h);
      deps.wake();
    },

    end(cancelled) {
      const r = run;
      if (!r) return;
      run = null;
      dropCarry();
      cache.invalidate();
      const it = r.item;
      const tg = r.target;
      const external = r.source.kind === 'external';
      let cancel = cancelled || tg === null || tg.valid === false;
      if (r.outside && external) cancel = true;
      const rects = cancel || !tg ? r.base : tg.rects;
      const instant = !cancel && tg?.instant === true;
      applyRects(registry, rects, instant, r.id);
      if (it) {
        it.settle = true;
        if ((external && cancel) || (r.leave && !cancel)) {
          it.leaving = true;
          it.r.t = 0;
          it.s.t = 0.9;
          it.o.t = 0;
        } else {
          const lift = r.source.kind === 'move' || external;
          const f = (!cancel && tg?.rects.get(it.id)) || r.base.get(it.id) || r.startRect;
          if (f) {
            for (const [s, v] of [[it.x, f.x], [it.y, f.y], [it.w, f.w], [it.h, f.h]] as [Spring, number][]) {
              s.t = v;
              setKind(s, 'drop');
            }
            if (revert) clearTimeout(revert);
            revert = setTimeout(() => {
              revert = null;
              for (const s of [it.x, it.y, it.w, it.h]) setKind(s, s === it.x || s === it.y ? 'pos' : 'size');
            }, DROP_MS);
          }
          if (lift) {
            it.r.t = 0;
            it.s.t = 1;
            it.o.t = 1;
          }
          if (f) setRect(landing, f, false);
        }
      }
      landing.o.t = 0;
      const id = r.id ?? (r.source as { id: string }).id;
      settling = { id, item: it };
      if (cancel) adapter.cancel();
      else if (tg) adapter.commit(tg, state({ ...r, outside: false }));
      deps.announcer.say(cancel ? 'motion.cancelled' : r.source.kind === 'move' || external ? 'motion.placed' : 'motion.resized', nameOf(r.id));
      deps.emit(r.source.kind === 'move' || external ? 'dragend' : 'resizeend', { id, cancelled: cancel });
      deps.wake();
    },

    dispose: dropHold,

    settleCheck(moving) {
      if (settling && !run && !moving) finishSettle();
    },
  };
  return api;
}
