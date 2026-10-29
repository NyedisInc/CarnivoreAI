import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Translate } from '../sessions/types';
import { workedWord } from './lenses';
import { readChoice, writeChoice } from './stored-choice';

const t: Translate = (key, params) => `${key}:${JSON.stringify(params ?? {})}`;

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

describe('workedWord', () => {
    it('speaks hours from an hour up and minutes (at least one) below', () => {
        expect(workedWord(7200, t)).toContain('group.worked:{"h":2}');
        expect(workedWord(10, t)).toContain('worked_min:{"m":1}');
    });
});
