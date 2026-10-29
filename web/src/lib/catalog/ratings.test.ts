import { describe, expect, test } from 'vitest';

import {
    MAX_LOGIN_CHARS,
    MAX_REVIEWS,
    MAX_REVIEW_CHARS,
    histogramRows,
    ratingsView,
} from './ratings';

const FIVE = { '1': 0, '2': 0, '3': 0, '4': 1, '5': 1 };

describe('which of the shapes a ratings block is', () => {
    test('nothing read at all is `unavailable`, which is not a zero', () => {
        expect(ratingsView(null).shape).toBe('unavailable');
        expect(ratingsView(undefined).shape).toBe('unavailable');
    });

    test('a measured `count: 0` is `none`, and it is a REAL zero', () => {
        const view = ratingsView({ count: 0, average: 0, histogram: {}, reviews: [] });
        expect(view.shape).toBe('none');
        expect(view.count).toBe(0);
    });

    test('an average of 0 beside count 0 is NEVER offered as a score', () => {
        const view = ratingsView({ count: 0, average: 0, histogram: {}, reviews: [] });
        expect(view.average).toBeNull();
    });

    test('a real score IS offered when somebody has rated it', () => {
        const view = ratingsView({ count: 2, average: 4.5, histogram: FIVE, reviews: [] });
        expect(view.shape).toBe('rated');
        expect(view.average).toBe(4.5);
        expect(view.count).toBe(2);
    });

    test('a count that is not a number is `unavailable`, never 0', () => {
        expect(ratingsView({ count: 'lots' } as never).shape).toBe('unavailable');
        expect(ratingsView({ count: 'lots' } as never).count).toBeNull();
    });
});

describe('the histogram', () => {
    test('all five rows render even when four of them are zero', () => {
        const rows = histogramRows(FIVE, 2);
        expect(rows.map((row) => row.stars)).toEqual([5, 4, 3, 2, 1]);
    });

    test('it counts down from five, because that is how people read one', () => {
        expect(histogramRows(FIVE, 2)[0]?.stars).toBe(5);
    });

    test('a bucket the server omitted is a zero row, not a missing row', () => {
        const rows = histogramRows({ '5': 3 }, 3);
        expect(rows).toHaveLength(5);
        expect(rows.find((row) => row.stars === 1)?.count).toBe(0);
    });

    test('a percentage is of the total, and a total of zero is not a divide', () => {
        const rows = histogramRows(FIVE, 2);
        expect(rows.find((row) => row.stars === 5)?.percent).toBe(50);
        expect(histogramRows(FIVE, 0).every((row) => row.percent === 0)).toBe(true);
    });

    test('a bucket value that is not a number reads as zero rather than NaN', () => {
        const rows = histogramRows({ '5': 'three' } as never, 3);
        expect(rows.find((row) => row.stars === 5)?.count).toBe(0);
    });
});

describe('the texts other people wrote', () => {
    test('a review carries the login, the stars, the words and the time', () => {
        const view = ratingsView({
            count: 1,
            average: 5,
            histogram: FIVE,
            reviews: [
                { login: 'acme', stars: 5, text: 'great', updated_at: 1789000000 },
            ],
        });
        expect(view.texts).toEqual([
            {
                login: 'acme', stars: 5, text: 'great', updatedAt: 1789000000,
                author: null, publisher: false, reviewRef: null, reportedInstalling: false,
            },
        ]);
    });

    test('a runaway body is clipped and the cut is never silent', () => {
        const view = ratingsView({
            count: 1,
            average: 5,
            histogram: FIVE,
            reviews: [{ login: 'x', stars: 5, text: 'y'.repeat(5000) }],
        });
        const text = view.texts[0]?.text ?? '';
        expect(text.length).toBeLessThanOrEqual(MAX_REVIEW_CHARS);
        expect(text.endsWith('...')).toBe(true);
    });

    test('a runaway login is clipped too, because a handle is a stranger`s string', () => {
        const view = ratingsView({
            count: 1,
            average: 5,
            histogram: FIVE,
            reviews: [{ login: 'z'.repeat(400), stars: 5, text: 'ok' }],
        });
        expect((view.texts[0]?.login ?? '').length).toBeLessThanOrEqual(MAX_LOGIN_CHARS);
    });

    test('a runaway list is capped at the page the server says it sends', () => {
        const reviews = Array.from({ length: MAX_REVIEWS + 40 }, () => ({
            login: 'x',
            stars: 5,
            text: 'ok',
        }));
        expect(ratingsView({ count: 60, average: 5, histogram: FIVE, reviews }).texts)
            .toHaveLength(MAX_REVIEWS);
    });

    test('an ABSENT updated_at renders no date rather than the epoch', () => {
        const view = ratingsView({
            count: 1,
            average: 5,
            histogram: FIVE,
            reviews: [{ login: 'x', stars: 5, text: 'ok' }],
        });
        expect(view.texts[0]?.updatedAt).toBeNull();
    });

    test('a reviews value that is not a list is REPORTED, never coerced to empty', () => {
        const view = ratingsView({
            count: 2,
            average: 4.5,
            histogram: FIVE,
            reviews: 'lots',
        } as never);
        expect(view.textsMalformed).toBe(true);
        expect(view.texts).toEqual([]);
    });

    test('an OMITTED reviews key is also reported rather than read as none', () => {
        const view = ratingsView({ count: 2, average: 4.5, histogram: FIVE });
        expect(view.textsMalformed).toBe(true);
    });

    test('a real empty list is a MEASURED zero and is not malformed', () => {
        const view = ratingsView({ count: 2, average: 4.5, histogram: FIVE, reviews: [] });
        expect(view.textsMalformed).toBe(false);
        expect(view.texts).toEqual([]);
    });
});
