import { expect, it } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { ELITE_KEYS as K } from '../../../../client/js/labels/warez-elite.js';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };

it('the tagged echo selects its form on count', () => {
    expect(i18n.t(K.echoTagged, { n: 1, count: 1 })).toBe('1 file tagged');
    expect(i18n.t(K.echoTagged, { n: 3, count: 3 })).toBe('3 files tagged');
});

it('the rating line selects its form on count', () => {
    expect(i18n.t(K.dizRating, { avg: '4.5', n: 1, count: 1 })).toBe('4.5 (1 rating)');
    expect(i18n.t(K.dizRating, { avg: '4.5', n: 7, count: 7 })).toBe('4.5 (7 ratings)');
});

it('the tagged total selects its form on count', () => {
    expect(i18n.t(K.taggedTotal, { size: '2 kb', n: 1, count: 1 })).toBe('total 2 kb in 1 file');
    expect(i18n.t(K.taggedTotal, { size: '2 kb', n: 2, count: 2 })).toBe('total 2 kb in 2 files');
});

it('the retired one/many keys are gone', () => {
    for (const k of ['echoTaggedOne', 'echoTaggedMany', 'dizRatingOne', 'taggedTotalOne']) {
        expect((K as Record<string, string>)[k]).toBeUndefined();
    }
});
