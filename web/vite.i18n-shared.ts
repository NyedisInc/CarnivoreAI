import type { Plugin } from 'vite';
import { realpathSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';

function real(rel: string): string {
    return realpathSync(fileURLToPath(new URL(rel, import.meta.url)));
}

const FALLBACK_SRC = real('./src/lib/i18n/fallback.ts');
const FALLBACK_BROWSER = real('./src/lib/i18n/fallback.browser.ts');
const PLUGIN_FRAGMENTS_SRC = real('./src/lib/i18n/plugin-fragments.ts');
const PLUGIN_FRAGMENTS_NOOP = real('./src/lib/i18n/plugin-fragments.noop.ts');
const EN_CATALOG_PATH = real('../client/js/i18n/catalog.en.js');
const FORMAT_PATH = real('../client/js/i18n/format.js');
const MENU_KEYS_PATH = real('../client/js/menu-keys.js');

const VIRTUAL_MENU_KEYS_CATALOG = '\0virtual:menu-keys-catalog';

function matchesPath(id: string, target: string): boolean {
    if (id === target) return true;
    try {
        return realpathSync(id) === target;
    } catch {
        return false;
    }
}

export function dedupeI18nPlugin(options: { dropPluginSlices?: boolean } = {}): Plugin {
    return {
        name: 'cloudecode-dedupe-i18n',
        enforce: 'pre',
        async resolveId(source, importer, opts) {
            if (!importer) return null;
            const wantFallback = source.includes('fallback');
            const wantFragments = Boolean(options.dropPluginSlices && source.includes('plugin-fragments'));
            const wantMenuCatalog = source.includes('catalog.en') && matchesPath(importer, MENU_KEYS_PATH);
            if (!wantFallback && !wantFragments && !wantMenuCatalog) return null;
            const resolved = await this.resolve(source, importer, { ...opts, skipSelf: true });
            if (!resolved) return null;
            if (wantFallback && matchesPath(resolved.id, FALLBACK_SRC)) return FALLBACK_BROWSER;
            if (wantFragments && matchesPath(resolved.id, PLUGIN_FRAGMENTS_SRC)) return PLUGIN_FRAGMENTS_NOOP;
            if (wantMenuCatalog && matchesPath(resolved.id, EN_CATALOG_PATH)) return VIRTUAL_MENU_KEYS_CATALOG;
            return null;
        },
        async load(id) {
            if (id !== VIRTUAL_MENU_KEYS_CATALOG) return null;
            const mod = (await import(pathToFileURL(EN_CATALOG_PATH).href)) as {
                default: Record<string, unknown>;
            };
            const subset: Record<string, unknown> = {};
            for (const [k, v] of Object.entries(mod.default)) {
                if (k.startsWith('keymap.menu.status-') || k === 'keymap.shares.status') subset[k] = v;
            }
            return `export default ${JSON.stringify(subset)};`;
        },
    };
}

const VIRTUAL_PAIR_FALLBACK = '\0virtual:pair-i18n-fallback';

export function pairI18nPlugin(): Plugin {
    return {
        name: 'cloudecode-pair-i18n',
        enforce: 'pre',
        async resolveId(source, importer, opts) {
            if (!importer) return null;
            if (!source.includes('fallback') && !source.includes('plugin-fragments')) return null;
            const resolved = await this.resolve(source, importer, { ...opts, skipSelf: true });
            if (!resolved) return null;
            if (matchesPath(resolved.id, FALLBACK_SRC)) return VIRTUAL_PAIR_FALLBACK;
            if (matchesPath(resolved.id, PLUGIN_FRAGMENTS_SRC)) return PLUGIN_FRAGMENTS_NOOP;
            return null;
        },
        async load(id) {
            if (id !== VIRTUAL_PAIR_FALLBACK) return null;
            const mod = (await import(pathToFileURL(EN_CATALOG_PATH).href)) as {
                default: Record<string, unknown>;
                intlLocale?: string;
            };
            const subset: Record<string, unknown> = {};
            for (const [k, v] of Object.entries(mod.default)) {
                if (k.startsWith('pair.')) subset[k] = v;
            }
            const intl = mod.intlLocale || 'en-US';
            return `
import { formatEntry } from ${JSON.stringify(FORMAT_PATH)};
const MESSAGES = ${JSON.stringify(subset)};
const INTL = ${JSON.stringify(intl)};
export const HAS_BUNDLED_CATALOG = false;
export function createFallbackI18n() {
    return {
        t(key, params) {
            if (typeof key !== 'string' || !key) return '';
            const entry = Object.prototype.hasOwnProperty.call(MESSAGES, key) ? MESSAGES[key] : undefined;
            if (entry === undefined) return key;
            const out = formatEntry(entry, params, INTL);
            return out === null ? key : out;
        },
        setLocale() { return false; },
        onLocaleChange() { return () => {}; },
        availableLocales() { return ['en']; },
        extendCatalog() { return 0; },
        get locale() { return 'en'; },
        get problems() { return []; },
    };
}
export function registerLocalFragment() { return 0; }
export function fallbackCatalogKeys() { return Object.keys(MESSAGES); }
`;
        },
    };
}
