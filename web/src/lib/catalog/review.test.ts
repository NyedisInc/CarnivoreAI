import { describe, expect, test } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { reviewLabel, reviewKindLabel } from '../../../../client/js/labels/skill.js';
import { MAX_WARNINGS, reviewView } from './review';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

describe('which of the four shapes a review block is', () => {
    test('no block at all is `absent`, which is not a review that came back empty', () => {
        expect(reviewView(null).shape).toBe('absent');
        expect(reviewView(undefined).shape).toBe('absent');
    });

    test('`unavailable` means the review did not run', () => {
        const view = reviewView({ status: 'unavailable' });
        expect(view.shape).toBe('unavailable');
        expect(view.warnings).toEqual([]);
    });

    test('`reviewed` with warnings keeps every one of them', () => {
        const view = reviewView({
            status: 'reviewed',
            summary: 'it reads a file',
            warnings: [{ kind: 'network', detail: 'calls out' }, { kind: 'file_delete' }],
        });
        expect(view.shape).toBe('reviewed');
        expect(view.summary).toBe('it reads a file');
        expect(view.warnings).toEqual([
            { kind: 'network', detail: 'calls out', file: null, line: null },
            { kind: 'file_delete', detail: null, file: null, line: null },
        ]);
    });

    test('`reviewed` with an empty list is a MEASURED zero', () => {
        const view = reviewView({ status: 'reviewed', warnings: [] });
        expect(view.shape).toBe('reviewed');
        expect(view.warnings).toEqual([]);
        expect(view.malformed).toBe(false);
    });

    test('a status this build has never heard of is `unavailable`, never `reviewed`', () => {
        expect(reviewView({ status: 'something_new' } as never).shape).toBe('unavailable');
    });

    test('a warnings field that is not a list is MALFORMED, not a measured zero', () => {
        const view = reviewView({ status: 'reviewed', warnings: 'lots' } as never);
        expect(view.malformed).toBe(true);
        expect(view.warnings).toEqual([]);
    });

    test('warnings beside `unavailable` are dropped: the block contradicts itself', () => {
        const view = reviewView({ status: 'unavailable', warnings: [{ kind: 'network' }] });
        expect(view.warnings).toEqual([]);
    });
});

describe('the index is somebody else`s file, so everything is bounded', () => {
    test('a runaway warning list is capped and the cap is the whole point', () => {
        const warnings = Array.from({ length: MAX_WARNINGS + 25 }, () => ({ kind: 'other' }));
        expect(reviewView({ status: 'reviewed', warnings }).warnings).toHaveLength(MAX_WARNINGS);
    });

    test('a runaway detail is clipped and the cut is never silent', () => {
        const view = reviewView({
            status: 'reviewed',
            warnings: [{ kind: 'other', detail: 'x'.repeat(5000) }],
        });
        const detail = view.warnings[0]?.detail ?? '';
        expect(detail.length).toBeLessThanOrEqual(500);
        expect(detail.endsWith('...')).toBe(true);
    });

    test('whitespace-only is absent, because a summary of spaces is not a summary', () => {
        expect(reviewView({ status: 'reviewed', summary: '   ' }).summary).toBeNull();
    });
});

describe('what the reader is actually told', () => {
    test('a review that did not run says "no ai review"', () => {
        expect(reviewLabel('unavailable', t)).toBe('no ai review');
    });

    test('and it NEVER says anything about what was or was not detected', () => {
        const said = String(reviewLabel('unavailable', t)).toLowerCase();
        expect(said).not.toContain('detected');
        expect(said).not.toContain('nothing');
        expect(said).not.toContain('clean');
        expect(said).not.toContain('safe');
    });

    test('a review that DID run is called something different', () => {
        expect(reviewLabel('reviewed', t)).toBe('ai reviewed');
        expect(reviewLabel('reviewed', t)).not.toBe(reviewLabel('unavailable', t));
    });

    test('an absent block is rendered by NOTHING here: the caller says so', () => {
        expect(reviewLabel(null, t)).toBeNull();
    });

    test('each of the seven kinds reads as what it MEANS', () => {
        expect(reviewKindLabel('network', t)).toBe('reaches the network');
        expect(reviewKindLabel('credential_access', t)).toBe('reads credentials');
        expect(reviewKindLabel('shell_exec', t)).toBe('runs shell commands');
    });

    test('a kind from a newer index is printed CARRYING ITS OWN TOKEN', () => {
        const said = reviewKindLabel('quantum_mischief', t);
        expect(said).toContain('quantum_mischief');
        expect(said).not.toBe('');
    });

    test('a kind that is missing entirely still renders something', () => {
        expect(reviewKindLabel(null, t).length).toBeGreaterThan(0);
    });
});
