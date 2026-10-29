import { describe, expect, test } from 'vitest';

import { MAX_STARS, MIN_STARS } from './ratings';
import {
    MAX_RATING_TEXT,
    STAR_VALUES,
    canSubmit,
    clampText,
    rateBlocked,
    removedOf,
    yourStarsOf,
} from './rating-write';

describe('the stars a person can press', () => {
    test('there are five of them, counting up', () => {
        expect(STAR_VALUES).toEqual([1, 2, 3, 4, 5]);
    });

    test('they are exactly the range the hosted api validates', () => {
        expect(STAR_VALUES[0]).toBe(MIN_STARS);
        expect(STAR_VALUES[STAR_VALUES.length - 1]).toBe(MAX_STARS);
    });
});

describe('why the control cannot be used', () => {
    test('signed out is the one reason, and it is nameable', () => {
        expect(rateBlocked(false)).toBe('signed_out');
    });

    test('NEGATIVE CONTROL: signed in, nothing blocks it', () => {
        expect(rateBlocked(true)).toBeNull();
    });
});

describe('when the save button does something', () => {
    test('a signed in person who picked a star may submit', () => {
        expect(canSubmit(5, false, true)).toBe(true);
    });

    test('nothing picked yet means nothing to send', () => {
        expect(canSubmit(null, false, true)).toBe(false);
    });

    test('a write already in flight does not start a second one', () => {
        expect(canSubmit(5, true, true)).toBe(false);
    });

    test('signed out it is never submittable, whatever is picked', () => {
        expect(canSubmit(5, false, false)).toBe(false);
    });
});

describe('the words a person writes', () => {
    test('an ordinary note is sent unchanged', () => {
        expect(clampText('it reads well')).toBe('it reads well');
    });

    test('it is cut to the length the hosted sanitiser accepts', () => {
        expect(clampText('y'.repeat(5000)).length).toBe(MAX_RATING_TEXT);
    });

    test('surrounding whitespace is not a review', () => {
        expect(clampText('   ')).toBe('');
    });
});

describe('what the write answered', () => {
    test('the stars it recorded come back and are shown', () => {
        expect(yourStarsOf({ your_stars: 4 })).toBe(4);
    });

    test('an answer with no your_stars claims nothing', () => {
        expect(yourStarsOf({ count: 3 })).toBeNull();
        expect(yourStarsOf(null)).toBeNull();
    });

    test('a JSON true is not one star', () => {
        expect(yourStarsOf({ your_stars: true } as never)).toBeNull();
    });

    test('a removal says so, and only when the server said it removed one', () => {
        expect(removedOf({ removed: true })).toBe(true);
        expect(removedOf({ removed: false })).toBe(false);
    });

    test('an answer that said nothing about removal claims nothing', () => {
        expect(removedOf({ count: 2 })).toBeNull();
        expect(removedOf(null)).toBeNull();
    });
});
