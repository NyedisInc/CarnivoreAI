import { describe, expect, test } from 'vitest';
import { formatUntil, msUntilReread } from './level-expiry';

describe('level-expiry', () => {
    test('formatUntil gives HH:MM and survives garbage', () => {
        expect(formatUntil('2026-10-17T14:30:00+00:00')).toMatch(/^\d\d:\d\d$/);
        expect(formatUntil('nope')).toBe('');
    });

    test('msUntilReread waits past the deadline and never goes negative', () => {
        const now = Date.parse('2026-10-17T14:00:00Z');
        expect(msUntilReread('2026-10-17T14:00:10Z', now)).toBe(11000);
        expect(msUntilReread('2026-10-17T13:00:00Z', now)).toBe(1000);
        expect(msUntilReread('nope', now)).toBeNull();
    });
});
