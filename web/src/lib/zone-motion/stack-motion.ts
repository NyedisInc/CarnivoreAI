import { mountMotion, type Adapter, type MotionHandle, type MotionOptions } from '../motion-grid';
import { createStackAdapter, STACK_ID_ATTR, type StackConfig, type StackItem } from './stack-adapter';

export type StackMount = Omit<StackConfig, 'items' | 'width'> & {
  order(): readonly string[];
};

export interface Stack {
  handle: MotionHandle;
  cell(node: HTMLElement, id: string): { update(id: string): void; destroy(): void };
  sync(instant?: boolean): void;
  destroy(): void;
}

export function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let n = el.parentElement; n; n = n.parentElement) {
    const o = getComputedStyle(n).overflowY;
    if (o === 'auto' || o === 'scroll') return n;
  }
  return null;
}

export function mountStack(container: HTMLElement, cfg: StackMount, options: MotionOptions = {}): Stack {
  return mountMeasured(container, (items) => createStackAdapter({ ...cfg, items, width: () => container.clientWidth }), { ...options, order: cfg.order });
}

export function mountMeasured(container: HTMLElement, build: (items: () => StackItem[], size: (id: string) => { w: number; h: number }) => Adapter, options: MotionOptions & { focusable?: boolean; order?: () => readonly string[] } = {}): Stack {
  const { focusable = true, order, ...core } = options;
  const sizes = new Map<string, { w: number; h: number }>();
  const observed = new Map<string, ResizeObserver>();
  let deferred = false;
  let dead = false;

  const size = (id: string): { w: number; h: number } => sizes.get(id) ?? { w: 0, h: 0 };
  const items = (): StackItem[] => (order ?? (() => [...sizes.keys()]))().map((id) => ({ id, ...size(id) }));
  const handle = mountMotion(container, build(items, size), { scroller: scrollParent(container), ...core });

  const sync = (instant = false): void => {
    if (dead) return;
    if (handle.isBusy()) {
      deferred = true;
      return;
    }
    handle.sync(instant);
  };
  const offSettle = handle.on('settle', () => {
    if (deferred) {
      deferred = false;
      handle.sync();
    }
  });
  const widthWatch = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => sync());
  widthWatch?.observe(container);

  const measure = (id: string, inner: HTMLElement): boolean => {
    const next = { w: inner.offsetWidth, h: inner.offsetHeight };
    const was = sizes.get(id);
    if (was && was.w === next.w && was.h === next.h) return false;
    sizes.set(id, next);
    return true;
  };

  return {
    handle,
    cell(node, id) {
      let current = id;
      node.setAttribute(STACK_ID_ATTR, id);
      if (focusable) node.tabIndex = 0;
      handle.register(id, node);
      const inner = node.firstElementChild as HTMLElement | null;
      if (inner) measure(id, inner);
      sync(true);
      const observe = (): void => {
        if (!inner || typeof ResizeObserver === 'undefined') return;
        const ro = new ResizeObserver(() => {
          if (measure(current, inner)) sync();
        });
        ro.observe(inner);
        observed.set(current, ro);
      };
      observe();
      return {
        update(next) {
          if (next === current) return;
          handle.unregister(current);
          observed.get(current)?.disconnect();
          observed.delete(current);
          sizes.delete(current);
          current = next;
          node.setAttribute(STACK_ID_ATTR, next);
          handle.register(next, node);
          if (inner) measure(next, inner);
          observe();
          sync(true);
        },
        destroy() {
          observed.get(current)?.disconnect();
          observed.delete(current);
          sizes.delete(current);
          if (!dead) handle.unregister(current);
          sync();
        },
      };
    },
    sync,
    destroy() {
      dead = true;
      offSettle();
      widthWatch?.disconnect();
      for (const ro of observed.values()) ro.disconnect();
      observed.clear();
      handle.destroy();
    },
  };
}
