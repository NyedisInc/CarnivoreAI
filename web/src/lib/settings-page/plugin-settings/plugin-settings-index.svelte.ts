import { authFetch } from '../../../opscenter/api/auth.svelte';
import { resourcePush, type ResourcePushGlobal } from '../../resource-push/boot';
import { CPLUGS_ROUTE, type CplugRow } from '../../plugins-page/cplugs-adapter';

export const CPLUGS_TOPIC = 'cplugs';

export const INDEX_POLL_MS = 60_000;

export interface IndexDeps {
    readonly read: () => Promise<readonly CplugRow[]>;
    readonly push: () => Pick<ResourcePushGlobal, 'pushOrPoll'>;
}

const DEFAULT_DEPS: IndexDeps = {
    read: async () => (await authFetch<{ cplugs?: CplugRow[] }>(CPLUGS_ROUTE))?.cplugs ?? [],
    push: resourcePush,
};

export class PluginSettingsIndex {
    rows = $state<readonly CplugRow[]>([]);
    read = $state(false);
    readonly #deps: IndexDeps;

    constructor(deps: IndexDeps = DEFAULT_DEPS) {
        this.#deps = deps;
    }

    async load(): Promise<void> {
        try {
            this.rows = await this.#deps.read();
            this.read = true;
        } catch {
        }
    }

    start(): () => void {
        this.read = false;
        const stop = this.#deps.push().pushOrPoll(() => void this.load(), INDEX_POLL_MS, [CPLUGS_TOPIC]);
        void this.load();
        return stop;
    }
}

export const pluginSettingsIndex = new PluginSettingsIndex();
