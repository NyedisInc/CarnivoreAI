/* there is nothing */
import { createFallbackI18n, HAS_BUNDLED_CATALOG } from './fallback';
import { registerPluginSlices } from './plugin-fragments';

export interface I18n {
    t(key: string, params?: Record<string, unknown> | null): string;
    setLocale(next: string): boolean;
    onLocaleChange(fn: (locale: string) => void): () => void;
    availableLocales(): string[];
    extendCatalog?(pluginId: string, messages: Record<string, unknown>): number;
    readonly locale: string;
    readonly problems: string[];
}

export const i18n: I18n =
    (globalThis as { CloudeI18n?: I18n }).CloudeI18n ?? (createFallbackI18n() as I18n);

registerPluginSlices((pluginId, messages) => i18n.extendCatalog?.(pluginId, messages));

let localeVersion = $state(0);

i18n.onLocaleChange(() => {
    localeVersion += 1;
});

let bundled: I18n | null = null;

function bundledCatalog(): I18n {
    if (!bundled || bundled.locale !== i18n.locale) bundled = createFallbackI18n({ locale: i18n.locale }) as I18n;
    return bundled;
}

export function t(key: string, params?: Record<string, unknown> | null): string {
    void localeVersion;
    const out = i18n.t(key, params);
    return HAS_BUNDLED_CATALOG && key && out === key ? bundledCatalog().t(key, params) : out;
}

export function setLocale(next: string): boolean {
    return i18n.setLocale(next);
}

export function currentLocale(): string {
    void localeVersion;
    return i18n.locale;
}
