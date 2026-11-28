import { fallbackCatalogKeys } from '../i18n/fallback';
import { isFeatureTier } from '../catalog/app-own';
import type { Translate } from '../sessions/types';

const PLUGIN_PREFIX = 'plugins.page.';
const FEATURE_PREFIX = 'features.page.';

let cachedTwins: ReadonlySet<string> | null = null;
function featureTwins(): ReadonlySet<string> {
    if (cachedTwins && cachedTwins.size > 0) return cachedTwins;
    const layer = (globalThis as { CloudeI18n?: { catalogFor?(locale: string): { messages?: Record<string, unknown> } } }).CloudeI18n;
    const msgs = layer?.catalogFor?.('en')?.messages;
    const keys = msgs ? Object.keys(msgs) : fallbackCatalogKeys();
    cachedTwins = new Set(keys.filter((key) => key.startsWith(FEATURE_PREFIX)));
    return cachedTwins;
}

export function featureWords(t: Translate): Translate {
    return (key, params) => {
        if (!key.startsWith(PLUGIN_PREFIX)) return t(key, params);
        const twin = `${FEATURE_PREFIX}${key.slice(PLUGIN_PREFIX.length)}`;
        return t(featureTwins().has(twin) ? twin : key, params);
    };
}

export function featureRows<T extends { readonly tier: string }>(rows: readonly T[], developerMode: boolean): T[] {
    return rows.filter((row) => isFeatureTier(row.tier) && (row.tier !== 'dev' || developerMode));
}
