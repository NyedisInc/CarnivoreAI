import { describe, expect, test } from 'vitest';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { i18n, t, setLocale, currentLocale } from './index.svelte';

describe('the svelte accessor', () => {
    test('translates through the same catalog the legacy tree reads', () => {
        expect(t('session.status.working')).toBe('working');
        expect(t('session.summary.sessions', { count: 2 })).toBe('2 sessions');
    });

    test('a locale change moves what t() answers', () => {
        expect(currentLocale()).toBe('en');
        expect(t('session.summary.none')).toBe('no sessions');
        expect(setLocale('pseudo')).toBe(true);
        expect(currentLocale()).toBe('pseudo');
        expect(t('session.summary.none')).not.toBe('no sessions');
        expect(t('session.summary.none')).toContain('no sessions');
        setLocale('en');
        expect(t('session.summary.none')).toBe('no sessions');
    });

    test('IT ADOPTS THE PAGE INSTANCE, it does not create a second one', () => {
        expect(typeof i18n.t).toBe('function');
        const other = createI18n({ locale: 'en' });
        expect(other).not.toBe(i18n);
        other.setLocale('pseudo');
        expect(currentLocale()).toBe('en');
    });
});
