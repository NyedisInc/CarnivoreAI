/*  hidden  */
import { authFetch } from '../api/auth.svelte';
import { labelResult } from './dimension-label';
import type { AnswerMeta, QueryBody, QueryResult } from '../cells/analytics/types';

export type BatchItem = { ok: true; result: QueryResult; answer?: AnswerMeta } | { ok: false; error: { code: string; message: string } };

export const BATCH_LIMIT = 32;
export const COALESCE_MS = 25;

export interface ClientDeps {
  post: (items: QueryBody[], signal: AbortSignal) => Promise<BatchItem[]>;
  hidden: () => boolean;
  onVisible: (cb: () => void) => () => void;
}

interface Caller {
  items: QueryBody[];
  keys: string[];
  out: (BatchItem | undefined)[];
  left: number;
  signal?: AbortSignal;
  resolve: (value: BatchItem[]) => void;
  reject: (reason: unknown) => void;
  done: boolean;
}

function keyOf(item: QueryBody): string { return JSON.stringify(item); }

export function createQueryClient(deps: ClientDeps): { runQueries: (items: QueryBody[], signal?: AbortSignal) => Promise<BatchItem[]> } {
  let pending: Caller[] = [];
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopWaiting: (() => void) | null = null;

  function fail(caller: Caller, reason: unknown): void {
    if (caller.done) return;
    caller.done = true;
    caller.reject(reason);
  }

  function deliver(waiters: { caller: Caller; index: number }[], outcome: BatchItem): void {
    for (const { caller, index } of waiters) {
      if (caller.done) continue;
      caller.out[index] = outcome;
      if (--caller.left === 0) { caller.done = true; caller.resolve(caller.out as BatchItem[]); }
    }
  }

  async function sendChunk(keys: string[], bodies: Map<string, QueryBody>, waiting: Map<string, { caller: Caller; index: number }[]>): Promise<void> {
    const controller = new AbortController();
    const callers = new Set(keys.flatMap((key) => waiting.get(key)!.map((waiter) => waiter.caller)));
    const listeners: (() => void)[] = [];
    const check = (): void => { if ([...callers].every((caller) => caller.done)) controller.abort(); };
    for (const caller of callers) {
      if (!caller.signal) continue;
      const onAbort = (): void => { fail(caller, new DOMException('aborted', 'AbortError')); check(); };
      caller.signal.addEventListener('abort', onAbort, { once: true });
      listeners.push(() => caller.signal!.removeEventListener('abort', onAbort));
    }
    try {
      const outcomes = await deps.post(keys.map((key) => bodies.get(key)!), controller.signal);
      keys.forEach((key, at) => deliver(waiting.get(key)!, outcomes[at] ?? { ok: false, error: { code: 'missing_result', message: 'no result for this item' } }));
    } catch (error) {
      for (const caller of callers) fail(caller, error);
    } finally { listeners.forEach((off) => off()); }
  }

  function flush(): void {
    timer = null;
    if (deps.hidden()) {
      if (!stopWaiting) stopWaiting = deps.onVisible(() => { stopWaiting = null; schedule(); });
      return;
    }
    const batch = pending.filter((caller) => !caller.done);
    pending = [];
    const bodies = new Map<string, QueryBody>();
    const waiting = new Map<string, { caller: Caller; index: number }[]>();
    for (const caller of batch) {
      caller.items.forEach((item, index) => {
        const key = caller.keys[index]!;
        bodies.set(key, item);
        (waiting.get(key) ?? waiting.set(key, []).get(key)!).push({ caller, index });
      });
    }
    const keys = [...bodies.keys()];
    for (let at = 0; at < keys.length; at += BATCH_LIMIT) void sendChunk(keys.slice(at, at + BATCH_LIMIT), bodies, waiting);
  }

  function schedule(): void { if (!timer) timer = setTimeout(flush, COALESCE_MS); }

  function runQueries(items: QueryBody[], signal?: AbortSignal): Promise<BatchItem[]> {
    if (items.length === 0) return Promise.resolve([]);
    if (signal?.aborted) return Promise.reject(new DOMException('aborted', 'AbortError'));
    return new Promise((resolve, reject) => {
      const caller: Caller = { items, keys: items.map(keyOf), out: new Array(items.length), left: items.length, signal, resolve, reject, done: false };
      signal?.addEventListener('abort', () => fail(caller, new DOMException('aborted', 'AbortError')), { once: true });
      pending.push(caller);
      schedule();
    });
  }

  return { runQueries };
}

export const queryClient = createQueryClient({
  post: async (items, signal) => {
    const response = await authFetch<{ results: BatchItem[] }>('/stats/query-batch', { method: 'POST', body: JSON.stringify({ items }), signal });
    return response.results.map((item, at) => (item.ok && items[at] ? { ...item, result: labelResult(items[at], item.result) } : item));
  },
  hidden: () => typeof document !== 'undefined' && document.visibilityState === 'hidden',
  onVisible: (cb) => {
    const handler = (): void => { if (document.visibilityState !== 'hidden') { document.removeEventListener('visibilitychange', handler); cb(); } };
    document.addEventListener('visibilitychange', handler);
    return () => document.removeEventListener('visibilitychange', handler);
  },
});

export const runQueries = queryClient.runQueries;
