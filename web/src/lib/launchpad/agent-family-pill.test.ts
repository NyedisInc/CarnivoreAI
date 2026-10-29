import { describe, expect, test } from 'vitest';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { FAMILY_PILL_KEYS, familyPillView } from './agent-family-pill';

const i18n = createI18n({ locale: 'en' }) as {
    t(k: string, p?: Record<string, unknown> | null): string;
};
const t = (k: string, p?: Record<string, unknown> | null) => i18n.t(k, p);

describe('a FACT paints solid and names the family', () => {
    test.each(['wrapper', 'reserved_name'])('%s is a fact', (source) => {
        const view = familyPillView('codex', source);
        expect(view.kind).toBe('fact');
        expect(view.className).toBe('family-pill--fact');
        expect(view.label).toBe('codex');
        expect(t(view.titleKey, view.titleParams)).toContain('codex');
    });

    test('the source token rides on the element for the stylesheet', () => {
        expect(familyPillView('codex', 'wrapper').source).toBe('wrapper');
    });
});

describe('a GUESS paints dashed, and never as a fact', () => {
    test.each(['fingerprint', 'derived_deepest', 'inferred_process'])(
        '%s is a guess', (source) => {
            const view = familyPillView('claude', source);
            expect(view.kind).toBe('guess');
            expect(view.className).toBe('family-pill--guess');
            expect(view.label).toBe('claude');
        });

    test('a scrollback guess names the source in its hover', () => {
        const view = familyPillView('claude', 'fingerprint');
        expect(view.titleKey).toBe(FAMILY_PILL_KEYS.titleGuess);
        expect(t(view.titleKey, view.titleParams)).toContain('fingerprint');
    });

    test('`inferred_process` KEEPS ITS OWN SENTENCE, because the other is false', () => {
        const view = familyPillView('claude', 'inferred_process');
        expect(view.kind).toBe('guess');
        expect(view.titleKey).toBe(FAMILY_PILL_KEYS.titleInferredProcess);
        expect(t(view.titleKey)).toContain('process running in this pane');
    });

    test('a guess and a fact are VISIBLY different classes', () => {
        expect(familyPillView('claude', 'fingerprint').className)
            .not.toBe(familyPillView('claude', 'wrapper').className);
    });
});

describe('UNKNOWN is a third outcome, never a collapsed guess', () => {
    test('a null family renders the unknown LABEL, not a family name', () => {
        const view = familyPillView(null, 'wrapper');
        expect(view.kind).toBe('unknown');
        expect(view.label).toBeNull();
        expect(t(FAMILY_PILL_KEYS.unknownLabel)).toBe('unknown family');
    });

    test('an empty family is unknown too, not an empty pill', () => {
        expect(familyPillView('', 'wrapper').kind).toBe('unknown');
    });

    test('A NAME WITH AN `unknown` SOURCE IS STILL UNKNOWN', () => {
        const view = familyPillView('claude', 'unknown');
        expect(view.kind).toBe('unknown');
        expect(view.label).toBeNull();
    });

    test('a missing source defaults to `unknown` rather than to a fact', () => {
        expect(familyPillView('claude', null).kind).toBe('unknown');
        expect(familyPillView('claude', undefined).kind).toBe('unknown');
    });

    test('the unknown hover says what could not be determined', () => {
        const view = familyPillView(null, null);
        expect(t(view.titleKey)).toContain('could not determine');
    });

    test('an unrecognised source with a name is a FACT, not a guess', () => {
        expect(familyPillView('codex', 'some_new_source').kind).toBe('fact');
    });
});

describe('the pill is byte-compatible with the legacy builder it replaces', () => {
    function legacyVerdict(family: string | null, source: string | null) {
        const src = source || 'unknown';
        const isGuess = src === 'fingerprint' || src === 'derived_deepest'
            || src === 'inferred_process';
        const known = !!family && src !== 'unknown';
        return {
            label: known ? family : 'unknown family',
            kindClass: !known
                ? 'family-pill--unknown'
                : (isGuess ? 'family-pill--guess' : 'family-pill--fact'),
        };
    }

    const CASES: Array<[string | null, string | null]> = [
        ['codex', 'wrapper'],
        ['codex', 'reserved_name'],
        ['claude', 'fingerprint'],
        ['claude', 'derived_deepest'],
        ['claude', 'inferred_process'],
        ['claude', 'unknown'],
        [null, 'wrapper'],
        [null, null],
        ['', 'wrapper'],
        ['codex', 'some_new_source'],
    ];

    test.each(CASES)('family=%s source=%s agrees with the legacy rules', (family, source) => {
        const view = familyPillView(family, source);
        const legacy = legacyVerdict(family, source);
        expect(view.className).toBe(legacy.kindClass);
        expect(view.label ?? t(FAMILY_PILL_KEYS.unknownLabel)).toBe(legacy.label);
    });
});

describe('every key this pill asks for exists', () => {
    test.each(Object.values(FAMILY_PILL_KEYS))('%s is in the catalog', (key) => {
        expect(Object.prototype.hasOwnProperty.call(enCatalog, key), key).toBe(true);
    });
});
