import { readCached, writeCached } from '../../lib/data-cache/cache';

const CHANNEL_NAME = 'carnivore-stats-bus';
const MAX_ENTRIES = 256;

interface Entry {
  at: number;
  value: unknown;
}

const mem = new Map<string, Entry>();
let channel: BroadcastChannel | null = null;

function ensureChannel(): BroadcastChannel | null {
  if (channel) return channel;
  if (typeof globalThis.BroadcastChannel !== 'function') return null;
  const proc = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
  if (proc?.env?.VITEST) return null;
  try {
    channel = new BroadcastChannel(CHANNEL_NAME);
    (channel as unknown as { unref?: () => void }).unref?.();
    channel.onmessage = (ev: MessageEvent) => {
      const msg = ev.data as { type?: string; key?: string; value?: unknown; at?: number } | null;
      if (!msg || msg.type !== 'put' || typeof msg.key !== 'string' || typeof msg.at !== 'number') return;
      storeLocal(msg.key, msg.value, msg.at);
    };
  } catch {
    channel = null;
  }
  return channel;
}

function storeLocal(key: string, value: unknown, at: number): void {
  if (mem.size >= MAX_ENTRIES && !mem.has(key)) {
    const first = mem.keys().next().value;
    if (first !== undefined) mem.delete(first);
  }
  mem.set(key, { at, value });
}

export function getShared<T>(key: string, maxAgeMs: number): T | null {
  ensureChannel();
  const hit = mem.get(key);
  if (!hit || Date.now() - hit.at > maxAgeMs) return null;
  return hit.value as T;
}

export function publishShared<T>(key: string, value: T): void {
  const at = Date.now();
  try {
    ensureChannel()?.postMessage({ type: 'put', key, value, at });
  } catch {
  }
}

export async function shareFetch<T>(key: string, maxAgeMs: number, fetcher: () => Promise<T>): Promise<T> {
  const hit = getShared<T>(key, maxAgeMs);
  if (hit !== null) return hit;
  const value = await fetcher();
  publishShared(key, value);
  return value;
}

export async function readColdCache<T>(name: string): Promise<T | null> {
  return readCached<T>(name);
}

export function writeColdCache<T>(name: string, value: T): void {
  void writeCached(name, value);
}
