export const channelNames = new Set<string>();

const open = new Map<string, Set<FakeChannel>>();

class FakeChannel {
  onmessage: ((event: MessageEvent) => void) | null = null;
  readonly #listeners = new Set<(event: MessageEvent) => void>();

  constructor(readonly name: string) {
    channelNames.add(name);
    if (!open.has(name)) open.set(name, new Set());
    open.get(name)!.add(this);
  }

  postMessage(data: unknown): void {
    for (const other of open.get(this.name) ?? []) {
      if (other === this) continue;
      queueMicrotask(() => {
        const event = { data } as MessageEvent;
        other.onmessage?.(event);
        for (const one of other.#listeners) one(event);
      });
    }
  }

  addEventListener(_kind: string, listener: (event: MessageEvent) => void): void {
    this.#listeners.add(listener);
  }

  close(): void {
    open.get(this.name)?.delete(this);
  }
}

export function installLabBus(): void {
  open.clear();
  channelNames.clear();
  sessionStorage.clear();
  (globalThis as { BroadcastChannel?: unknown }).BroadcastChannel = FakeChannel;
  (globalThis as { Themes?: unknown }).Themes = {
    listAll: () => [{ id: 'carnivore', name: 'carnivore' }, { id: 'blade_runner', name: 'blade runner' }],
    getActiveGlobal: () => ({ id: 'carnivore' }),
  };
  localStorage.clear();
}

export const SAMPLE_TABLE = {
  schema: 1, generated_at: '2026-10-18', counts: { pass: 1, fail: 2, unsupported: 1 }, hosts: { home: ['m'], terminal: ['m'] },
  widgets: [
    { widget: 'core.notes', ok: false, determined: true, failures: 1, cells: {
      'home/m': { verdict: 'pass', red: false, draws: 8, reasons: [] },
      'terminal/m': { verdict: 'fail', red: true, draws: 8, reasons: ['core.notes terminal/m/data/carnivore: overflow-x: runs 5px past'] } } },
    { widget: 'core.gone', ok: false, determined: false, failures: 1, cells: {} },
  ],
};
