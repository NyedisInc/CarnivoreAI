import { describe, expect, test } from 'vitest';

import { headerControlsFor, headerPromptFor } from './prompt-header';

const at = (ordinal: number, line: number): { ordinal: number; line: number } => ({
    ordinal,
    line,
});

describe('the prompt above the viewport', () => {
    test('NEGATIVE: an empty list names nothing', () => {
        expect(headerPromptFor([], 500)).toBe(0);
    });

    test('a prompt scrolled above the viewport is the one named', () => {
        expect(headerPromptFor([at(1, 10)], 40)).toBe(1);
    });

    test('several above: the LAST one above wins, not the first', () => {
        expect(headerPromptFor([at(1, 10), at(2, 60), at(3, 120)], 200)).toBe(3);
        expect(headerPromptFor([at(1, 10), at(2, 60), at(3, 120)], 100)).toBe(2);
    });

    test('a prompt exactly on the top row is still the header', () => {
        expect(headerPromptFor([at(1, 40)], 40)).toBe(1);
    });

    test('after a jump, the viewport top lands on a prompt and the header shows it', () => {
        expect(headerPromptFor([at(1, 10), at(2, 60), at(3, 120)], 60)).toBe(2);
    });

    test('NEGATIVE: a prompt one line below the top is not shown', () => {
        expect(headerPromptFor([at(1, 41)], 40)).toBe(0);
    });

    test('NEGATIVE: every prompt below the viewport names nothing', () => {
        expect(headerPromptFor([at(1, 900), at(2, 950)], 100)).toBe(0);
    });

    test('at the bottom with the only prompt still visible, nothing is named', () => {
        expect(headerPromptFor([at(1, 980)], 976)).toBe(0);
    });

    test('the newest prompt being visible does not silence an OLDER one above', () => {
        expect(headerPromptFor([at(1, 10), at(2, 980)], 976)).toBe(1);
    });

    test('at the bottom with the newest prompt scrolled off, it IS named', () => {
        expect(headerPromptFor([at(1, 10), at(2, 900)], 976)).toBe(2);
    });

    test('NEGATIVE: a viewport reading that is not a number names nothing', () => {
        expect(headerPromptFor([at(1, 10)], Number.NaN)).toBe(0);
        expect(headerPromptFor([at(1, 10)], Number.POSITIVE_INFINITY)).toBe(0);
    });
});

describe('whether the header arrows have somewhere to go', () => {
    const ALPHA = at(1, 6);
    const BRAVO = at(2, 16);
    const CHARLIE = at(3, 69);
    const DELTA = at(4, 133);
    const RAIL = [ALPHA, BRAVO, CHARLIE, DELTA];
    const MAX_TOP = 98;

    test('NEGATIVE: at charlie, delta cannot reach the top row, so hasNext is false', () => {
        expect(headerControlsFor(RAIL, CHARLIE.ordinal, MAX_TOP)).toEqual({
            hasPrev: true,
            hasNext: false,
        });
    });

    test('at bravo, charlie can still reach the top row, so hasNext is true', () => {
        expect(headerControlsFor(RAIL, BRAVO.ordinal, MAX_TOP)).toEqual({
            hasPrev: true,
            hasNext: true,
        });
    });

    test('NEGATIVE: at alpha there is nothing before it, so hasPrev is false', () => {
        expect(headerControlsFor(RAIL, ALPHA.ordinal, MAX_TOP)).toEqual({
            hasPrev: false,
            hasNext: true,
        });
    });

    test('when the newest prompt is at or below max top, the one before it can reach it', () => {
        expect(headerControlsFor(RAIL, CHARLIE.ordinal, DELTA.line)).toEqual({
            hasPrev: true,
            hasNext: true,
        });
    });

    test('NEGATIVE: the newest prompt itself has nothing after it, whatever max top is', () => {
        expect(headerControlsFor(RAIL, DELTA.ordinal, 100000)).toEqual({
            hasPrev: true,
            hasNext: false,
        });
    });

    test('NEGATIVE: ordinal zero (no header) has nowhere to go either way', () => {
        expect(headerControlsFor(RAIL, 0, MAX_TOP)).toEqual({ hasPrev: false, hasNext: false });
    });

    test('NEGATIVE: an unreadable max top answers false rather than guessing', () => {
        expect(headerControlsFor(RAIL, BRAVO.ordinal, Number.NaN)).toEqual({
            hasPrev: true,
            hasNext: false,
        });
    });
});
