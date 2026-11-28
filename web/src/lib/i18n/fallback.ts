import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { registerFragment } from '../../../../client/js/i18n/catalogs.js';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';

export const HAS_BUNDLED_CATALOG = true;

export function createFallbackI18n(options?: { locale?: string }): ReturnType<typeof createI18n> {
    return createI18n(options);
}

export function registerLocalFragment(pluginId: string, messages: Record<string, unknown>): number {
    return registerFragment(pluginId, messages);
}

export function fallbackCatalogKeys(): string[] {
    return Object.keys(enCatalog as Record<string, unknown>);
}
