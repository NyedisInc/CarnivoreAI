
let owner = $state<string | null>(null);

let selectedTerminal = $state<string | null>(null);

let ownerNow: string | null = null;
let selectedNow: string | null = null;

const mounts = new Map<string, number>();

const TERMINAL_PREFIX = 'terminal:';

export const GLOBAL_NAME = 'TerminalInputFocus';

export const inputFocus = {
  get owner(): string | null {
    return owner;
  },

  claim(id: string): void {
    if (!id) return;
    ownerNow = owner = id;
    if (id.startsWith(TERMINAL_PREFIX)) selectedNow = selectedTerminal = id;
  },

  get selected(): string | null {
    return selectedTerminal;
  },

  select(id: string): void {
    if (id && id.startsWith(TERMINAL_PREFIX)) selectedNow = selectedTerminal = id;
  },

  forget(id: string): void {
    if (ownerNow === id) ownerNow = owner = null;
    if (selectedNow === id) selectedNow = selectedTerminal = null;
  },

  mount(id: string): () => void {
    mounts.set(id, (mounts.get(id) ?? 0) + 1);
    let live = true;
    return () => {
      if (!live) return;
      live = false;
      const left = (mounts.get(id) ?? 1) - 1;
      if (left > 0) { mounts.set(id, left); return; }
      mounts.delete(id);
      inputFocus.forget(id);
    };
  },

  release(id: string): void {
    if (ownerNow === id) ownerNow = owner = null;
  },

  permits(id: string): boolean {
    return ownerNow === null || ownerNow === id;
  },
} as const;

export function publishInputFocus(target: Record<string, unknown> = globalThis): void {
  target[GLOBAL_NAME] = {
    current: (): string | null => ownerNow,
    permits: (id: string): boolean => inputFocus.permits(id),
  };
}

publishInputFocus();
