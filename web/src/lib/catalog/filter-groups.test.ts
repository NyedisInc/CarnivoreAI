import { describe, expect, test } from 'vitest';

import { NO_FILTERS } from './filter';
import { pressOrClear, stateOf, withState } from './filter-groups';

describe('the state group', () => {
    test('any is no flag, and each value reads back what it set', () => {
        expect(stateOf(NO_FILTERS)).toBe('any');
        for (const value of ['installed', 'available', 'updates'] as const) {
            expect(stateOf(withState(NO_FILTERS, value))).toBe(value);
        }
    });

    test('choosing updates after installed leaves exactly updates set', () => {
        const next = withState(withState(NO_FILTERS, 'installed'), 'updates');
        expect(next.installed).toBe(false);
        expect(next.available).toBe(false);
        expect(next.updates).toBe(true);
    });

    test('any clears all three and touches no other filter', () => {
        const next = withState({ ...NO_FILTERS, updates: true, kind: 'skill', scripts: true }, 'any');
        expect([next.installed, next.available, next.updates]).toEqual([false, false, false]);
        expect(next.kind).toBe('skill');
        expect(next.scripts).toBe(true);
    });
});

describe('the phone press', () => {
    test('pressing the pressed segment again clears the group', () => {
        expect(pressOrClear('any', 'updates')).toBe('updates');
        expect(pressOrClear('updates', 'updates')).toBe('any');
        expect(pressOrClear('installed', 'updates')).toBe('updates');
    });
});
