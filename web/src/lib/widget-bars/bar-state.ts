import type { RailEdge } from '../session-rail/rail-model';
import type { BarMode, BarsTogether } from './bar-settings.svelte';

export type BarVisual = 'absent' | 'edit' | 'folded' | 'held' | 'pinned' | 'peek' | 'handle';

export const RETRACT_MS = 300;

export interface PeekFlags {
  hover: boolean;
  focusIn: boolean;
  touchPeek: boolean;
  retracting: boolean;
}

export interface BarStateInput extends PeekFlags {
  show: boolean;
  drawn: boolean;
  editing: boolean;
  folded: boolean;
  panelShown: boolean;
  mode: BarMode;
}

export function barState(i: BarStateInput): BarVisual {
  if (!i.show || (!i.drawn && !i.editing)) return 'absent';
  if (i.editing) return 'edit';
  const out = i.hover || i.focusIn || i.touchPeek || i.retracting;
  if (i.folded) return out ? 'peek' : 'folded';
  if (i.panelShown) return 'held';
  if (i.mode === 'pinned') return 'pinned';
  return out ? 'peek' : 'handle';
}

export const inFlow = (state: BarVisual): boolean => state === 'held' || state === 'pinned' || state === 'edit';

export const barOut = (state: BarVisual): boolean => inFlow(state) || state === 'peek';

export const showsHandle = (state: BarVisual): boolean => state === 'handle' || state === 'peek' || state === 'folded';

export const peekOut = (f: Readonly<PeekFlags>): boolean => f.hover || f.focusIn || f.touchPeek || f.retracting;

export const showsPin = (state: BarVisual): boolean => state === 'held' || state === 'pinned' || state === 'peek';

export function foldedEdge(together: BarsTogether, lead: RailEdge | null, edge: RailEdge): boolean {
  return together === 'one' && lead !== null && lead !== edge;
}

export interface Clock {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export const realClock: Clock = {
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export class PeekController {
  flags: PeekFlags = { hover: false, focusIn: false, touchPeek: false, retracting: false };
  #timer: unknown = null;

  constructor(
    private readonly clock: Clock,
    private readonly onChange: (flags: Readonly<PeekFlags>) => void,
    private readonly delay: number = RETRACT_MS,
    private readonly stillInside?: () => boolean,
  ) {}

  open(): void {
    this.#cancel();
    this.#set({ hover: true, retracting: false });
  }

  enter(): void {
    this.#cancel();
    this.#set({ hover: true, retracting: false });
  }

  leave(): void {
    this.#set({ hover: false });
    this.#arm();
  }

  focusIn(): void {
    this.#cancel();
    this.#set({ focusIn: true, retracting: false });
  }

  focusOut(): void {
    this.#set({ focusIn: false });
    this.#arm();
  }

  tap(): void {
    if (this.flags.touchPeek) this.dismissTouch();
    else {
      this.#cancel();
      this.#set({ touchPeek: true, retracting: false });
    }
  }

  dismissTouch(): void {
    this.#cancel();
    this.#set({ touchPeek: false, retracting: false });
  }

  escape(): void {
    this.#cancel();
    this.#set({ hover: false, focusIn: false, touchPeek: false, retracting: false });
  }

  panelClosed(): void {
    this.#arm();
  }

  destroy(): void {
    this.#cancel();
  }

  #arm(): void {
    const f = this.flags;
    if (f.hover || f.focusIn || f.touchPeek) return;
    this.#cancel();
    this.#set({ retracting: true });
    this.#timer = this.clock.setTimeout(() => {
      this.#timer = null;
      if (this.stillInside?.()) this.#set({ hover: true, retracting: false });
      else this.#set({ retracting: false });
    }, this.delay);
  }

  #cancel(): void {
    if (this.#timer === null) return;
    this.clock.clearTimeout(this.#timer);
    this.#timer = null;
  }

  #set(patch: Partial<PeekFlags>): void {
    this.flags = { ...this.flags, ...patch };
    this.onChange(this.flags);
  }
}
