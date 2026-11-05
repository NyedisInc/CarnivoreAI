import { afterEach, describe, expect, it, vi } from 'vitest';
import { readChoice, writeChoice } from './stored-choice';

function memoryStorage(): Pick<Storage, 'getItem' | 'setItem'> {
    const kept = new Map<string, string>();
    return { getItem: (k) => kept.get(k) ?? null, setItem: (k, v) => void kept.set(k, v) };
}

afterEach(() => vi.unstubAllGlobals());

describe('readChoice and writeChoice', () => {
    it('keeps an allowed value and falls back on junk', () => {
        vi.stubGlobal('localStorage', memoryStorage());
        writeChoice('k', 'pivot');
        expect(readChoice('k', ['list', 'pivot'] as const, 'list')).toBe('pivot');
        writeChoice('k', 'cards');
        expect(readChoice('k', ['list', 'pivot'] as const, 'list')).toBe('list');
    });
    it('survives a storage that refuses', () => {
        vi.stubGlobal('localStorage', {
            getItem: () => { throw new Error('blocked'); },
            setItem: () => { throw new Error('blocked'); },
        });
        expect(readChoice('k', ['a'] as const, 'a')).toBe('a');
        expect(() => writeChoice('k', 'a')).not.toThrow();
    });
});
