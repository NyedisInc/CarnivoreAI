
interface Registry {
    applyTheme(id: string, options: { persist: boolean }): boolean;
    getActiveGlobal?(): { id?: string } | null;
    DEFAULT_THEME_ID?: string;
}

const registry = (): Registry | undefined => (globalThis as { Themes?: Registry }).Themes;

export const RECENT_THEMES_KEY = 'carnivore.themes.recent';

export const MAX_RECENT_THEMES = 6;

export function recentThemeIds(): string[] {
    try {
        const parsed: unknown = JSON.parse(globalThis.localStorage?.getItem(RECENT_THEMES_KEY) ?? '[]');
        return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : [];
    } catch (err) {
        if (typeof console !== 'undefined') console.warn('CloudeWeb: recent themes unreadable', err);
        return [];
    }
}

function remember(id: string): void {
    const next = [id, ...recentThemeIds().filter((entry) => entry !== id)].slice(0, MAX_RECENT_THEMES);
    try {
        globalThis.localStorage?.setItem(RECENT_THEMES_KEY, JSON.stringify(next));
    } catch (err) {
        if (typeof console !== 'undefined') console.warn('CloudeWeb: recent themes not written', err);
    }
}

export function applyGlobalTheme(id: string): boolean {
    const applied = registry()?.applyTheme(id, { persist: true }) === true;
    if (applied) remember(id);
    return applied;
}

export function activeGlobalThemeId(): string {
    return registry()?.getActiveGlobal?.()?.id ?? document.documentElement.dataset.theme ?? registry()?.DEFAULT_THEME_ID ?? '';
}
