import { describe, expect, test } from 'vitest';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { PLUGIN_PART_KEYS } from '../../../../client/js/labels/catalog-kind.js';
import { parsePluginManifest, pluginFacts, pluginParts } from './plugin-facts';
import type { PreviewFile } from './types';

const catalog = enCatalog as unknown as Record<string, unknown>;

const files = (...paths: string[]): PreviewFile[] =>
    paths.map((path) => ({ path, size: 1, exec: false }));

describe('the manifest is parsed, and a bad one is a state not a throw', () => {
    test('an object comes back as itself', () => {
        expect(parsePluginManifest('{"name":"x"}')).toEqual({ name: 'x' });
    });

    test.each([
        ['truncated', '{"name":'],
        ['not json', 'hello'],
        ['an array', '[1,2]'],
        ['a bare string', '"x"'],
        ['empty', ''],
        ['blank', '   '],
    ])('%s answers null rather than throwing', (_label, text) => {
        expect(parsePluginManifest(text)).toBe(null);
    });

    test.each([[null], [undefined], [42]])('the non-string %s answers null', (text) => {
        expect(parsePluginManifest(text as unknown as string)).toBe(null);
    });
});

describe('identity comes off the manifest', () => {
    test('name, version and description are trimmed', () => {
        const facts = pluginFacts(
            '{"name":"  toolbelt  ","version":" 2.1.0 ","description":" does things "}',
            [],
        );
        expect(facts.name).toBe('toolbelt');
        expect(facts.version).toBe('2.1.0');
        expect(facts.description).toBe('does things');
    });

    test('a field that is blank or not a string is null, never a guess', () => {
        const facts = pluginFacts('{"name":"   ","version":3,"description":null}', []);
        expect(facts.name).toBe(null);
        expect(facts.version).toBe(null);
        expect(facts.description).toBe(null);
    });

    test('an unparseable manifest still yields an inventory', () => {
        const facts = pluginFacts('{"name":', files('skills/a/SKILL.md'));
        expect(facts.name).toBe(null);
        expect(facts.parts).toHaveLength(1);
    });
});

describe('the inventory is counted off the file list', () => {
    test('a directory component counts every file under it', () => {
        const parts = pluginParts(
            files('skills/a/SKILL.md', 'skills/b/SKILL.md', 'README.md'),
        );
        expect(parts).toEqual([
            { prefix: 'skills/', labelKey: 'plugin.part.skills', files: 2 },
        ]);
    });

    test('a single-file component matches on equality, not on prefix', () => {
        expect(pluginParts(files('.mcp.json'))).toHaveLength(1);
        expect(pluginParts(files('.mcp.json.bak'))).toEqual([]);
    });

    test('a leading ./ is the same member', () => {
        expect(pluginParts(files('./bin/run'))).toEqual([
            { prefix: 'bin/', labelKey: 'plugin.part.bin', files: 1 },
        ]);
    });

    test('order follows the closed list so two plugins compare', () => {
        const parts = pluginParts(files('bin/run', 'agents/a.md', 'skills/s/SKILL.md'));
        expect(parts.map((part) => part.prefix)).toEqual([
            'skills/',
            'agents/',
            'bin/',
        ]);
    });

    test('a directory this build cannot name gets no row', () => {
        expect(pluginParts(files('invented/thing.txt'))).toEqual([]);
    });

    test.each([[null], [undefined], ['not a list']])(
        'a file list of %s is an empty inventory, not a throw',
        (input) => {
            expect(pluginParts(input as unknown as PreviewFile[])).toEqual([]);
        },
    );

    test('a file with no usable path is skipped', () => {
        const parts = pluginParts([
            { path: null },
            { path: '   ' },
            { path: 'hooks/hooks.json' },
        ] as PreviewFile[]);
        expect(parts).toEqual([
            { prefix: 'hooks/', labelKey: 'plugin.part.hooks', files: 1 },
        ]);
    });
});

describe('the manifest does not decide the inventory', () => {
    test('a declared component that ships no files gets NO row', () => {
        const facts = pluginFacts('{"name":"x","hooks":"./hooks/hooks.json"}', []);
        expect(facts.parts).toEqual([]);
    });

    test('an undeclared bin/ still gets a row, because it lands on PATH', () => {
        const facts = pluginFacts('{"name":"x"}', files('bin/run'));
        expect(facts.parts).toEqual([
            { prefix: 'bin/', labelKey: 'plugin.part.bin', files: 1 },
        ]);
    });
});

describe('every part this module can emit has a word for it', () => {
    test.each(Object.entries(PLUGIN_PART_KEYS))('%s -> %s exists', (_prefix, key) => {
        expect(catalog[key as string]).toBeDefined();
    });
});
