import { SvelteMap } from 'svelte/reactivity';

export interface Connection { text: string; className: string }

export type Transport = 'connected' | 'disconnected' | 'unknown';

const transports = new SvelteMap<string, Transport>();

export function noteConnection(sessionId: string, connection: Connection | null): void {
  if (!sessionId) return;
  if (!connection) { transports.delete(sessionId); return; }
  const prev = transports.get(sessionId);
  const next: Transport = connection.className === 'connected' ? 'connected'
    : connection.className === 'error' || prev === 'disconnected' ? 'disconnected' : 'unknown';
  if (prev !== next) transports.set(sessionId, next);
}

export function transportFor(sessionId: string): Transport {
  return transports.get(sessionId) ?? 'unknown';
}
