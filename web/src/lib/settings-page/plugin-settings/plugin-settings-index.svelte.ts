import type { ResourcePushGlobal } from '../../resource-push/boot';
import type { CplugRow } from '../../plugins-page/cplugs-adapter';
import { CPLUGS_TOPIC, POLL_MS, pluginsStore } from '../../plugins/store.svelte';

export { CPLUGS_TOPIC };

export const INDEX_POLL_MS = POLL_MS;

export interface IndexDeps {
    readonly read: () => Promise<readonly CplugRow[]>;
    readonly push: () => Pick<ResourcePushGlobal, 'pushOrPoll'>;
}

export class PluginSettingsIndex {
    #customRows = $state<readonly CplugRow[]>([]);
    #customRead = $state(false);
    readonly #customDeps: IndexDeps | null;

    constructor(deps?: IndexDeps) {
        this.#customDeps = deps ?? null;
    }

    get rows(): readonly CplugRow[] {
        return this.#customDeps ? this.#customRows : pluginsStore.rows;
    }

    set rows(value: readonly CplugRow[]) {
        if (this.#customDeps) this.#customRows = value;
        else pluginsStore.rows = value;
    }

    get read(): boolean {
        return this.#customDeps ? this.#customRead : pluginsStore.read;
    }

    set read(value: boolean) {
        if (this.#customDeps) this.#customRead = value;
        else pluginsStore.read = value;
    }

    async load(): Promise<void> {
        if (!this.#customDeps) {
            await pluginsStore.refresh({ force: true, allowSignedOut: true });
            return;
        }
        try {
            this.#customRows = await this.#customDeps.read();
            this.#customRead = true;
        } catch {
        }
    }

    start(): () => void {
        if (!this.#customDeps) {
            pluginsStore.read = false;
            return pluginsStore.acquire({ allowSignedOut: true });
        }
        this.#customRead = false;
        const stop = this.#customDeps.push().pushOrPoll(() => void this.load(), INDEX_POLL_MS, [CPLUGS_TOPIC]);
        void this.load();
        return stop;
    }
}

export const pluginSettingsIndex = new PluginSettingsIndex();
