import { describe, expect, it } from 'vitest';
import { AWAY_THRESHOLD, initialAway, nextAway } from '../../../../client/js/scroll-away.js';

const base = { max: 900, rowsH: 88, focusInside: false };
const at = (state: { away: boolean; anchor: number }, top: number, extra: Partial<typeof base> = {}) => nextAway(state, { ...base, ...extra, top });

describe('nextAway', () => {
    it('shows the rows at rest and at the top', () => {
        expect(initialAway().away).toBe(false);
        expect(at({ away: true, anchor: 300 }, 0).away).toBe(false);
    });

    it('hides after scrolling down past the rows and the threshold, not before', () => {
        expect(at(initialAway(), 10).away).toBe(false);
        expect(at(initialAway(), 40).away).toBe(false);
        expect(at(initialAway(), 300).away).toBe(true);
    });

    it('comes back after scrolling up by the threshold, and not for jitter', () => {
        const away = { away: true, anchor: 300 };
        expect(at(away, 300 - AWAY_THRESHOLD + 1).away).toBe(true);
        expect(at(away, 300 - AWAY_THRESHOLD).away).toBe(false);
    });

    it('follows the furthest point down while away, so a small bounce back does not show them', () => {
        const down = at({ away: true, anchor: 300 }, 400);
        expect(down.anchor).toBe(400);
        expect(at(down, 390).away).toBe(true);
    });

    it('never hides while focus is inside the rows, and shows them when it lands there', () => {
        expect(at(initialAway(), 300, { focusInside: true }).away).toBe(false);
        expect(at({ away: true, anchor: 300 }, 320, { focusInside: true }).away).toBe(false);
    });

    it('never hides content that overflows by no more than the rows own height', () => {
        expect(at(initialAway(), 88, { max: 88 }).away).toBe(false);
        expect(at(initialAway(), 30, { max: 30 }).away).toBe(false);
        expect(at(initialAway(), 90, { max: 100 }).away).toBe(true);
    });

    it('ignores positions outside the real scroll range (iOS overscroll bounce)', () => {
        const away = { away: true, anchor: 300 };
        expect(at(away, -20)).toBe(away);
        expect(at(away, 960)).toBe(away);
        const shown = initialAway();
        expect(at(shown, 960)).toBe(shown);
    });

    it('does nothing without rows', () => {
        expect(at(initialAway(), 300, { rowsH: 0 }).away).toBe(false);
    });
});
