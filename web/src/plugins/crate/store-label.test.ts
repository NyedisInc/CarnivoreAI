import { describe, expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { setLocale, t } from '../../lib/i18n/index.svelte';
import { registerFixturePlugin } from '../../lib/i18n/test-support/folder-plugin-fixture';
import { skipSentence } from './import-api';
import { storeLabel, unitLabel } from './store-label';

setLocale('en');
registerFixturePlugin();

describe('store labels', () => {
    test('a store with its own label reads that label, never the unit id', () => {
        expect(unitLabel('boardfix.boards', t)).toBe('fixture boards');
        expect(storeLabel('boardfix', 'boards', t)).toBe('fixture boards');
    });
    test('a store with no label of its own reads plugin name / data id, and an unknown plugin its id', () => {
        expect(unitLabel('boardfix.drafts', t)).toBe('board fixture / drafts');
        expect(unitLabel('nosuch.thing', t)).toBe('nosuch / thing');
    });
});

describe('skip sentences', () => {
    test('the plain reason and the "kept in the crate" list sentence are different keys with different words', () => {
        const plain = skipSentence('plugin_store_no_folder', t);
        const kept = skipSentence('plugin_store_no_folder', t, true);
        expect(plain).not.toBe(kept);
        expect(kept).toContain('the crate still holds them');
        expect(skipSentence('backups_not_chosen', t, true)).toBe(skipSentence('backups_not_chosen', t));
    });
});

describe('the crate catalog', () => {
    test('defines no key twice', () => {
        const source = readFileSync(resolve(__dirname, 'catalog.en.js'), 'utf8');
        const keys = [...source.matchAll(/^\s*'(cplug\.[^']+)':/gm)].map((m) => m[1]);
        const twice = keys.filter((k, i) => keys.indexOf(k) !== i);
        expect(twice).toEqual([]);
    });
});
