import { formatEntry } from '../../../client/js/i18n/format.js';
import enCatalog, { intlLocale } from '../../../client/js/i18n/catalog.en.js';

const MESSAGES = enCatalog as unknown as Record<string, unknown>;

/* the refusal ladder */
export function hasKey(key: string): boolean {
    return Object.prototype.hasOwnProperty.call(MESSAGES, key);
}

export function t(key: string, params?: Record<string, unknown> | null): string {
    const entry = MESSAGES[key];
    if (entry === undefined) return key;
    const said = formatEntry(entry, params || null, intlLocale, () => {});
    return typeof said === 'string' ? said : key;
}
