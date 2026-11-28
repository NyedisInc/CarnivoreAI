import { describe, expect, test } from 'vitest';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { headlineFromSummary, summarizeFlaggedWarnings } from './flagged-labels';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

describe('flagged-labels (#3402)', () => {
    test('headlineFromSummary extracts the first crisp sentence without mid-word cut', () => {
        const raw =
            'A Tier 0 declarative cplug that adds a Dr. Mario-style falling-pill puzzle game widget. It ships a large bundled, minified game engine with no permissions declared.';
        expect(headlineFromSummary(raw)).toBe(
            'A Tier 0 declarative cplug that adds a Dr. Mario-style falling-pill puzzle game widget.',
        );
    });

    test('summarizeFlaggedWarnings deduplicates structured warning kinds into plain-English chips', () => {
        const res = summarizeFlaggedWarnings(
            [
                { kind: 'opaque_payload', file: 'views/game/app.js', detail: 'Minified bundle cut off at review limit.' },
                { kind: 'opaque_payload', file: 'views/game/atlas-0.js', detail: 'Large atlas script.' },
                { kind: 'opaque_payload', file: 'views/game/atlas-1.js', detail: 'Second atlas script.' },
                { kind: 'obfuscation', file: 'views/game/app.js', detail: 'Minified build.' },
                { kind: 'other', file: 'views/game/app.js', detail: 'Partial coverage.' },
            ],
            [],
            t,
        );
        expect(res.chips).toEqual([
            { key: 'kind:opaque_payload', label: 'large / uninspected files', count: 3, tone: 'warn' },
            { key: 'kind:obfuscation', label: 'minified / bundled code', count: 1, tone: 'warn' },
            { key: 'kind:other', label: 'partial scan', count: 1, tone: 'neutral' },
        ]);
        expect(res.details).toHaveLength(5);
        expect(res.details[0]?.file).toBe('views/game/app.js');
    });

    test('summarizeFlaggedWarnings preserves free-form legacy reasons without losing text', () => {
        const res = summarizeFlaggedWarnings([], ['executes shell subprocesses'], t);
        expect(res.chips).toHaveLength(1);
        expect(res.chips[0]?.label).toBe('executes shell subprocesses');
    });
});
