import { createAnnouncer } from './announcer';
import { createAutoscroll } from './autoscroll';
import { createFrameLoop } from './frame-loop';
import { createGestureController } from './gesture';
import { createKeyboard } from './keyboard';
import { applyRects, createItem, createRegistry, paintItem, sizeMoving, stepItem } from './paint';
import { createRectCache } from './rect-cache';
import { createSession } from './session';
import { makeSpring, snapTo, stepSpring } from './spring';
import type { Adapter, Env, ExternalOptions, ItemId, MotionEvent, MotionHandle, MotionOptions, Point, Rect, Source } from './types';

export * from './types';
export * from './drop-hosts';

const RENDER_MS = 70;

function browserEnv(): Env {
  return {
    raf: (cb) => window.requestAnimationFrame(cb),
    caf: (id) => window.cancelAnimationFrame(id),
    now: () => performance.now(),
    win: window,
    doc: document,
  };
}

export function mountMotion(container: HTMLElement, adapter: Adapter, options: MotionOptions = {}): MotionHandle {
  const env = options.env ?? browserEnv();
  const reduced = options.reduced ?? ((): boolean => env.win.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false);
  let enabled = options.enabled !== false;
  const listeners = new Map<MotionEvent, Set<(d: { id: string; cancelled?: boolean }) => void>>();
  const flip = options.sizePaint === 'flip';
  const registry = createRegistry(flip);
  const cache = createRectCache(container, env.win);
  const announcer = createAnnouncer(container, options.translate);
  const landingEl = env.doc.createElement('div');
  landingEl.className = 'motion-landing';
  landingEl.setAttribute('aria-hidden', 'true');
  container.appendChild(landingEl);
  const landing = createItem('', landingEl);
  landing.keepOpacity = true;
  snapTo(landing.o, 0);
  const extent = makeSpring(0, 'size');
  let extentSet = false;
  let extentCss = '';
  let pendingExternal: { rect: Rect; grab: Point } | null = null;
  let pendingLeave = false;

  function releaseExtent(): void {
    if (!extentSet) return;
    extentSet = false;
    extentCss = '';
    container.style.height = '';
  }

  const loop = createFrameLoop(env, (dt, t) => tick(dt, t));
  const session = createSession({
    env, container, adapter, registry, landing, cache,
    autoscroll: createAutoscroll(env.win, options.scroller ?? null, () => options.autoscroll !== false),
    announcer, reduced, wake: () => loop.wake(), flip, lift: options.lift,
    emit: (ev, d) => listeners.get(ev)?.forEach((fn) => fn(d)),
    setExtent(h) {
      if (h === null) return releaseExtent();
      extent.t = h;
      if (!extentSet) snapTo(extent, h);
      extentSet = true;
    },
  });

  const popoverOpen = (): boolean => {
    try {
      return env.doc.querySelector('[popover]:popover-open') !== null;
    } catch {
      return false;
    }
  };

  const gesture = createGestureController(env, container, () => enabled, {
    hit: (el, ev) => {
      const src = adapter.hit(el, ev);
      if (!src || src.kind === 'external') return null;
      if (src.kind === 'move' && (el.closest('[popover], [role=dialog]') || popoverOpen())) return null;
      return src;
    },
    begin: (source: Source, pt) => session.begin(source, pt, source.kind === 'external' ? pendingExternal ?? undefined : undefined, pendingLeave),
    move: (pt) => session.move(pt),
    end: (cancelled) => session.end(cancelled),
  });

  const keyboard = createKeyboard({
    container, registry, adapter, announcer,
    enabled: () => enabled,
    pointerActive: () => session.active(),
    apply: (target) => {
      session.applyTarget(target, null);
    },
    restore: (rects) => {
      applyRects(registry, rects, false, null);
      loop.wake();
    },
  });

  const renderCheck = (it: ReturnType<typeof createItem>, moving: boolean, t: number): boolean => {
    if (it.fresh || !options.render) return false;
    if (flip) return flipRenderCheck(it, t);
    const changed = it.rw < 0 || Math.abs(it.w.v - it.rw) >= 1 || Math.abs(it.h.v - it.rh) >= 1;
    if (changed) {
      it.dirty = true;
      if (it.rw < 0 || !moving || t - it.lastR >= RENDER_MS) {
        const reason = !it.mounted ? 'mount' : moving ? 'resize' : 'settle';
        it.rw = it.w.v;
        it.rh = it.h.v;
        it.lastR = t;
        it.dirty = false;
        it.mounted = true;
        loop.noteRender();
        try {
          options.render(it.id, { w: Math.round(it.w.v), h: Math.round(it.h.v) }, reason);
        } catch (err) {
          console.error('motion-grid render', it.id, err);
        }
      } else return true;
    }
    return it.dirty;
  };

  const flipRenderCheck = (it: ReturnType<typeof createItem>, t: number): boolean => {
    if (sizeMoving(it)) return false;
    if (it.rw >= 0 && Math.abs(it.w.v - it.rw) < 1 && Math.abs(it.h.v - it.rh) < 1) return false;
    const reason = !it.mounted ? 'mount' : session.active() ? 'resize' : 'settle';
    it.rw = it.w.v;
    it.rh = it.h.v;
    it.lastR = t;
    it.dirty = false;
    it.mounted = true;
    loop.noteRender();
    try {
      options.render?.(it.id, { w: Math.round(it.w.v), h: Math.round(it.h.v) }, reason);
    } catch (err) {
      console.error('motion-grid render', it.id, err);
    }
    return false;
  };

  function tick(dt: number, t: number): boolean {
    let moving = false;
    const snap = reduced();
    if (session.active()) {
      session.tick(dt);
      moving = true;
    }
    if (stepSpring(extent, dt, snap)) moving = true;
    if (extentSet) {
      const h = `${extent.v.toFixed(1)}px`;
      if (h !== extentCss) {
        container.style.height = h;
        extentCss = h;
      }
    }
    if (stepItem(landing, dt, snap)) moving = true;
    paintItem(landing);
    for (const it of registry.all()) {
      const m = stepItem(it, dt, snap);
      paintItem(it);
      if (m) moving = true;
      if (renderCheck(it, m || session.active(), t)) moving = true;
    }
    session.settleCheck(moving);
    return moving;
  }

  const abort = (): void => {
    if (gesture.active()) gesture.cancel();
  };

  container.classList.toggle('motion-enabled', enabled);

  return {
    register(id: ItemId, el: HTMLElement) {
      el.classList.add('motion-item');
      registry.register(id, el);
    },
    unregister(id) {
      if (gesture.active() && registry.get(id)?.el.classList.contains('motion-lifted')) abort();
      keyboard.dropItem(id);
      registry.unregister(id);
    },
    sync(instant = false) {
      applyRects(registry, adapter.rects(), instant, null);
      const h = adapter.extent?.(adapter.rects());
      if (h === null) releaseExtent();
      else if (h !== undefined) {
        extent.t = h;
        if (instant || !extentSet) snapTo(extent, h);
        extentSet = true;
      }
      loop.wake();
    },
    setEnabled(on) {
      enabled = on;
      container.classList.toggle('motion-enabled', on);
      if (!on) abort();
    },
    isBusy: () => session.busy(),
    beginExternal(source, ev, opts?: ExternalOptions) {
      const it = registry.get(source.id);
      if (!enabled || !it) return false;
      const asMove = opts?.as === 'move';
      pendingExternal = asMove ? null : { rect: source.rect, grab: source.grab };
      pendingLeave = opts?.leaveOnDrop === true;
      const ok = gesture.beginExternal({ kind: asMove ? 'move' : 'external', id: source.id }, ev, it.el);
      pendingExternal = null;
      pendingLeave = false;
      return ok;
    },
    on(event, fn) {
      const set = listeners.get(event) ?? new Set();
      set.add(fn);
      listeners.set(event, set);
      return () => set.delete(fn);
    },
    stats: () => loop.stats(),
    destroy() {
      abort();
      gesture.destroy();
      keyboard.destroy();
      cache.dispose();
      loop.stop();
      announcer.dispose();
      landingEl.remove();
      container.classList.remove('motion-enabled', 'motion-busy');
      session.dispose();
      listeners.clear();
    },
  };
}
