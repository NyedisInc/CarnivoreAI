
const KEY = 'carnivore.sessions.folds';

function read(): Record<string, boolean> {
    try {
        const parsed: unknown = JSON.parse(globalThis.localStorage?.getItem(KEY) ?? '{}');
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return {};
        return Object.fromEntries(Object.entries(parsed).filter(([, v]) => typeof v === 'boolean'));
    } catch {
        return {};
    }
}

export class Folds {
    #choices = $state<Record<string, boolean>>(read());

    isFolded(key: string, fallback = false): boolean {
        return this.#choices[key] ?? fallback;
    }

    toggle(key: string, fallback = false): void {
        this.#choices[key] = !this.isFolded(key, fallback);
        try {
            globalThis.localStorage?.setItem(KEY, JSON.stringify(this.#choices));
        } catch {
        }
    }
}
