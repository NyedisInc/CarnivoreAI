import { CATALOGS, DEFAULT_LOCALE, availableLocales, registerFragment } from './catalogs.js';
import { formatEntry } from './format.js';
import { readMigrating, writeMigrating } from '../browser-storage-migrate.js';

export const LOCALE_STORAGE_KEY = 'carnivore.locale';

export const LOCALE_CHANGED_EVENT = 'cloude:locale-changed';
export const CARNIVORE_LOCALE_CHANGED_EVENT = 'carnivore:locale-changed';

export function storedLocale() {
    try {
        const raw = readMigrating(LOCALE_STORAGE_KEY);
        return raw || null;
    } catch (err) {
        console.debug('[i18n] locale override unreadable:', err && err.message);
        return null;
    }
}

export function matchLocale(preferred, available) {
    const list = Array.isArray(preferred) ? preferred : [];
    const have = new Map(
        (available || []).map((key) => [key.toLowerCase(), key]),
    );
    for (const raw of list) {
        if (typeof raw !== 'string' || !raw) continue;
        const tag = raw.toLowerCase();
        const exact = have.get(tag);
        if (exact) return exact;
        const base = tag.split('-')[0];
        const prefix = have.get(base);
        if (prefix) return prefix;
    }
    return null;
}

function navigatorLocales() {
    const nav = globalThis.navigator;
    if (!nav) return [];
    if (Array.isArray(nav.languages) && nav.languages.length) {
        return nav.languages.slice();
    }
    return typeof nav.language === 'string' && nav.language ? [nav.language] : [];
}

export function resolveLocale() {
    const keys = availableLocales();
    const override = storedLocale();
    if (override && Object.prototype.hasOwnProperty.call(CATALOGS, override)) {
        return override;
    }
    return matchLocale(navigatorLocales(), keys) || DEFAULT_LOCALE;
}

export function createI18n(options) {
    const opts = options || {};
    let locale =
        opts.locale && Object.prototype.hasOwnProperty.call(CATALOGS, opts.locale)
            ? opts.locale
            : resolveLocale();

    const reported = new Set();
    const listeners = new Set();

    function report(key, reason) {
        const seen = key + '::' + reason;
        if (reported.has(seen)) return;
        reported.add(seen);
        console.error('[i18n] ' + reason + ': ' + key + ' (locale ' + locale + ')');
    }

    function lookup(key) {
        const current = CATALOGS[locale];
        if (current && Object.prototype.hasOwnProperty.call(current.messages, key)) {
            return current.messages[key];
        }
        const fallback = CATALOGS[DEFAULT_LOCALE];
        if (
            fallback &&
            Object.prototype.hasOwnProperty.call(fallback.messages, key)
        ) {
            report(key, 'key missing from locale, using ' + DEFAULT_LOCALE);
            return fallback.messages[key];
        }
        return undefined;
    }

    function t(key, params) {
        if (typeof key !== 'string' || !key) {
            console.error('[i18n] t() called with a non-string key:', key);
            return '';
        }
        const entry = lookup(key);
        if (entry === undefined) {
            report(key, 'missing key');
            return key;
        }
        const intl = (CATALOGS[locale] || CATALOGS[DEFAULT_LOCALE]).intl;
        const out = formatEntry(entry, params, intl, (reason) => report(key, reason));
        if (out === null) {
            report(key, 'unusable catalog entry');
            return key;
        }
        return out;
    }

    function setLocale(next) {
        if (!Object.prototype.hasOwnProperty.call(CATALOGS, next)) {
            console.error('[i18n] no catalog for locale:', next);
            return false;
        }
        if (next === locale) return false;
        locale = next;
        reported.clear();
        try {
            writeMigrating(LOCALE_STORAGE_KEY, next);
        } catch (err) {
            console.debug('[i18n] locale choice not persisted:', err && err.message);
        }
        for (const fn of listeners) {
            try {
                fn(locale);
            } catch (err) {
                console.error('[i18n] locale listener threw:', err);
            }
        }
        if (globalThis.dispatchEvent && typeof CustomEvent === 'function') {
            globalThis.dispatchEvent(
                new CustomEvent(LOCALE_CHANGED_EVENT, { detail: { locale } }),
            );
            globalThis.dispatchEvent(
                new CustomEvent(CARNIVORE_LOCALE_CHANGED_EVENT, { detail: { locale } }),
            );
        }
        return true;
    }

    function onLocaleChange(fn) {
        if (typeof fn !== 'function') return () => {};
        listeners.add(fn);
        return () => listeners.delete(fn);
    }

    return {
        t,
        setLocale,
        onLocaleChange,
        availableLocales,
        extendCatalog: registerFragment,
        get locale() {
            return locale;
        },
        get problems() {
            return Array.from(reported);
        },
        catalogFor(key) {
            return CATALOGS[key];
        },
    };
}
