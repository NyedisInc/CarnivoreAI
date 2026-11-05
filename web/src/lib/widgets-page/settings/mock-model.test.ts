import { describe, expect, test } from 'vitest';

import { resolveBars } from '../../widget-bars/bar-settings.svelte';
import { MIN_SCALE, STAGE_W, counterScale, dockedPx, editCaption, mockKeys, mockScale } from './mock-model';

const t = (key: string): string => key;

describe('mock-model', () => {
    test('the stage shrinks to the band width, never grows past 1, and never collapses', () => {
        expect(mockScale(STAGE_W / 2)).toBe(0.5);
        expect(mockScale(STAGE_W * 3)).toBe(1);
        expect(mockScale(10)).toBe(MIN_SCALE);
        expect(mockScale(0)).toBe(1);
    });

    test('a hairline or inset multiplied by the counter-scale renders at its design size at every width', () => {
        for (const width of [320, 390, 640, 1280, 1600]) {
            const k = mockScale(width);
            expect(1 * counterScale(k) * k).toBeCloseTo(1, 10);
            expect(4 * counterScale(k) * k).toBeCloseTo(4, 10);
        }
    });

    test('a bar\'s keys are the drawable placements in order, by their catalog title and key; an id this build cannot draw is left out', () => {
        const keys = mockKeys([{ widget: 'core.notes', look: null }, { widget: 'nobody.knows', look: null }, { widget: 'core.files', look: null }], t);
        expect(keys.map((one) => one.key)).toEqual(['core.notes', 'core.files']);
        expect(keys[0]?.title).not.toBe('');
        expect(keys[0]?.icon).not.toBe('');
    });

    test('a docked bar takes its real thickness, and nothing while hidden', () => {
        expect(dockedPx('side', resolveBars({ v: 1, side: { size: 'detailed' } }))).toBe(68);
        expect(dockedPx('bottom', resolveBars({ v: 1, bottom: { size: 'compact' } }))).toBe(20);
        expect(dockedPx('bottom', resolveBars({ v: 1, bottom: { show: false } }))).toBe(0);
    });

    test('the caption names the items, or says hidden, or empty; hidden wins over a bar that still holds keys', () => {
        const keys = mockKeys([{ widget: 'core.notes', look: null }], t);
        expect(editCaption(true, keys)).toEqual({ kind: 'items', names: keys[0]?.title });
        expect(editCaption(true, [])).toEqual({ kind: 'empty' });
        expect(editCaption(false, keys)).toEqual({ kind: 'hidden' });
    });
});
