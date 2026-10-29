import { describe, expect, test } from 'vitest';
import {
    formatEntry,
    interpolate,
    numberFormatFor,
    pluralRulesFor,
    selectForm,
} from '../../../../client/js/i18n/format.js';

const SESSIONS = { one: '{count} session', other: '{count} sessions' };

describe('plural selection at the boundaries', () => {
    test('English CLDR categories are what we think they are', () => {
        const rules = pluralRulesFor('en');
        expect(rules.select(0)).toBe('other');
        expect(rules.select(1)).toBe('one');
        expect(rules.select(2)).toBe('other');
        expect(rules.select(19)).toBe('other');
    });

    test('0, 1, 2 and many resolve through the real plural set', () => {
        expect(formatEntry(SESSIONS, { count: 0 }, 'en')).toBe('0 sessions');
        expect(formatEntry(SESSIONS, { count: 1 }, 'en')).toBe('1 session');
        expect(formatEntry(SESSIONS, { count: 2 }, 'en')).toBe('2 sessions');
        expect(formatEntry(SESSIONS, { count: 19 }, 'en')).toBe('19 sessions');
    });

    test('a category the catalog does not carry falls back to `other`', () => {
        expect(pluralRulesFor('pl').select(2)).toBe('few');
        expect(formatEntry(SESSIONS, { count: 2 }, 'pl')).toBe('2 sessions');
    });

    test('a locale with more forms than English selects among them', () => {
        const russian = { one: 'a', few: 'b', many: 'c', other: 'd' };
        expect(selectForm(russian, { count: 1 }, 'ru')).toBe('a');
        expect(selectForm(russian, { count: 3 }, 'ru')).toBe('b');
        expect(selectForm(russian, { count: 5 }, 'ru')).toBe('c');
    });

    test('a plural set with no count reports and takes `other`', () => {
        const problems: string[] = [];
        expect(formatEntry(SESSIONS, {}, 'en', (r: string) => problems.push(r))).toBe(
            '{count} sessions',
        );
        expect(problems.join(' ')).toMatch(/count/);
    });

    test('an unusable locale tag degrades to English rather than throwing', () => {
        expect(() => pluralRulesFor('not a tag')).not.toThrow();
        expect(pluralRulesFor('not a tag').select(1)).toBe('one');
    });
});

describe('interpolation', () => {
    test('fills named holes', () => {
        expect(interpolate('{bucket} - {sessions}', { bucket: 'working', sessions: '2 sessions' }, 'en'))
            .toBe('working - 2 sessions');
    });

    test('numbers go through Intl.NumberFormat, so grouping is per locale', () => {
        expect(interpolate('{count}', { count: 1234 }, 'en')).toBe('1,234');
        expect(interpolate('{count}', { count: 1234 }, 'de')).toBe('1.234');
        expect(numberFormatFor('en').format(1234)).toBe('1,234');
    });

    test('a hole with no value is LEFT VERBATIM and reported', () => {
        const problems: string[] = [];
        expect(interpolate('{a} and {b}', { a: 'x' }, 'en', (r: string) => problems.push(r)))
            .toBe('x and {b}');
        expect(problems).toHaveLength(1);
        expect(problems[0]).toContain('{b}');
    });

    test('nothing is escaped here, because the result is text', () => {
        expect(interpolate('{x}', { x: '<b>&' }, 'en')).toBe('<b>&');
    });

    test('a template with no holes is returned untouched', () => {
        expect(interpolate('working', null, 'en')).toBe('working');
    });
});

describe('NEGATIVE CONTROL: the formatter can refuse', () => {
    test('a plural set with no `other` form is unusable, not silently empty', () => {
        expect(formatEntry({ one: 'x' }, { count: 2 }, 'en')).toBeNull();
    });

    test('a non-entry is unusable', () => {
        expect(formatEntry(undefined, null, 'en')).toBeNull();
        expect(formatEntry(42 as unknown as string, null, 'en')).toBeNull();
    });
});

describe('the {name|date} hole', () => {
    test('epoch seconds paint as a locale date, never as a grouped integer', () => {
        const out = formatEntry('updated {when|date}', { when: 1790993383 }, 'en');
        expect(out).toMatch(/^updated Oct [23], 2026$/);
        expect(out).not.toContain('1,790,993,383');
    });

    test('a bare number hole still groups digits (it is a quantity)', () => {
        expect(formatEntry('{n}', { n: 1790993383 }, 'en')).toBe('1,790,993,383');
    });
});
