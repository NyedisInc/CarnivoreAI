import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';
import CATALOG from '../../../../client/js/i18n/catalog.en.js';
import {
    cleanRoomSkipExpected,
    cleanRoomSkipped,
    emptyKey,
    folderPhrase,
    foundByFact,
    kindWord,
    realKind,
    tabOf,
    type KindTab,
} from './kinds';

const TABS: KindTab[] = ['skills', 'themes', 'mods', 'plugins'];
const REPORT = (verdict: string, code: string) => ({ gates: [{ id: 'clean_room', verdict, code }] });

describe('kinds', () => {
    test('every location kind maps to its tab, both plugin kinds to plugins with the real kind kept', () => {
        expect(['skill', 'theme', 'mod', 'plugin', 'cplug'].map((k) => tabOf(k))).toEqual([
            'skills', 'themes', 'mods', 'plugins', 'plugins',
        ]);
        expect(tabOf(undefined)).toBe('skills');
        expect(tabOf('nonsense')).toBeNull();
        expect(tabOf('')).toBe('skills');
        expect(realKind({ kind: 'cplug' })).toBe('cplug');
        expect(realKind({ kind: 'plugin' })).toBe('plugin');
        expect(realKind({})).toBe('skill');
    });

    test('the skip mention is expected for cplug only and read from the report otherwise', () => {
        expect(cleanRoomSkipExpected({ kind: 'cplug' })).toBe(true);
        for (const kind of ['plugin', 'mod', 'skill', 'theme']) expect(cleanRoomSkipExpected({ kind })).toBe(false);
        expect(cleanRoomSkipped(REPORT('advisory', 'skipped_by_policy'))).toBe(true);
        expect(cleanRoomSkipped(REPORT('fail', 'secret_found'))).toBe(false);
        expect(cleanRoomSkipped(REPORT('advisory', 'other'))).toBe(false);
        expect(cleanRoomSkipped({ gates: [{ id: 'license', verdict: 'advisory', code: 'skipped_by_policy' }] })).toBe(false);
        expect(cleanRoomSkipped(null)).toBe(false);
    });

    test('found by shows on the plugins tab only', () => {
        expect(foundByFact({ kind: 'plugin' })).not.toBeNull();
        expect(foundByFact({ kind: 'cplug' })).not.toBeNull();
        for (const kind of ['skill', 'theme', 'mod']) expect(foundByFact({ kind })).toBeNull();
    });

    test('every key returned exists in the catalog and is never a cplug key', () => {
        const keys = [
            ...['skill', 'theme', 'mod', 'plugin', 'cplug'].map(kindWord),
            ...TABS.flatMap((tab) => [folderPhrase(tab), emptyKey(tab)]),
            ...Object.values(foundByFact({ kind: 'plugin' })!),
        ];
        for (const key of keys) {
            expect((CATALOG as Record<string, unknown>)[key], key).toBeTypeOf('string');
            expect(key).not.toBe('skill.publish.kind.cplug');
            expect(key).not.toBe('catalog.kind.cplug');
        }
        expect(kindWord('cplug')).toBe('skill.publish.kind.plugin');
        expect(emptyKey('plugins')).toBe('skill.publish.kind.none_plugin');
    });

    test('no string in kinds.ts, bar the bare kind ids, names sidecar, cplug or claude code plugin', () => {
        const source = readFileSync(new URL('./kinds.ts', import.meta.url), 'utf8')
            .replace(/\/\*[\s\S]*?\*\//g, '')
            .replace(/^\s*\/\/.*$/gm, '');
        const literals = source.match(/'[^'\n]*'|"[^"\n]*"|`[^`]*`/g) ?? [];
        expect(literals.length).toBeGreaterThan(10);
        for (const lit of literals) {
            if (lit === "'cplug'" || lit === "'plugin'") continue;
            expect(lit).not.toMatch(/sidecar|cplug|claude code plugin/i);
        }
    });
});
