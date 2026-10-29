
export class MemoryStorage implements Storage {
  #items = new Map<string, string>();

  constructor(seed: Storage | null) {
    if (!seed) return;
    for (let index = 0; index < seed.length; index += 1) {
      const key = seed.key(index);
      if (key !== null) this.#items.set(key, seed.getItem(key) ?? '');
    }
  }

  get length(): number {
    return this.#items.size;
  }

  clear(): void {
    this.#items.clear();
  }

  getItem(key: string): string | null {
    return this.#items.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.#items.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.#items.delete(key);
  }

  setItem(key: string, value: string): void {
    this.#items.set(key, String(value));
  }
}

function realStorage(name: 'localStorage' | 'sessionStorage'): Storage | null {
  try {
    return globalThis[name];
  } catch (error) {
    console.warn('[widget page] storage unavailable', name, error);
    return null;
  }
}

/* localStorage.getItem('claude_tunnel_token') */
export function isolateStorage(seed: boolean): void {
  for (const name of ['localStorage', 'sessionStorage'] as const) {
    Object.defineProperty(globalThis, name, { value: new MemoryStorage(seed ? realStorage(name) : null), configurable: true });
  }
}

export class SilentChannel extends EventTarget {
  readonly name: string;
  onmessage: unknown = null;
  onmessageerror: unknown = null;

  constructor(name: string) {
    super();
    this.name = name;
  }

  postMessage(): void {}

  close(): void {}
}

export function silenceBroadcast(): void {
  (globalThis as { BroadcastChannel: unknown }).BroadcastChannel = SilentChannel;
}
