import { CATALOGS, DEFAULT_LOCALE } from './catalogs.js';

export const STATIC_LABELS = Object.freeze([
    ['#session-sidebar-list', 'a11y.session_list'],
    ['#deep-link-error-dismiss', 'a11y.notice_dismiss'],
]);

export function langOf(locale) {
    const entry = CATALOGS[locale] || CATALOGS[DEFAULT_LOCALE];
    return entry.intl || DEFAULT_LOCALE;
}

export function applyDocumentLang(i18n, doc) {
    doc.documentElement.setAttribute('lang', langOf(i18n.locale));
    for (const [selector, key] of STATIC_LABELS) {
        const el = doc.querySelector(selector);
        if (el) el.setAttribute('aria-label', i18n.t(key));
    }
}

export function bindDocumentLang(i18n, doc) {
    applyDocumentLang(i18n, doc);
    i18n.onLocaleChange(() => applyDocumentLang(i18n, doc));
}
