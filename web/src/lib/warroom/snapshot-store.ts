/*  hidden  */
import { authFetch } from '../../opscenter/api/auth.svelte';

export const WALL_MS = 5000;
export const HOT_MS = 1000;
export function wallIntervalMs(count: number): number {
  return Math.min(WALL_MS, Math.max(HOT_MS, count * 125));
}
export const MAX_PER_CALL = 40;

/* did not answer */
export interface Snapshot {
  status: 'ok' | 'gone' | 'unsupported' | 'older' | 'unreachable';
  cols: number;
  rows: number;
  hash: string;
  screen: string;
}

export type SnapshotListener = (snapshot: Snapshot) => void;

export interface StoreDeps {
  fetchScreens: (items: Array<{ id: string; hash?: string }>) => Promise<Record<string, Snapshot>>;
  now: () => number;
  setTimer: (callback: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
  pageVisible: () => boolean;
  onVisibility: (callback: () => void) => () => void;
}

interface Entry {
  listeners: Set<SnapshotListener>;
  hash?: string;
  lastAt: number;
}

function realDeps(): StoreDeps {
  return {
    fetchScreens: async (items) => {
      const answer = await authFetch<{ screens: Record<string, Snapshot> }>('/warroom/screens', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ items }),
      });
      return answer.screens;
    },
    now: () => Date.now(),
    setTimer: (callback, ms) => globalThis.setTimeout(callback, ms),
    clearTimer: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
    pageVisible: () => globalThis.document?.visibilityState !== 'hidden',
    onVisibility: (callback) => {
      globalThis.document?.addEventListener('visibilitychange', callback);
      return () => globalThis.document?.removeEventListener('visibilitychange', callback);
    },
  };
}

export interface SnapshotStore {
  subscribe(id: string, listener: SnapshotListener): () => void;
  setHot(id: string | null): void;
  releaseHot(id: string): void;
}

export function createSnapshotStore(deps: StoreDeps = realDeps()): SnapshotStore {
  const entries = new Map<string, Entry>();
  let hot: string | null = null;
  let timer: unknown = null;
  let inFlight = false;
  let remoteInFlight = false;
  let stopVisibility: (() => void) | null = null;

  const wanted = (): boolean => entries.size > 0 && deps.pageVisible();

  function arm(): void {
    if (timer !== null) deps.clearTimer(timer);
    timer = null;
    if (!wanted()) return;
    timer = deps.setTimer(() => void tick(), hot !== null && entries.has(hot) ? HOT_MS : wallIntervalMs(entries.size));
  }

  async function tick(): Promise<void> {
    if (timer !== null) deps.clearTimer(timer);
    timer = null;
    if (!wanted() || inFlight) return arm();
    const now = deps.now();
    const due = [...entries].filter(([id, e]) => id === hot || now - e.lastAt >= wallIntervalMs(entries.size) - 50);
    const isRemote = ([id]: [string, Entry]): boolean => id.startsWith('remote:');
    const remoteDue = remoteInFlight ? [] : due.filter(isRemote);
    if (remoteDue.length > 0) void readRemote(remoteDue);
    const localDue = due.filter((d) => !isRemote(d));
    inFlight = true;
    try {
      for (let at = 0; at < localDue.length; at += MAX_PER_CALL) await readBatch(localDue.slice(at, at + MAX_PER_CALL));
    } catch {
    } finally {
      inFlight = false;
      arm();
    }
  }

  async function readBatch(batch: Array<[string, Entry]>): Promise<void> {
    const answer = await deps.fetchScreens(batch.map(([id, e]) => (e.hash ? { id, hash: e.hash } : { id })));
    for (const [id, e] of batch) {
      e.lastAt = deps.now();
      const shot = answer[id];
      if (!shot || !entries.has(id)) continue;
      if (shot.status === 'ok') e.hash = shot.hash;
      else if (shot.status !== 'unreachable') e.hash = undefined;
      for (const listener of e.listeners) listener(shot);
    }
  }

  async function readRemote(remoteDue: Array<[string, Entry]>): Promise<void> {
    remoteInFlight = true;
    try {
      for (let at = 0; at < remoteDue.length; at += MAX_PER_CALL) await readBatch(remoteDue.slice(at, at + MAX_PER_CALL));
    } catch {
    } finally {
      remoteInFlight = false;
    }
  }

  function syncVisibility(): void {
    if (entries.size > 0 && !stopVisibility) {
      stopVisibility = deps.onVisibility(() => (deps.pageVisible() ? void tick() : arm()));
    } else if (entries.size === 0 && stopVisibility) {
      stopVisibility();
      stopVisibility = null;
    }
  }

  return {
    subscribe(id, listener) {
      let entry = entries.get(id);
      if (!entry) {
        entry = { listeners: new Set(), lastAt: 0 };
        entries.set(id, entry);
      }
      entry.listeners.add(listener);
      syncVisibility();
      if (timer !== null) deps.clearTimer(timer);
      timer = deps.setTimer(() => void tick(), 0);
      return () => {
        const current = entries.get(id);
        current?.listeners.delete(listener);
        if (current && current.listeners.size === 0) entries.delete(id);
        if (hot === id && !entries.has(id)) hot = null;
        syncVisibility();
        arm();
      };
    },
    setHot(id) {
      if (hot === id) return;
      hot = id;
      arm();
      if (id !== null && entries.has(id)) void tick();
    },
    releaseHot(id) {
      if (hot === id) {
        hot = null;
        arm();
      }
    },
  };
}

export const snapshotStore: SnapshotStore = createSnapshotStore();
