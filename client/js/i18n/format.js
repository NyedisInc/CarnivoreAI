
export const PLURAL_CATEGORIES = ['zero', 'one', 'two', 'few', 'many', 'other'];

export const COUNT_PARAM = 'count';

const pluralRulesCache = new Map();

const numberFormatCache = new Map();

const dateFormatCache = new Map();

export function pluralRulesFor(locale) {
    const key = typeof locale === 'string' && locale ? locale : 'en';
    let rules = pluralRulesCache.get(key);
    if (rules) return rules;
    try {
        rules = new Intl.PluralRules(key);
    } catch (err) {
        if (err instanceof RangeError) {
            console.error('[i18n] unusable locale tag for plurals:', key, err.message);
            rules = pluralRulesFor('en');
        } else {
            throw err;
        }
    }
    pluralRulesCache.set(key, rules);
    return rules;
}

export function numberFormatFor(locale) {
    const key = typeof locale === 'string' && locale ? locale : 'en';
    let fmt = numberFormatCache.get(key);
    if (fmt) return fmt;
    try {
        fmt = new Intl.NumberFormat(key);
    } catch (err) {
        if (err instanceof RangeError) {
            console.error('[i18n] unusable locale tag for numbers:', key, err.message);
            fmt = numberFormatFor('en');
        } else {
            throw err;
        }
    }
    numberFormatCache.set(key, fmt);
    return fmt;
}

export function dateFormatFor(locale) {
    const key = typeof locale === 'string' && locale ? locale : 'en';
    let fmt = dateFormatCache.get(key);
    if (fmt) return fmt;
    try {
        fmt = new Intl.DateTimeFormat(key, { dateStyle: 'medium' });
    } catch (err) {
        if (err instanceof RangeError) {
            console.error('[i18n] unusable locale tag for dates:', key, err.message);
            fmt = dateFormatFor('en');
        } else {
            throw err;
        }
    }
    dateFormatCache.set(key, fmt);
    return fmt;
}

/* could not */
export function selectForm(entry, params, locale, onProblem) {
    if (typeof entry === 'string') return entry;
    if (!entry || typeof entry !== 'object') return null;

    const p = params || {};
    const count = p[COUNT_PARAM];
    let category = 'other';
    if (typeof count === 'number' && Number.isFinite(count)) {
        category = pluralRulesFor(locale).select(count);
    } else if (onProblem) {
        onProblem('plural set used without a numeric `count` parameter');
    }

    const chosen = Object.prototype.hasOwnProperty.call(entry, category)
        ? entry[category]
        : entry.other;
    if (typeof chosen !== 'string') {
        if (onProblem) {
            onProblem('plural set has no `other` form');
        }
        return null;
    }
    return chosen;
}

export function interpolate(template, params, locale, onProblem) {
    if (typeof template !== 'string') return '';
    if (template.indexOf('{') === -1) return template;
    const p = params || {};
    return template.replace(/\{([A-Za-z_][A-Za-z0-9_]*)(\|date)?\}/g, (whole, name, kind) => {
        if (!Object.prototype.hasOwnProperty.call(p, name)) {
            if (onProblem) onProblem('no value for {' + name + '}');
            return whole;
        }
        const value = p[name];
        if (kind && typeof value === 'number' && Number.isFinite(value)) {
            return dateFormatFor(locale).format(new Date(value * 1000));
        }
        if (typeof value === 'number' && Number.isFinite(value)) {
            return numberFormatFor(locale).format(value);
        }
        if (value === null || value === undefined) {
            if (onProblem) onProblem('{' + name + '} is null or undefined');
            return whole;
        }
        return String(value);
    });
}

/* not usable */
export function formatEntry(entry, params, locale, onProblem) {
    const form = selectForm(entry, params, locale, onProblem);
    if (form === null) return null;
    return interpolate(form, params, locale, onProblem);
}
