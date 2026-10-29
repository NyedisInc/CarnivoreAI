/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FUZZY_PREF_KEY, readFuzzyPref, writeFuzzyPref } from './fuzzy-pref';

afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
});

describe('the changelog fuzzy checkbox memory', () => {
    it('starts off and remembers the last choice', () => {
        expect(readFuzzyPref()).toBe(false);
        writeFuzzyPref(true);
        expect(localStorage.getItem(FUZZY_PREF_KEY)).toBe('1');
        expect(readFuzzyPref()).toBe(true);
        writeFuzzyPref(false);
        expect(readFuzzyPref()).toBe(false);
    });

    it('blocked storage reads as off and a refused write does not throw', () => {
        vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
        expect(readFuzzyPref()).toBe(false);
        expect(() => writeFuzzyPref(true)).not.toThrow();
    });
});
