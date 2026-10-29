import { describe, expect, test } from 'vitest';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import {
    CATALOG_KINDS,
    KIND_KEYS,
    bodyHeadingKey,
    kindKey,
    kindLabel,
} from '../../../../client/js/labels/catalog-kind.js';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

/** The catalog as a plain lookup, however the module exports it. */
const catalog = enCatalog as unknown as Record<string, unknown>;

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

describe('every key the kind layer names has a sentence', () => {
    test.each(Object.entries(KIND_KEYS))('%s -> %s exists', (_name, key) => {
        expect(catalog[key as string]).toBeDefined();
    });

    test('every kind the client knows has a name of its own', () => {
        for (const kind of CATALOG_KINDS) {
            const key = kindKey(kind);
            expect(key).not.toBe(null);
            expect(catalog[key as string]).toBeDefined();
        }
    });

    test('the refusal for a scope a kind does not have has a sentence', () => {
        expect(catalog['skill.refused.scope_not_supported']).toBeDefined();
    });
});

describe('an unknown kind is not named, and not invented', () => {
    test.each([['bundle'], ['workspace'], [''], ['   ']])(
        'kindKey(%s) is null',
        (kind) => {
            expect(kindKey(kind)).toBe(null);
        },
    );

    test.each([[null], [undefined], [42]])('kindKey of the non-string %s is null', (kind) => {
        expect(kindKey(kind as unknown as string)).toBe(null);
    });

    test('kindLabel answers null so the caller paints NO badge', () => {
        expect(kindLabel('bundle', t)).toBe(null);
        expect(kindLabel(null, t)).toBe(null);
    });

    test('a known kind is named in words', () => {
        expect(kindLabel('theme', t)).toBe('theme');
        expect(kindLabel('skill', t)).toBe('skill');
        expect(kindLabel('plugin', t)).toBe('plugin');
        expect(kindLabel('loadout', t)).toBe('loadout');
    });
});

describe('the consent document heading follows the KIND', () => {
    test('a theme is described as declaring, not as instructing', () => {
        const key = bodyHeadingKey('theme');
        expect(key).toBe(KIND_KEYS.themeBodyHeading);
        expect(catalog[key]).toBeDefined();
        expect(String(catalog[key])).not.toContain('agent');
    });

    test('a skill keeps its own wording', () => {
        const key = bodyHeadingKey('skill');
        expect(key).toBe('skill.sheet.body.heading');
        expect(catalog[key]).toBeDefined();
    });

    test('a plugin is described as the manifest it is loaded through', () => {
        const key = bodyHeadingKey('plugin');
        expect(key).toBe(KIND_KEYS.pluginBodyHeading);
        expect(catalog[key]).toBeDefined();
        expect(String(catalog[key])).toContain('plugin.json');
    });

    test('a loadout is described as a LIST, never as a thing itself', () => {
        const key = bodyHeadingKey('loadout');
        expect(key).toBe(KIND_KEYS.loadoutBodyHeading);
        expect(catalog[key]).toBeDefined();
        expect(String(catalog[key])).toContain('lists');
        expect(String(catalog[key])).toContain('loadout.json');
    });

    test.each([['bundle'], [''], [null], [undefined]])(
        'an unknown kind (%s) falls back to the skill wording, which exists',
        (kind) => {
            const key = bodyHeadingKey(kind as unknown as string);
            expect(key).toBe('skill.sheet.body.heading');
            expect(catalog[key]).toBeDefined();
        },
    );
});
