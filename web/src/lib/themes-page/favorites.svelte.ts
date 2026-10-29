
import { whenLegacyBootComplete } from '../legacy-boot';

export const THEME_FAVORITES_FIELD = 'theme_favorites';

export const THEME_FAVORITES_CACHE_KEY = 'carnivore.themes.favorites';

export const MAX_THEME_FAVORITES = 200;

export const SKILL_FAVORITES_FIELD = 'skill_favorites';

export const SKILL_FAVORITES_CACHE_KEY = 'carnivore.skills.favorites';

export const MAX_SKILL_FAVORITES = 200;

interface Bridge {
    read(field: string, localReader: () => unknown): unknown;
    write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
    follow(field: string, apply: (value: unknown) => void): () => void;
}

function bridge(): Bridge | null {
    const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
    return found && typeof found.read === 'function' ? found : null;
}

export function toIds(value: unknown): string[] {
    if (!Array.isArray(value)) return [];
    return [...new Set(value.filter((entry): entry is string => typeof entry === 'string' && entry.length > 0))];
}

function readCache(key: string): unknown {
    try {
        const raw = globalThis.localStorage?.getItem(key);
        return raw ? JSON.parse(raw) : undefined;
    } catch (err) {
        if (typeof console !== 'undefined') console.warn('CloudeWeb: theme favorites cache unreadable', err);
        return undefined;
    }
}

function writeCache(key: string, ids: string[]): void {
    try {
        globalThis.localStorage?.setItem(key, JSON.stringify(ids));
    } catch (err) {
        if (typeof console !== 'undefined') console.warn('CloudeWeb: theme favorites cache not written', err);
    }
}

class Favorites {
    ids = $state<string[]>([]);

    #started = false;

    constructor(
        private readonly field: string,
        private readonly cacheKey: string,
        private readonly max: number,
    ) {}

    start(target: Window | null = typeof window !== 'undefined' ? window : null): void {
        if (this.#started) return;
        this.#started = true;
        this.reload();
        bridge()?.follow(this.field, (value) => {
            this.ids = toIds(value);
            writeCache(this.cacheKey, this.ids);
        });
        whenLegacyBootComplete(target, () => this.reload());
    }

    reload(): void {
        const found = bridge();
        const cached = (): unknown => readCache(this.cacheKey);
        this.ids = toIds(found ? found.read(this.field, cached) : cached());
    }

    has(id: string): boolean {
        return this.ids.includes(id);
    }

    toggle(id: string): boolean {
        const starred = this.has(id);
        if (!starred && this.ids.length >= this.max) return false;
        const next = starred ? this.ids.filter((entry) => entry !== id) : [...this.ids, id];
        this.ids = next;
        const found = bridge();
        if (found) void found.write(this.field, next, () => writeCache(this.cacheKey, next));
        else writeCache(this.cacheKey, next);
        return true;
    }
}

export const themeFavorites = new Favorites(THEME_FAVORITES_FIELD, THEME_FAVORITES_CACHE_KEY, MAX_THEME_FAVORITES);

export const skillFavorites = new Favorites(SKILL_FAVORITES_FIELD, SKILL_FAVORITES_CACHE_KEY, MAX_SKILL_FAVORITES);
