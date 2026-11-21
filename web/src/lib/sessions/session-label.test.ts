import { describe, expect, test } from 'vitest';
import { derivedDisplayName } from './session-label';

describe('derivedDisplayName', () => {
    test('strips the canonical carnivore_ prefix', () => {
        expect(derivedDisplayName('carnivore_api')).toBe('api');
    });
    test('still strips the legacy cloude_ prefix', () => {
        expect(derivedDisplayName('cloude_api')).toBe('api');
    });
    test('leaves an external session name verbatim', () => {
        expect(derivedDisplayName('my-own-tmux')).toBe('my-own-tmux');
        expect(derivedDisplayName(null)).toBe('');
    });
});
