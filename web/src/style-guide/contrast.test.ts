import { describe, expect, it } from 'vitest';
import {
    AA_TEXT,
    EXTRA_PAIRS,
    GROUND_ROLES,
    TEXT_ROLES,
    contrastRatio,
    luminance,
    scopeVars,
    summarize,
    verdict,
    type Measured,
} from './contrast';

function row(over: Partial<Measured>): Measured {
    return { fg: '--a', bg: '--b', kind: 'text', resting: true, min: AA_TEXT, ratio: 7, verdict: 'pass', ...over };
}

describe('the WCAG formula', () => {
    it('gives the reference extremes and a known mid pair', () => {
        expect(luminance([0, 0, 0])).toBe(0);
        expect(luminance([255, 255, 255])).toBe(1);
        expect(contrastRatio([0, 0, 0], [255, 255, 255])).toBe(21);
        expect(contrastRatio([255, 255, 255], [0, 0, 0])).toBe(21);
        expect(contrastRatio([0x77, 0x77, 0x77], [255, 255, 255])).toBe(4.48);
        expect(contrastRatio([10, 20, 30], [10, 20, 30])).toBe(1);
    });
});

describe('verdicts', () => {
    it('flags text by AA, with the large-text band between 3 and 4.5', () => {
        expect(verdict(4.5, 'text', AA_TEXT)).toBe('pass');
        expect(verdict(4.49, 'text', AA_TEXT)).toBe('large');
        expect(verdict(2.99, 'text', AA_TEXT)).toBe('fail');
    });

    it('gives a boundary or a step no large-text band, and a decorative pair no floor', () => {
        expect(verdict(2.99, 'boundary', 3)).toBe('fail');
        expect(verdict(3, 'boundary', 3)).toBe('pass');
        expect(verdict(1.05, 'step', 1.1)).toBe('fail');
        expect(verdict(1.01, 'decorative', 0)).toBe('info');
    });
});

describe('the theme scope', () => {
    it('resets every name another theme sets, and keeps this theme its own values', () => {
        const vars = scopeVars({ '--color-fg': '#fff' }, ['--color-fg', '--color-bg-hover']);
        expect(vars).toEqual({ '--color-fg': '#fff', '--color-bg-hover': 'initial' });
    });

    it('carries a name only this theme sets', () => {
        expect(scopeVars({ '--color-x': 'red' }, [])).toEqual({ '--color-x': 'red' });
    });
});

describe('the per-theme tally', () => {
    it('counts large and fail as failures, splits resting from transient, and finds the worst by its own floor', () => {
        const rows = [
            row({ ratio: 4.1, verdict: 'large' }),
            row({ ratio: 2.5, verdict: 'fail', resting: false }),
            row({ kind: 'boundary', min: 3, ratio: 2.9, verdict: 'fail' }),
            row({ kind: 'decorative', min: 0, ratio: 1.2, verdict: 'info' }),
            row({ ratio: 9, verdict: 'pass' }),
        ];
        const s = summarize(rows);
        expect(s.failsAll).toBe(3);
        expect(s.failsResting).toBe(2);
        expect(s.measured).toBe(5);
        expect(s.worst?.ratio).toBe(2.5);
    });

    it('reports nothing failing for an all-pass theme', () => {
        expect(summarize([row({}), row({ ratio: 12 })])).toMatchObject({ failsAll: 0, failsResting: 0 });
    });
});

describe('the role data', () => {
    it('names nine text roles, eight grounds with the five base surfaces first, and only --oc- tokens', () => {
        expect(TEXT_ROLES).toHaveLength(9);
        expect(GROUND_ROLES.slice(0, 5).map((g) => g.token)).toEqual([
            '--oc-surface-sunken',
            '--oc-surface-base',
            '--oc-surface-band',
            '--oc-surface-raised',
            '--oc-surface-overlay',
        ]);
        const tokens = [...TEXT_ROLES, ...GROUND_ROLES, ...EXTRA_PAIRS.flatMap((p) => [p.fg, p.bg])].map((r) => r.token);
        expect(tokens.every((t) => t.startsWith('--oc-'))).toBe(true);
    });
});
