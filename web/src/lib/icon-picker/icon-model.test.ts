import { describe, expect, test } from 'vitest';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { GLYPHS } from '../../../../client/js/icons/glyphs.js';
import { RETIRED_ICON_IDS, iconSvg } from '../../../../client/js/icons/icon-registry.js';
import type { Translate } from '../sessions/types';
import {
    ICON_PICKER_KEYS,
    PICKABLE_ICONS,
    PICKER_COLUMNS,
    filterIcons,
    iconValue,
    moveIndex,
    resolveIcon,
} from './icon-model';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);
const catalog = enCatalog as Record<string, unknown>;
const glyphs = GLYPHS as Record<string, Array<Record<string, string>>>;

describe('the registry', () => {
    test('every id is unique', () => {
        const ids = PICKABLE_ICONS.map((icon) => icon.id);
        expect(new Set(ids).size).toBe(ids.length);
        expect(ids.length).toBeGreaterThan(0);
    });

    test('every id is a plain lowercase slug, safe in any JSON document', () => {
        for (const icon of PICKABLE_ICONS) expect(icon.id).toMatch(/^[a-z][a-z0-9-]*$/);
    });

    test('every entry points at a glyph that exists', () => {
        for (const icon of PICKABLE_ICONS) expect(glyphs[icon.glyph], icon.id).toBeDefined();
    });

    test('every name and every picker word is in the catalog, lowercase', () => {
        const keys = [...PICKABLE_ICONS.map((icon) => icon.label), ...Object.values(ICON_PICKER_KEYS)];
        for (const key of keys) {
            expect(typeof catalog[key], key).toBe('string');
            expect(catalog[key]).toBe(String(catalog[key]).toLowerCase());
        }
    });

    test('no pickable glyph sets a colour: every stroke and fill is currentColor or none', () => {
        for (const icon of PICKABLE_ICONS) {
            for (const element of glyphs[icon.glyph] ?? []) {
                for (const attr of ['stroke', 'fill']) {
                    if (element[attr] !== undefined) {
                        expect(['currentColor', 'none'], `${icon.id} ${attr}`).toContain(element[attr]);
                    }
                }
            }
        }
    });

    test('action glyphs are never pickable', () => {
        const ids = PICKABLE_ICONS.map((icon) => icon.glyph);
        for (const action of ['trash', 'close', 'pencil', 'restart', 'archive', 'copy']) {
            expect(ids).not.toContain(action);
        }
    });

    test('a retired id maps to a live one', () => {
        for (const [, next] of Object.entries(RETIRED_ICON_IDS as Record<string, string>)) {
            expect(resolveIcon(next)).not.toBeNull();
        }
    });
});

describe('resolving a stored id', () => {
    test('a known id resolves to its entry', () => {
        expect(resolveIcon('folder')?.glyph).toBe('folder');
    });

    test('an unknown, empty or non-string id resolves to nothing, never a guess', () => {
        for (const bad of ['nope', '', null, undefined, 3, {}, 'FOLDER']) {
            expect(resolveIcon(bad)).toBeNull();
        }
    });

    test('the legacy renderer draws the same glyph, and nothing for an unknown id', () => {
        expect(iconSvg('folder', 12)).toContain('width="12"');
        expect(iconSvg('folder')).toContain('currentColor');
        expect(iconSvg('nope')).toBe('');
        expect(iconSvg(null)).toBe('');
    });

    test('iconValue keeps an unknown string (a newer build wrote it) and drops non-strings', () => {
        expect(iconValue('from-the-future')).toBe('from-the-future');
        expect(iconValue('')).toBeNull();
        expect(iconValue(7)).toBeNull();
        expect(iconValue(undefined)).toBeNull();
    });
});

describe('search', () => {
    test('a blank query shows everything, in registry order', () => {
        expect(filterIcons('  ', t)).toEqual(PICKABLE_ICONS);
    });

    test('matches the id, the translated name and the keywords, ignoring case', () => {
        expect(filterIcons('FOLD', t).map((icon) => icon.id)).toEqual(['folder', 'folder-tree']);
        expect(filterIcons('people', t).map((icon) => icon.id)).toEqual(['users']);
        expect(filterIcons('team', t).map((icon) => icon.id)).toEqual(['users']);
    });

    test('no match is an empty list', () => {
        expect(filterIcons('zzzz', t)).toEqual([]);
    });
});

describe('keyboard movement', () => {
    const count = 25;

    test('arrows move a cell and a row of PICKER_COLUMNS', () => {
        expect(PICKER_COLUMNS).toBe(8);
        expect(moveIndex(0, 'ArrowRight', count)).toBe(1);
        expect(moveIndex(1, 'ArrowLeft', count)).toBe(0);
        expect(moveIndex(0, 'ArrowDown', count)).toBe(8);
        expect(moveIndex(9, 'ArrowUp', count)).toBe(1);
    });

    test('edges clamp instead of wrapping', () => {
        expect(moveIndex(0, 'ArrowLeft', count)).toBe(0);
        expect(moveIndex(24, 'ArrowRight', count)).toBe(24);
        expect(moveIndex(3, 'ArrowUp', count)).toBe(3);
        expect(moveIndex(20, 'ArrowDown', count)).toBe(20);
    });

    test('Home and End jump; other keys and an empty grid answer null', () => {
        expect(moveIndex(12, 'Home', count)).toBe(0);
        expect(moveIndex(3, 'End', count)).toBe(24);
        expect(moveIndex(3, 'a', count)).toBeNull();
        expect(moveIndex(0, 'ArrowRight', 0)).toBeNull();
    });
});
