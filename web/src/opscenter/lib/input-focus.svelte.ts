
let owner = $state<string | null>(null);

let selectedTerminal = $state<string | null>(null);

const TERMINAL_PREFIX = 'terminal:';

export const GLOBAL_NAME = 'TerminalInputFocus';

export const inputFocus = {
  get owner(): string | null {
    return owner;
  },

  claim(id: string): void {
    if (!id) return;
    owner = id;
    if (id.startsWith(TERMINAL_PREFIX)) selectedTerminal = id;
  },

  get selected(): string | null {
    return selectedTerminal;
  },

  select(id: string): void {
    if (id && id.startsWith(TERMINAL_PREFIX)) selectedTerminal = id;
  },

  forget(id: string): void {
    if (owner === id) owner = null;
    if (selectedTerminal === id) selectedTerminal = null;
  },

  release(id: string): void {
    if (owner === id) owner = null;
  },

  permits(id: string): boolean {
    return owner === null || owner === id;
  },
} as const;

export function publishInputFocus(target: Record<string, unknown> = globalThis): void {
  target[GLOBAL_NAME] = {
    current: (): string | null => inputFocus.owner,
    permits: (id: string): boolean => inputFocus.permits(id),
  };
}

publishInputFocus();
