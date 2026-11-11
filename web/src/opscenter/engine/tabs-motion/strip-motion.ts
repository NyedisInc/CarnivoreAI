import { mountMotion, type MotionHandle, type Rect } from '../../../lib/motion-grid';
import { carryTab, commitTabDrop } from '../tab-drag';
import { tabDrag } from '../tab-drag-state.svelte';
import { viewport } from '../viewport.svelte';
import { createStripAdapter } from './strip-adapter';
import { tabName } from './tab-name';

export const TAB_THRESHOLD = 6;

const LEAVE_PX = 10;

export const TOUCH_HOLD_MS = 320;
export const TOUCH_SLOP = 10;

const GAP = 1;

const PAINTED = ['transform', 'width', 'height', 'opacity', 'z-index', 'transform-origin', 'will-change'] as const;

export interface StripMotion {
  press(handle: HTMLElement, event: PointerEvent, tab: string): boolean;
  nudge(tab: string, dir: 'left' | 'right'): boolean;
  destroy(): void;
}

const strips = new WeakMap<Element, StripMotion>();

export function stripOf(el: Element): StripMotion | null {
  const track = el.closest('[data-tab-track]');
  return track ? (strips.get(track) ?? null) : null;
}

const tabOf = (wrap: Element): string => wrap.querySelector<HTMLElement>('[data-tab]')?.dataset['tab'] ?? '';

export function mountStrip(track: HTMLElement, slot: string, opts: { touch?: boolean } = {}): StripMotion {
  let measured = new Map<string, Rect>();
  let live = false;
  let handle: MotionHandle | null = null;
  let offSettle: (() => void) | null = null;
  let listening: (() => void) | null = null;
  let destroyed = false;

  const wraps = (): HTMLElement[] => [...track.querySelectorAll<HTMLElement>(':scope > .oc-tabwrap')];
  const order = (): string[] => wraps().map(tabOf);
  const adapter = createStripAdapter(
    {
      order,
      measured: () => measured,
      onDrop: (id, index) => {
        commitTabDrop(id, { kind: 'strip', slot, index });
      },
      name: (id) => tabName(id, track),
    },
    GAP,
  );

  const mount = (): void => {
    handle = mountMotion(track, adapter, { autoscroll: false });
    offSettle = handle.on('settle', teardown);
  };

  function teardown(): void {
    if (!live) return;
    live = false;
    for (const wrap of wraps()) {
      handle?.unregister(tabOf(wrap));
      wrap.classList.remove('motion-item', 'motion-lifted');
      for (const name of PAINTED) wrap.style.removeProperty(name);
    }
    track.classList.remove('oc-tabs-live');
    track.style.removeProperty('--oc-tabs-w');
    track.style.removeProperty('--oc-tabs-h');
  }

  const prepare = (): void => {
    const box = track.getBoundingClientRect();
    measured = new Map();
    for (const wrap of wraps()) {
      const r = wrap.getBoundingClientRect();
      measured.set(tabOf(wrap), { x: r.left - box.left, y: r.top - box.top, w: r.width, h: r.height });
    }
    const total = [...measured.values()].reduce((end, r) => Math.max(end, r.x + r.w), 0);
    track.style.setProperty('--oc-tabs-w', `${total}px`);
    track.style.setProperty('--oc-tabs-h', `${box.height}px`);
    track.classList.add('oc-tabs-live');
    live = true;
    for (const wrap of wraps()) handle?.register(tabOf(wrap), wrap);
    handle?.sync(true);
  };

  const remount = (): void => {
    if (destroyed) return;
    offSettle?.();
    handle?.destroy();
    teardown();
    mount();
  };

  const handOff = (tab: string, event: PointerEvent): void => {
    handle?.setEnabled(false);
    tabDrag.tab = tab;
    const carried = carryTab(tab, event);
    if (!carried) tabDrag.tab = null;
    if (carried) requestAnimationFrame(remount);
    else remount();
  };

  const lift = (event: PointerEvent, tab: string): void => {
    prepare();
    const rect = measured.get(tab);
    const box = track.getBoundingClientRect();
    if (!rect || !handle) return teardown();
    const grab = { x: event.clientX - box.left - rect.x, y: event.clientY - box.top - rect.y };
    if (!handle.beginExternal({ id: tab, rect, grab }, event)) return teardown();
    if (opts.touch) return;
    const bounds = (track.closest('.oc-frame-strip') ?? track).getBoundingClientRect();
    const onMove = (e: PointerEvent): void => {
      if (e.pointerId !== event.pointerId) return;
      const outside = e.clientX < bounds.left - LEAVE_PX || e.clientX > bounds.right + LEAVE_PX || e.clientY < bounds.top - LEAVE_PX || e.clientY > bounds.bottom + LEAVE_PX;
      if (!outside) return;
      stop();
      handOff(tab, e);
    };
    const stop = (): void => {
      window.removeEventListener('pointermove', onMove, true);
      window.removeEventListener('pointerup', stop, true);
      window.removeEventListener('pointercancel', stop, true);
      listening = null;
    };
    listening = stop;
    window.addEventListener('pointermove', onMove, true);
    window.addEventListener('pointerup', stop, true);
    window.addEventListener('pointercancel', stop, true);
  };

  mount();
  const strip: StripMotion = {
    press(button, event, tab) {
      if (live || (event.pointerType === 'mouse' && event.button !== 0) || button.closest('[data-tab-close]')) return false;
      if (!opts.touch && viewport.wide && order().length === 1) return false;
      const x0 = event.clientX;
      const y0 = event.clientY;
      const held = opts.touch && event.pointerType === 'touch';
      let last = event;
      const timer = held
        ? setTimeout(() => {
            drop();
            lift(last, tab);
          }, TOUCH_HOLD_MS)
        : null;
      const onMove = (e: PointerEvent): void => {
        if (e.pointerId !== event.pointerId) return;
        last = e;
        const far = Math.hypot(e.clientX - x0, e.clientY - y0);
        if (held) {
          if (far > TOUCH_SLOP) drop();
          return;
        }
        if (far < TAB_THRESHOLD) return;
        drop();
        lift(e, tab);
      };
      const drop = (): void => {
        if (timer !== null) clearTimeout(timer);
        window.removeEventListener('pointermove', onMove, true);
        window.removeEventListener('pointerup', drop, true);
        window.removeEventListener('pointercancel', drop, true);
      };
      window.addEventListener('pointermove', onMove, true);
      window.addEventListener('pointerup', drop, true);
      window.addEventListener('pointercancel', drop, true);
      return true;
    },
    nudge(tab, dir) {
      const target = adapter.step?.(tab, { dir, resize: false });
      if (!target) return false;
      adapter.commit(target, null);
      return true;
    },
    destroy() {
      destroyed = true;
      listening?.();
      offSettle?.();
      handle?.destroy();
      teardown();
      handle = null;
      strips.delete(track);
    },
  };
  strips.set(track, strip);
  return strip;
}
