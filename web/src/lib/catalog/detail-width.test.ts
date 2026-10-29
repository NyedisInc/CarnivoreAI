/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import {
    DETAIL_DEFAULT_WIDTH,
    DETAIL_MAX_WIDTH,
    DETAIL_MIN_WIDTH,
    DETAIL_WIDTH_KEY,
    clampDetailWidth,
    defaultDetailWidth,
    readDetailWidth,
    writeDetailWidth,
} from './detail-width';

afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
});

describe('the catalog detail drawer width', () => {
    test('opens at the default, narrower than half a desktop', () => {
        expect(readDetailWidth()).toBe(DETAIL_DEFAULT_WIDTH);
        expect(DETAIL_DEFAULT_WIDTH).toBe(400);
    });

    test('opens at 440 once the container is 1600px or wider', () => {
        expect(defaultDetailWidth(1599)).toBe(400);
        expect(defaultDetailWidth(1600)).toBe(440);
        expect(readDetailWidth(1700)).toBe(440);
    });

    test('clamps to the minimum, the maximum and the room the list keeps', () => {
        expect(clampDetailWidth(10, 1400)).toBe(DETAIL_MIN_WIDTH);
        expect(clampDetailWidth(9000, 2000)).toBe(DETAIL_MAX_WIDTH);
        expect(clampDetailWidth(700, 900)).toBe(620);
        expect(clampDetailWidth(NaN, 1400)).toBe(DETAIL_DEFAULT_WIDTH);
    });

    test('remembers a written width, and clamps a stored one on read', () => {
        writeDetailWidth(512);
        expect(window.localStorage.getItem(DETAIL_WIDTH_KEY)).toBe('512');
        expect(readDetailWidth()).toBe(512);
        window.localStorage.setItem(DETAIL_WIDTH_KEY, '5000');
        expect(readDetailWidth(1000)).toBe(640);
        window.localStorage.setItem(DETAIL_WIDTH_KEY, 'junk');
        expect(readDetailWidth()).toBe(DETAIL_DEFAULT_WIDTH);
    });

    test('works when storage throws', () => {
        vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied'); });
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied'); });
        expect(readDetailWidth()).toBe(DETAIL_DEFAULT_WIDTH);
        expect(() => writeDetailWidth(500)).not.toThrow();
    });
});
