/** @vitest-environment jsdom */
import { describe, expect, test } from 'vitest';
import {
    createI18n,
    LOCALE_CHANGED_EVENT,
    CARNIVORE_LOCALE_CHANGED_EVENT,
} from '../../../../client/js/i18n/runtime.js';

interface I18nLike {
    setLocale(next: string): boolean;
}

describe('setLocale dispatches both the legacy and the new window event', () => {
    test('the event names are the exact literals the rename plan names', () => {
        expect(LOCALE_CHANGED_EVENT).toBe('cloude:locale-changed');
        expect(CARNIVORE_LOCALE_CHANGED_EVENT).toBe('carnivore:locale-changed');
    });

    test('both events fire, in order, with the same detail', () => {
        const seen: Array<{ type: string; locale: unknown }> = [];
        const onLegacy = (e: Event) =>
            seen.push({ type: LOCALE_CHANGED_EVENT, locale: (e as CustomEvent).detail.locale });
        const onNew = (e: Event) =>
            seen.push({
                type: CARNIVORE_LOCALE_CHANGED_EVENT,
                locale: (e as CustomEvent).detail.locale,
            });
        window.addEventListener(LOCALE_CHANGED_EVENT, onLegacy);
        window.addEventListener(CARNIVORE_LOCALE_CHANGED_EVENT, onNew);
        try {
            const i18n = createI18n({ locale: 'en' }) as I18nLike;
            expect(i18n.setLocale('pseudo')).toBe(true);
        } finally {
            window.removeEventListener(LOCALE_CHANGED_EVENT, onLegacy);
            window.removeEventListener(CARNIVORE_LOCALE_CHANGED_EVENT, onNew);
        }
        expect(seen).toEqual([
            { type: LOCALE_CHANGED_EVENT, locale: 'pseudo' },
            { type: CARNIVORE_LOCALE_CHANGED_EVENT, locale: 'pseudo' },
        ]);
    });

    test('a listener bound only to the new event name still hears every change', () => {
        let heard = 0;
        const onNew = () => {
            heard += 1;
        };
        window.addEventListener(CARNIVORE_LOCALE_CHANGED_EVENT, onNew);
        try {
            const i18n = createI18n({ locale: 'en' }) as I18nLike;
            i18n.setLocale('pseudo');
        } finally {
            window.removeEventListener(CARNIVORE_LOCALE_CHANGED_EVENT, onNew);
        }
        expect(heard).toBe(1);
    });

    test('setting the same locale again dispatches neither event', () => {
        const seen: string[] = [];
        const record = (e: Event) => seen.push(e.type);
        window.addEventListener(LOCALE_CHANGED_EVENT, record);
        window.addEventListener(CARNIVORE_LOCALE_CHANGED_EVENT, record);
        try {
            const i18n = createI18n({ locale: 'en' }) as I18nLike;
            expect(i18n.setLocale('en')).toBe(false);
        } finally {
            window.removeEventListener(LOCALE_CHANGED_EVENT, record);
            window.removeEventListener(CARNIVORE_LOCALE_CHANGED_EVENT, record);
        }
        expect(seen).toHaveLength(0);
    });
});
