import { settingsFeatureFragment, settingsFeatureOf, writeSettingsFragment, type FeatureLink } from '../settings-hash';
import { settingsView } from '../settings-view.svelte';

export class FeatureRouting {
    focus = $state<FeatureLink | null>(null);
    readonly #embedded: boolean;
    readonly #leave: () => void;

    constructor(embedded: boolean, leave: () => void) {
        this.#embedded = embedded;
        this.#leave = leave;
    }

    pick(id: string, settings: boolean, mode: 'push' | 'replace' = 'push'): void {
        this.#leave();
        settingsView.section = 'features';
        this.focus = { id, settings };
        if (!this.#embedded) writeSettingsFragment(settingsFeatureFragment(id, settings), mode);
    }

    select(id: string, paneTab: string): void {
        if (!this.#embedded) writeSettingsFragment(settingsFeatureFragment(id, paneTab === 'settings'), 'replace');
    }

    clear(): void {
        this.focus = null;
    }

    follow(hash: string): FeatureLink | null {
        const link = settingsFeatureOf(hash);
        if (link) {
            this.#leave();
            settingsView.section = 'features';
        }
        this.focus = link;
        return link;
    }
}
