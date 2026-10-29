
import { freezeClock } from './freeze-clock';
import { isolateStorage, silenceBroadcast } from './isolated-world';
import { OfflineSocket } from './offline-socket';

export const ACCESS_KEY = 'claude_tunnel_token';

export interface FrameWorldOptions {
  seedStorage: boolean;
  placeholderToken: string | null;
  freeze: boolean;
}

export function isolateWorld(options: FrameWorldOptions): void {
  if (options.freeze) freezeClock();
  isolateStorage(options.seedStorage);
  silenceBroadcast();
  if (options.placeholderToken !== null && !globalThis.localStorage.getItem(ACCESS_KEY)) {
    globalThis.localStorage.setItem(ACCESS_KEY, options.placeholderToken);
  }
  (globalThis as { WebSocket: unknown }).WebSocket = OfflineSocket;
}

export interface ApiRequest {
  method: string;
  path: string;
  url: URL;
  init: RequestInit | undefined;
}

export function installApiInterceptor(base: string, origin: string, answer: (request: ApiRequest) => Promise<Response>): void {
  const realFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, base);
    if (url.origin !== origin || !url.pathname.startsWith('/api/')) return realFetch(input instanceof Request ? input : url.href, init);
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    return answer({ method, path: url.pathname.replace(/^\/api\/v1/, ''), url, init });
  };
}
