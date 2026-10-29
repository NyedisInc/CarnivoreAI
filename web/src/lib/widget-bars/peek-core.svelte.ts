/* no longer holds something else */
import { tick } from 'svelte';
import { PeekController, peekOut, realClock, type Clock, type PeekFlags } from './bar-state';

export interface PeekCoreInput {
  nav: () => HTMLElement | null;
  firstKey: string;
  isPeeking: () => boolean;
  isFolded?: () => boolean;
  holds?: (node: Node) => boolean;
  inside?: (x: number, y: number) => boolean;
  clock?: Clock;
}

const inHandle = (node: EventTarget | null): boolean => node instanceof Element && node.closest('[data-bar-handle]') !== null;

export function createPeekCore(input: PeekCoreInput) {
  let flags = $state<PeekFlags>({ hover: false, focusIn: false, touchPeek: false, retracting: false });
  let last: { x: number; y: number } | null = null;
  let folded = false;
  const pointerInside = (): boolean => last !== null && input.inside?.(last.x, last.y) === true;
  const peek = new PeekController(input.clock ?? realClock, (next) => (flags = { ...next }), undefined, input.inside ? pointerInside : undefined);

  $effect(() => {
    if (!input.inside) return;
    const moved = (event: PointerEvent): void => {
      if (event.pointerType === 'touch') return;
      last = { x: event.clientX, y: event.clientY };
      const over = pointerInside();
      if (!over) folded = false;
      else if (!folded && !peek.flags.hover && !peek.flags.retracting && !peek.flags.focusIn && !peek.flags.touchPeek) peek.enter();
    };
    window.addEventListener('pointermove', moved, { capture: true, passive: true });
    return () => window.removeEventListener('pointermove', moved, true);
  });

  $effect(() => {
    if (!flags.touchPeek) return;
    const away = (event: PointerEvent): void => {
      const target = event.target as Node;
      if (event.pointerType === 'touch' && !input.nav()?.contains(target) && !input.holds?.(target)) peek.dismissTouch();
    };
    window.addEventListener('pointerdown', away, true);
    return () => window.removeEventListener('pointerdown', away, true);
  });

  $effect(() => () => peek.destroy());

  return {
    peek,
    get flags(): PeekFlags {
      return flags;
    },
    pointerInside,
    onpointerenter(event: PointerEvent): void {
      if (event.pointerType !== 'touch') peek.enter();
    },
    onpointerleave(event: PointerEvent): void {
      if (event.pointerType !== 'touch') peek.leave();
    },
    onfocusin(event: FocusEvent): void {
      if (!inHandle(event.target) && event.target instanceof Element && event.target.matches(':focus-visible')) peek.focusIn();
    },
    onfocusout(event: FocusEvent): void {
      const to = event.relatedTarget;
      if (to instanceof Node && input.nav()?.contains(to) && !inHandle(to)) return;
      if (flags.focusIn) peek.focusOut();
      // something else
      if (input.isFolded?.() && !flags.hover) peek.escape();
    },
    onkeydown(event: KeyboardEvent): void {
      if (event.key !== 'Escape' || !input.isPeeking()) return;
      event.preventDefault();
      folded = pointerInside();
      peek.escape();
      input.nav()?.querySelector<HTMLElement>('[data-bar-handle]')?.focus();
    },
    fold(): void {
      folded = pointerInside();
      peek.escape();
    },
    async onpress(kind: 'keyboard' | 'touch' | 'pointer'): Promise<void> {
      if (kind === 'pointer' && peekOut(flags)) return;
      if (peekOut(flags)) {
        folded = pointerInside();
        peek.escape();
      } else if (kind === 'touch') peek.tap();
      else if (kind === 'pointer') peek.open();
      else {
        peek.focusIn();
        await tick();
        input.nav()?.querySelector<HTMLElement>(input.firstKey)?.focus();
      }
    },
  };
}
