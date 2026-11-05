import { describe, expect, test } from 'vitest';
import { BAR_DEFAULTS, resolveBars } from '../../widget-bars/bar-settings.svelte';
import { SHOW_CHOICES, showChoice, showOps, undoOps, type BarOp } from './settings-model';

describe('showChoice', () => {
    test('reads the four combinations off the resolved view', () => {
        expect(showChoice(BAR_DEFAULTS)).toBe('both');
        expect(showChoice(resolveBars({ v: 1, bottom: { show: false } }))).toBe('side');
        expect(showChoice(resolveBars({ v: 1, side: { show: false } }))).toBe('bottom');
        expect(showChoice(resolveBars({ v: 1, side: { show: false }, bottom: { show: false } }))).toBe('none');
    });
    test('offers exactly those four, both first', () => {
        expect(SHOW_CHOICES).toEqual(['both', 'side', 'bottom', 'none']);
    });
});

describe('showOps', () => {
    test('writes only the bars whose value changes', () => {
        expect(showOps('bottom', BAR_DEFAULTS)).toEqual([{ kind: 'bar', edge: 'side', patch: { show: false } }]);
        expect(showOps('both', BAR_DEFAULTS)).toEqual([]);
        expect(showOps('none', BAR_DEFAULTS)).toHaveLength(2);
    });
});

describe('undoOps', () => {
    test('puts back the prior leaf, and null where the leaf was absent so a default stays a default', () => {
        const stored = { v: 1 as const, side: { size: 'compact' as const } };
        const ops: BarOp[] = [
            { kind: 'bar', edge: 'side', patch: { size: 'detailed' } },
            { kind: 'bar', edge: 'bottom', patch: { show: false } },
            { kind: 'together', value: 'one' },
        ];
        expect(undoOps(stored, ops)).toEqual([
            { kind: 'bar', edge: 'side', patch: { size: 'compact' } },
            { kind: 'bar', edge: 'bottom', patch: { show: null } },
            { kind: 'together', value: null },
        ]);
    });
});
