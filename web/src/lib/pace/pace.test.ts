import { describe, expect, test } from 'vitest';
import {
    PACE_MIN_ELAPSED_PCT,
    elapsedPct,
    paceOf,
    paceState,
    windowLengthSeconds,
} from '../../../../client/js/labels/pace.js';

const NOW = Date.parse('2026-09-29T12:00:00Z');
const HOUR = 3_600_000;
const iso = (offsetMs: number): string => new Date(NOW + offsetMs).toISOString();

describe('windowLengthSeconds', () => {
    test('the server length wins, else the kind or label implies it', () => {
        expect(windowLengthSeconds({ kind: 'five_hour', window_seconds: 999 })).toBe(999);
        expect(windowLengthSeconds({ kind: 'five_hour' })).toBe(18_000);
        expect(windowLengthSeconds({ kind: 'seven_day_opus' })).toBe(604_800);
        expect(windowLengthSeconds({ kind: 'primary', label: '7d' })).toBe(604_800);
    });
    test('an unknown kind with no length is unknown, never guessed', () => {
        expect(windowLengthSeconds({ kind: 'primary', label: 'daily' })).toBeNull();
        expect(windowLengthSeconds(null)).toBeNull();
        expect(windowLengthSeconds({ kind: 'x', window_seconds: 0 })).toBeNull();
    });
});

describe('elapsedPct', () => {
    test('two hours to reset on a five hour window is 60 percent elapsed', () => {
        expect(elapsedPct({ kind: 'five_hour', resets_at: iso(2 * HOUR) }, NOW)).toBeCloseTo(60, 6);
    });
    test('just reset is about zero, and a reset further out than the window clamps to zero', () => {
        expect(elapsedPct({ kind: 'five_hour', resets_at: iso(5 * HOUR) }, NOW)).toBe(0);
        expect(elapsedPct({ kind: 'five_hour', resets_at: iso(9 * HOUR) }, NOW)).toBe(0);
    });
    test('an unknown, unparseable or already passed reset has no elapsed fraction', () => {
        expect(elapsedPct({ kind: 'five_hour', resets_at: null }, NOW)).toBeNull();
        expect(elapsedPct({ kind: 'five_hour' }, NOW)).toBeNull();
        expect(elapsedPct({ kind: 'five_hour', resets_at: 'soon' }, NOW)).toBeNull();
        expect(elapsedPct({ kind: 'five_hour', resets_at: iso(-HOUR) }, NOW)).toBeNull();
        expect(elapsedPct({ kind: 'primary', resets_at: iso(HOUR) }, NOW)).toBeNull();
    });
});

describe('paceState', () => {
    test('exactly on pace and under pace are on', () => {
        expect(paceState(60, 60)).toBe('on');
        expect(paceState(10, 60)).toBe('on');
    });
    test('ahead of pace but projecting under the overrun line is ahead', () => {
        expect(paceState(34, 32)).toBe('ahead');
        expect(paceState(59, 50)).toBe('ahead');
        expect(paceState(60, 50)).toBe('over');
    });
    test('projecting past the overrun line, or already at 100, is over', () => {
        expect(paceState(64, 32)).toBe('over');
        expect(paceState(100, 90)).toBe('over');
        expect(paceState(140, 90)).toBe('over');
    });
    test('a window younger than the minimum is never judged', () => {
        expect(paceState(3, PACE_MIN_ELAPSED_PCT - 1)).toBe('on');
    });
    test('unknown inputs give no state', () => {
        expect(paceState(null, 50)).toBeNull();
        expect(paceState(50, null)).toBeNull();
    });
});

describe('paceOf', () => {
    test('the usage step passes through unchanged whatever the pace (pace never colours the bar)', () => {
        const w = { kind: 'five_hour', used_pct: 64, resets_at: iso(3.4 * HOUR) };
        const p = paceOf(w, NOW, 3);
        expect(p.state).toBe('over');
        expect(p.scale).toBe(3);
        expect(paceOf(w, NOW, null).scale).toBeNull();
    });
    test('a five hour window 32 percent used, 60 percent elapsed, is on pace', () => {
        const w = { kind: 'five_hour', used_pct: 32, resets_at: iso(2 * HOUR) };
        const p = paceOf(w, NOW, 1);
        expect(p.state).toBe('on');
        expect(p.scale).toBe(1);
        expect(p.elapsedPct).toBeCloseTo(60, 6);
    });
    test('an unknown reset draws no pace and keeps the absolute colour', () => {
        const p = paceOf({ kind: 'five_hour', used_pct: 92, resets_at: null }, NOW, 5);
        expect(p).toEqual({ elapsedPct: null, state: null, scale: 5 });
    });
    test('over 100 percent is over', () => {
        expect(paceOf({ kind: 'seven_day', used_pct: 120, resets_at: iso(24 * HOUR) }, NOW, 5).state).toBe('over');
    });
    test('just reset with a little used stays on', () => {
        const w = { kind: 'five_hour', used_pct: 2, resets_at: iso(4.9 * HOUR) };
        expect(paceOf(w, NOW, 1).state).toBe('on');
    });
});
