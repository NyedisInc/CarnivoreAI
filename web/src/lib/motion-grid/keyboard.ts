import type { Announcer } from './announcer';
import type { ItemRegistry } from './paint';
import type { Adapter, ItemId, Rect, Target } from './types';

const ARROWS: Record<string, 'left' | 'right' | 'up' | 'down'> = {
  ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down',
};

export interface KeyboardDeps {
  container: HTMLElement;
  registry: ItemRegistry;
  adapter: Adapter;
  announcer: Announcer;
  enabled(): boolean;
  pointerActive(): boolean;
  apply(target: Target): void;
  restore(rects: ReadonlyMap<ItemId, Rect>): void;
}

export interface Keyboard {
  active(): boolean;
  dropItem(id: ItemId): void;
  destroy(): void;
}

export function createKeyboard(deps: KeyboardDeps): Keyboard {
  const { container, registry, adapter, announcer } = deps;
  let session: { id: ItemId; snapshot: Map<ItemId, Rect>; last: Target | null } | null = null;

  const itemFor = (el: Element): ItemId | null => {
    const start = registry.idOf(el) ? el : el.closest('[data-motion-handle]');
    for (let n: Element | null = start; n; n = n.parentElement) {
      const id = registry.idOf(n);
      if (id) return id;
    }
    return null;
  };
  const nameOf = (id: ItemId): string => adapter.label?.(id) ?? id;

  const onKeyDown = (e: KeyboardEvent): void => {
    if (!deps.enabled() || deps.pointerActive() || !(e.target instanceof Element)) return;
    const id = itemFor(e.target);
    if (!id) return;
    const dir = ARROWS[e.key];
    if (dir) {
      if (!e.shiftKey && e.target.closest('[role="tab"]')) return;
      e.preventDefault();
      if (!adapter.step) return;
      if (!session) {
        session = { id, snapshot: new Map(adapter.rects()), last: null };
        adapter.begin?.(e.shiftKey ? { kind: 'resize', id, edge: 'se' } : { kind: 'move', id }, 'keyboard');
      }
      const target = adapter.step(id, { dir, resize: e.shiftKey }, session.last);
      if (!target) return;
      deps.apply(target);
      if (adapter.stepFromTarget) session.last = target;
      else adapter.commit(target, null);
      announcer.say(e.shiftKey ? 'motion.resized' : 'motion.moved', nameOf(id));
    } else if (e.key === 'Escape' && session) {
      e.preventDefault();
      adapter.cancel();
      deps.restore(session.snapshot);
      session = null;
      announcer.say('motion.cancelled', nameOf(id));
    } else if ((e.key === 'Enter' || e.key === ' ') && session) {
      e.preventDefault();
      endSession();
      announcer.say('motion.placed', nameOf(id));
    }
  };
  const endSession = (): void => {
    const last = session?.last;
    session = null;
    if (last) adapter.commit(last, null);
  };
  const onFocusOut = (e: FocusEvent): void => {
    if (!session || !(e.target instanceof Element) || itemFor(e.target) !== session.id) return;
    const to = e.relatedTarget instanceof Element ? itemFor(e.relatedTarget) : null;
    if (to !== session.id) endSession();
  };

  container.addEventListener('keydown', onKeyDown);
  container.addEventListener('focusout', onFocusOut);
  return {
    active: () => session !== null,
    dropItem(id) {
      if (session?.id !== id) return;
      deps.restore(session.snapshot);
      session = null;
      adapter.cancel();
    },
    destroy() {
      container.removeEventListener('keydown', onKeyDown);
      container.removeEventListener('focusout', onFocusOut);
    },
  };
}
