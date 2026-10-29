
export interface ConnectionHost {
  subscribe(handler: (frame: { type?: string }) => void): () => void;
  isConnected(): boolean;
  reconnectNow?(manual?: boolean): void;
}

export interface ConnectionState {
  live: boolean;
  everLive: boolean;
  downSince: number;
}

export const OFFLINE_GRACE_MS = 8000;

export const connection: ConnectionState = $state({ live: false, everLive: false, downSince: Date.now() });

let attached: ConnectionHost | null = null;

function pageHost(): ConnectionHost | null {
  const found = (globalThis as { AppEvents?: unknown }).AppEvents as ConnectionHost | undefined;
  return found && typeof found.subscribe === 'function' ? found : null;
}

export function startConnectionWatch(
  host: ConnectionHost | null = pageHost(),
  now: () => number = Date.now,
): () => void {
  if (attached) return () => {};
  connection.downSince = now();
  if (!host) return () => {};
  attached = host;
  if (host.isConnected()) {
    connection.live = true;
    connection.everLive = true;
  }
  const off = host.subscribe((frame) => {
    if (!frame || typeof frame.type !== 'string') return;
    if (frame.type === 'events.open' || frame.type === 'events.hello') {
      connection.live = true;
      connection.everLive = true;
    } else if (frame.type === 'events.closed' && connection.live) {
      connection.live = false;
      connection.downSince = now();
    }
  });
  return () => {
    off();
    attached = null;
  };
}

export function offlineAge(state: ConnectionState, at: number, graceMs: number = OFFLINE_GRACE_MS): number | null {
  if (state.live) return null;
  const age = Math.max(0, at - state.downSince);
  return age >= graceMs ? age : null;
}

export interface AgeParts {
  unit: 'seconds' | 'minutes' | 'hours' | 'days';
  count: number;
}

export function ageParts(ms: number): AgeParts {
  const s = Math.floor(ms / 1000);
  if (s < 60) return { unit: 'seconds', count: s };
  if (s < 3600) return { unit: 'minutes', count: Math.floor(s / 60) };
  if (s < 86400) return { unit: 'hours', count: Math.floor(s / 3600) };
  return { unit: 'days', count: Math.floor(s / 86400) };
}

export function retryConnection(): boolean {
  const host = attached ?? pageHost();
  if (!host || typeof host.reconnectNow !== 'function') return false;
  host.reconnectNow(true);
  return true;
}

export function _resetConnectionForTest(): void {
  attached = null;
  connection.live = false;
  connection.everLive = false;
  connection.downSince = Date.now();
}
