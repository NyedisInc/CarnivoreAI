import { CATALOGS, DEFAULT_LOCALE } from '../../../../client/js/i18n/catalogs.js';
import { isFeatureTier } from '../catalog/app-own';
import type { Translate } from '../sessions/types';

const PLUGIN_PREFIX = 'plugins.page.';
const FEATURE_PREFIX = 'features.page.';

const TWINS: ReadonlySet<string> = new Set(
    Object.keys(CATALOGS[DEFAULT_LOCALE]?.messages ?? {}).filter((key) => key.startsWith(FEATURE_PREFIX)),
);

export function featureWords(t: Translate): Translate {
    return (key, params) => {
        if (!key.startsWith(PLUGIN_PREFIX)) return t(key, params);
        const twin = `${FEATURE_PREFIX}${key.slice(PLUGIN_PREFIX.length)}`;
        return t(TWINS.has(twin) ? twin : key, params);
    };
}

export function featureRows<T extends { readonly tier: string }>(rows: readonly T[], developerMode: boolean): T[] {
    return rows.filter((row) => isFeatureTier(row.tier) && (row.tier !== 'dev' || developerMode));
}
