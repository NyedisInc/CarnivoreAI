
import { freezeClock } from '../opscenter/widgets/fixtures/freeze-clock';
import type { FixtureKind, RouteTable } from '../opscenter/widgets/fixtures/types';
import { answerResponse, jsonResponse, lookup } from '../opscenter/widgets/fixtures/route-lookup';
import { OfflineSocket } from '../opscenter/widgets/fixtures/offline-socket';
import { isolateStorage, silenceBroadcast } from '../opscenter/widgets/fixtures/isolated-world';
import { ScenarioStore } from './scenario-store';
import { harnessState } from './state';

export const params = new URLSearchParams(globalThis.location?.search ?? '');

const ACCESS_KEY = 'claude_tunnel_token';

const PLACEHOLDER_TOKEN = 'widget-harness-placeholder';

const ORIGIN = globalThis.origin;
const BASE = document.baseURI;

let provideStore: (store: ScenarioStore) => void = () => {};
const storeReady = new Promise<ScenarioStore>((resolve) => {
  provideStore = resolve;
});

export function serveFixture(table: RouteTable): void {
  provideStore(new ScenarioStore(table));
}

export const scenarioWanted: boolean = params.get('scenario') === 'wait';

let provideScenarioText: (text: string) => void = () => {};
export const scenarioText = new Promise<string>((resolve) => {
  provideScenarioText = resolve;
});
(harnessState as typeof harnessState & Record<string, unknown>)['provideScenario'] = (text: string): void => provideScenarioText(String(text));

function installFixtureServer(): void {
  const realFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, BASE);
    if (url.origin !== ORIGIN || !url.pathname.startsWith('/api/')) {
      return realFetch(input, init);
    }
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const path = url.pathname.replace(/^\/api\/v1/, '');
    harnessState.requests += 1;
    harnessState.counts[`${method} ${path}`] = (harnessState.counts[`${method} ${path}`] ?? 0) + 1;
    if (!harnessState.asked.includes(`${method} ${path}`)) harnessState.asked.push(`${method} ${path}`);
    const store = await storeReady;
    const played = store.simulate(method, path, init);
    if (played !== undefined) return jsonResponse(played.status, played.body);
    const answer = lookup(store.table, method, path);
    if (answer === undefined) {
      harnessState.misses.push(`${method} ${path}`);
      return jsonResponse(404, { detail: 'not in this widget fixture' });
    }
    return answerResponse(answer, url, init, method);
  };
}

export const fixtureKind: FixtureKind = params.get('fixture') === 'empty' ? 'empty' : params.get('fixture') === 'stress' ? 'stress' : 'data';

freezeClock();
isolateStorage(false);
silenceBroadcast();
globalThis.localStorage.setItem(ACCESS_KEY, PLACEHOLDER_TOKEN);
installFixtureServer();
(globalThis as { WebSocket: unknown }).WebSocket = OfflineSocket;
