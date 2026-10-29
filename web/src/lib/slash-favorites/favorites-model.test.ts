import { describe, expect, test } from 'vitest';

import {
    FAVORITE_COLORS,
    indexAtPoint,
    isFavoriteColor,
    keyboardDelta,
    moveItem,
    rowFromPayload,
    sameOrder,
    swatchVar,
} from './favorites-model';

describe('the swatch set', () => {
    test('is the five palette token names the server accepts, never the accent', () => {
        expect([...FAVORITE_COLORS]).toEqual(['yellow', 'green', 'cyan', 'violet', 'coral']);
    });

    test('paints from the --oc token, never a literal colour', () => {
        for (const id of FAVORITE_COLORS) expect(swatchVar(id)).toBe(`var(--oc-${id})`);
    });

    test('refuses anything else, a hex included', () => {
        expect(isFavoriteColor('#ff0000')).toBe(false);
        expect(isFavoriteColor(null)).toBe(false);
        expect(isFavoriteColor('green')).toBe(true);
    });
});

describe('reading the server body', () => {
    test('carries each colour through', () => {
        const row = rowFromPayload({
            command_details: [
                { command: '/clear', description: 'wipe', color: 'green' },
                { command: '/diff', description: '', color: null },
            ],
            defaulted: false,
        });
        expect(row.favorites.map((f) => f.color)).toEqual(['green', null]);
        expect(row.defaulted).toBe(false);
    });

    test('a missing or unknown colour is no colour, never a guess', () => {
        const row = rowFromPayload({
            command_details: [{ command: '/a' }, { command: '/b', color: 'mauve' }],
        });
        expect(row.favorites.map((f) => f.color)).toEqual([null, null]);
        expect(row.defaulted).toBe(false);
    });

    test('a body that is not a row reads as an empty one', () => {
        expect(rowFromPayload(null)).toEqual({ favorites: [], defaulted: false });
    });
});

describe('moving', () => {
    test('moves an item forward and back', () => {
        expect(moveItem(['a', 'b', 'c'], 0, 2)).toEqual(['b', 'c', 'a']);
        expect(moveItem(['a', 'b', 'c'], 2, 0)).toEqual(['c', 'a', 'b']);
    });

    test('clamps and leaves the input alone', () => {
        const input = ['a', 'b'];
        expect(moveItem(input, 1, 9)).toEqual(['a', 'b']);
        expect(moveItem(input, 0, -3)).toEqual(['a', 'b']);
        expect(moveItem(input, 5, 0)).toEqual(['a', 'b']);
        expect(input).toEqual(['a', 'b']);
    });

    test('alt with an arrow is a move, a bare arrow is not', () => {
        expect(keyboardDelta('ArrowUp', true)).toBe(-1);
        expect(keyboardDelta('ArrowLeft', true)).toBe(-1);
        expect(keyboardDelta('ArrowDown', true)).toBe(1);
        expect(keyboardDelta('ArrowRight', true)).toBe(1);
        expect(keyboardDelta('ArrowDown', false)).toBe(0);
        expect(keyboardDelta('Enter', true)).toBe(0);
    });

    test('the hit test names the chip under the point, or the nearest', () => {
        const rects = [
            { left: 0, top: 0, right: 100, bottom: 50 },
            { left: 110, top: 0, right: 210, bottom: 50 },
        ];
        expect(indexAtPoint(rects, 150, 20)).toBe(1);
        expect(indexAtPoint(rects, 104, 20)).toBe(0);
        expect(indexAtPoint(rects, 300, 20)).toBe(1);
        expect(indexAtPoint([], 1, 1)).toBe(-1);
    });

    test('same order compares position by position', () => {
        expect(sameOrder(['/a', '/b'], ['/a', '/b'])).toBe(true);
        expect(sameOrder(['/a', '/b'], ['/b', '/a'])).toBe(false);
    });
});
