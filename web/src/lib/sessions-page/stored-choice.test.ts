import { describe, expect, it } from 'vitest';
import type { Translate } from '../sessions/types';
import { workedWord } from './lenses';

const t: Translate = (key, params) => `${key}:${JSON.stringify(params ?? {})}`;

describe('workedWord', () => {
    it('speaks hours from an hour up and minutes (at least one) below', () => {
        expect(workedWord(7200, t)).toContain('group.worked:{"h":2}');
        expect(workedWord(10, t)).toContain('worked_min:{"m":1}');
    });
});
