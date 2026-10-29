
import type { FixtureKind, RouteTable } from '../opscenter/widgets/fixtures/types';
import { answerResponse, jsonResponse, lookup } from '../opscenter/widgets/fixtures/route-lookup';
import { installApiInterceptor, isolateWorld } from '../opscenter/widgets/fixtures/frame-world';
import { ScenarioStore } from './scenario-store';
import { harnessState } from './state';

export const params = new URLSearchParams(globalThis.location?.search ?? '');

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
  installApiInterceptor(BASE, ORIGIN, async ({ method, path, url, init }) => {
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
  });
}

export const fixtureKind: FixtureKind = params.get('fixture') === 'empty' ? 'empty' : params.get('fixture') === 'stress' ? 'stress' : 'data';

isolateWorld({ seedStorage: false, placeholderToken: PLACEHOLDER_TOKEN, freeze: true });
installFixtureServer();
