import { describe, expect, test } from 'vitest';

import { t } from '../i18n/index.svelte';
import { countLabel, promptCountLabel } from './count-label';

const count = (state: Parameters<typeof countLabel>[0]): string => countLabel(state, t);
const promptCount = (state: Parameters<typeof promptCountLabel>[0]): string => promptCountLabel(state, t);

describe('what the counter says', () => {
    test('a history load in flight says so, whatever else is true', () => {
        expect(count({ history: 'pending', query: 'x', results: null })).toBe(
            'loading history...',
        );
    });

    test('an empty box says nothing, once the history is in', () => {
        expect(count({ history: 'painted', query: '', results: null })).toBe('');
        expect(count({ history: 'already', query: '', results: null })).toBe('');
    });

    test('an empty box after a FAILED history load says what it can see', () => {
        expect(count({ history: 'unavailable', query: '', results: null })).toBe(
            'searching recent output only',
        );
    });

    test('a real count reads "n of N", one-based', () => {
        expect(
            count({
                history: 'already',
                query: 'foo',
                results: { resultIndex: 2, resultCount: 9, limit: 1000 },
            }),
        ).toBe('3 of 9');
    });

    test('no index yet still counts from one rather than from zero', () => {
        expect(
            count({
                history: 'already',
                query: 'foo',
                results: { resultIndex: null, resultCount: 9, limit: 1000 },
            }),
        ).toBe('1 of 9');
    });

    test('zero matches is said out loud', () => {
        expect(
            count({ history: 'already', query: 'foo', results: { resultCount: 0 } }),
        ).toBe('no matches');
    });

    test('at the highlight cap the count is a floor, not a number', () => {
        expect(
            count({
                history: 'already',
                query: 'e',
                results: { resultIndex: 4, resultCount: 1000, limit: 1000 },
            }),
        ).toBe('1000+');
    });

    test('NEGATIVE: an uncounted result paints NOTHING, never "no matches"', () => {
        for (const results of [null, {}, { resultCount: null }, { resultCount: undefined }]) {
            expect(count({ history: 'already', query: 'foo', results })).toBe('');
        }
    });
});

describe('what the counter says while prompts-only is on', () => {
    test('an exact ordinal match reads "k of n prompts", one-based', () => {
        expect(
            promptCount({
                prompts: [
                    { ordinal: 1, matches: false },
                    { ordinal: 2, matches: true },
                    { ordinal: 3, matches: true },
                ],
                currentOrdinal: 3,
            }),
        ).toBe('2 of 2 prompts');
    });

    test('the first matching ordinal reads "1 of n"', () => {
        expect(
            promptCount({
                prompts: [
                    { ordinal: 2, matches: true },
                    { ordinal: 3, matches: true },
                ],
                currentOrdinal: 2,
            }),
        ).toBe('1 of 2 prompts');
    });

    test('no prompt matches the query at all', () => {
        expect(
            promptCount({
                prompts: [{ ordinal: 1, matches: false }],
                currentOrdinal: 0,
            }),
        ).toBe('no prompts match');
        expect(promptCount({ prompts: [], currentOrdinal: 0 })).toBe('no prompts match');
    });

    test('ABSENT IS NOT A NUMBER: landing between two matches, before the first step, reads 0', () => {
        expect(
            promptCount({
                prompts: [
                    { ordinal: 1, matches: false },
                    { ordinal: 2, matches: true },
                ],
                currentOrdinal: 1,
            }),
        ).toBe('0 of 1 prompts');
    });

    test('only the MATCHING prompts are counted, never the dimmed ones', () => {
        expect(
            promptCount({
                prompts: [
                    { ordinal: 1, matches: false },
                    { ordinal: 2, matches: true },
                    { ordinal: 3, matches: false },
                ],
                currentOrdinal: 2,
            }),
        ).toBe('1 of 1 prompts');
    });
});
