import { PreferenceField, savePreference } from '../zone-shell/preference-field';
import { isEmpty, readOverrides, withChords, withoutChords, type KeymapOverrides } from './keymap-overrides';
import type { KeyboardFamily } from './keymap-view';

export const KEYMAP_FIELD = 'keymap';

class KeymapStore {
    overrides = $state<KeymapOverrides>({});

    readonly #pref = new PreferenceField(KEYMAP_FIELD, (value) => {
        this.overrides = readOverrides(value);
    });

    start(target?: Window | null): void {
        this.#pref.start(target);
    }

    reload(): void {
        this.#pref.reload();
    }

    async #commit(next: KeymapOverrides): Promise<string | null> {
        const before = this.overrides;
        this.overrides = next;
        const failure = await savePreference(KEYMAP_FIELD, isEmpty(next) ? null : next);
        if (failure) this.overrides = before;
        return failure;
    }

    set(family: KeyboardFamily | 'mouse', id: string, chords: readonly string[]): Promise<string | null> {
        return this.#commit(withChords(this.overrides, family, id, chords));
    }

    reset(family: KeyboardFamily | 'mouse', id: string): Promise<string | null> {
        return this.#commit(withoutChords(this.overrides, family, id));
    }

    resetAll(): Promise<string | null> {
        return this.#commit({});
    }
}

export const keymapStore = new KeymapStore();
