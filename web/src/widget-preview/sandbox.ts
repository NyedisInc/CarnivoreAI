
import { freezeClock } from '../opscenter/widgets/fixtures/freeze-clock';
import { OfflineSocket } from '../opscenter/widgets/fixtures/offline-socket';
import { answerResponse, jsonResponse, lookup } from '../opscenter/widgets/fixtures/route-lookup';
import type { RouteTable } from '../opscenter/widgets/fixtures/types';
import { isolateStorage, silenceBroadcast } from '../opscenter/widgets/fixtures/isolated-world';
import { PREVIEW_PORT_MESSAGE, readPreviewConfig, type PreviewAnswer, type PreviewConfig } from './protocol';

const ORIGIN = globalThis.origin;
const BASE = document.baseURI;

const ACCESS_KEY = 'claude_tunnel_token';

const PLACEHOLDER_TOKEN = 'widget-preview-sample';

export const previewConfig: PreviewConfig | null = readPreviewConfig(document);

let provideTable: (table: RouteTable) => void = () => {};
const tableReady = new Promise<RouteTable>((resolve) => {
  provideTable = resolve;
});

export function serveFixture(table: RouteTable): void {
  provideTable(table);
}

let providePort: (port: MessagePort) => void = () => {};
const portReady = new Promise<MessagePort>((resolve) => {
  providePort = resolve;
});

const waiting = new Map<number, (answer: PreviewAnswer) => void>();
let nextId = 1;

function listenForPort(): void {
  globalThis.addEventListener('message', (event: MessageEvent) => {
    if (event.origin !== ORIGIN || event.data?.type !== PREVIEW_PORT_MESSAGE) return;
    const port = event.ports[0];
    if (!port) return;
    port.onmessage = (answer: MessageEvent<PreviewAnswer>) => {
      waiting.get(answer.data.id)?.(answer.data);
      waiting.delete(answer.data.id);
    };
    providePort(port);
  });
}

async function askPage(path: string): Promise<Response> {
  const port = await portReady;
  const id = nextId++;
  const answer = await new Promise<PreviewAnswer>((resolve) => {
    waiting.set(id, resolve);
    port.postMessage({ id, path });
  });
  if (answer.ok) return jsonResponse(200, answer.body);
  return jsonResponse(answer.status === 401 ? 503 : answer.status || 503, { detail: answer.detail });
}

function installFetch(mode: PreviewConfig['mode']): void {
  const realFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, BASE);
    if (url.origin !== ORIGIN || !url.pathname.startsWith('/api/')) return realFetch(input instanceof Request ? input : url.href, init);
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (method !== 'GET') return jsonResponse(405, { detail: 'a preview reads only' });
    const path = url.pathname.replace(/^\/api\/v1/, '');
    if (mode === 'real') return askPage(`${path}${url.search}`);
    const answer = lookup(await tableReady, method, path);
    return answer === undefined ? jsonResponse(404, { detail: 'not in this widget fixture' }) : answerResponse(answer, url, init, method);
  };
}

isolateStorage(true);
if (previewConfig?.mode !== 'real' && !globalThis.localStorage.getItem(ACCESS_KEY)) {
  globalThis.localStorage.setItem(ACCESS_KEY, PLACEHOLDER_TOKEN);
}
(globalThis as { WebSocket: unknown }).WebSocket = OfflineSocket;
silenceBroadcast();
if (previewConfig?.mode !== 'real') freezeClock();
listenForPort();
installFetch(previewConfig?.mode ?? 'sample');
