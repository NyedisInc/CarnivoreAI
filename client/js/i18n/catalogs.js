import en, { intlLocale as enIntlLocale } from './catalog.en.js';
import { pseudoCatalog, PSEUDO_LOCALE } from './pseudo.js';

export const DEFAULT_LOCALE = 'en';

export const CATALOGS = {
    en: { messages: en, intl: enIntlLocale },
    [PSEUDO_LOCALE]: {
        messages: pseudoCatalog(en),
        intl: enIntlLocale,
    },
};

export function availableLocales() {
    return Object.keys(CATALOGS);
}

export function registerFragment(pluginId, messages) {
    const prefix = 'cplug.' + pluginId + '.';
    const base = CATALOGS[DEFAULT_LOCALE].messages;
    const fresh = {};
    for (const key of Object.keys(messages || {})) {
        if (!key.startsWith(prefix)) {
            throw new Error('[i18n] ' + pluginId + ' plugin slice carries a key outside ' + prefix + ': ' + key);
        }
        if (Object.prototype.hasOwnProperty.call(base, key)) {
            if (JSON.stringify(base[key]) !== JSON.stringify(messages[key])) {
                throw new Error('[i18n] ' + pluginId + ' plugin slice redefines an existing key: ' + key);
            }
            continue;
        }
        fresh[key] = messages[key];
    }
    Object.assign(base, fresh);
    Object.assign(CATALOGS[PSEUDO_LOCALE].messages, pseudoCatalog(fresh));
    return Object.keys(fresh).length;
}
