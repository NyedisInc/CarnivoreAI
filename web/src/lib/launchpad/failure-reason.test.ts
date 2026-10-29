import { describe, expect, it } from 'vitest';
import { reasonOf } from './failure-reason';

const t = (key: string): string => `<${key}>`;

describe('launchpad reasonOf', () => {
    it('uses the error message, a string, or the unreachable key', () => {
        expect(reasonOf(new Error('gone'), t)).toBe('gone');
        expect(reasonOf('plain', t)).toBe('plain');
        expect(reasonOf(new Error(''), t)).toBe('<error.server_unreachable>');
        expect(reasonOf(undefined, t)).toBe('<error.server_unreachable>');
    });
});
