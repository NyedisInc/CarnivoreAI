import { describe, expect, test } from 'vitest';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { buildUpdateNotes, hasCplugCapabilities } from './update-notes';
import type { CplugFactsData, UpdateDiff } from './types';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

describe('update-notes (#3408)', () => {
    test('prefers explicit releaseNotes and cleans markdown syntax with semantic icons', () => {
        const notes = buildUpdateNotes({
            releaseNotes: [
                '## v1.0.3',
                '- **Controls bar:** Added always-visible keyboard hints along the bottom',
                '- Fixed **Up arrow** rotate clockwise during gameplay',
                '- Updated icon glyph to a pill',
            ].join('\n'),
            fromVersion: '1.0.1',
            toVersion: '1.0.3',
            t,
        });
        expect(notes).toHaveLength(3);
        expect(notes[0]).toMatchObject({ icon: 'keyboard', tone: 'info' });
        expect(notes[0]?.text).toBe('Controls bar: Added always-visible keyboard hints along the bottom');
        expect(notes[1]).toMatchObject({ icon: 'keyboard' });
        expect(notes[2]).toMatchObject({ icon: 'palette', tone: 'accent' });
    });

    test('extracts plain-English bullets from README.md diff instead of CSS/JS code diffs', () => {
        const diff: UpdateDiff = {
            from_version: '1.0.1',
            to_version: '1.0.3',
            unchanged: 6,
            changes: [
                {
                    path: 'views/game/style.css',
                    status: 'changed',
                    old_size: 815,
                    new_size: 1929,
                    diff: '@@ -1 +1 @@\n+#keys { display: flex; }\n',
                },
                {
                    path: 'README.md',
                    status: 'changed',
                    old_size: 900,
                    new_size: 1125,
                    diff: [
                        '--- a/README.md',
                        '+++ b/README.md',
                        '@@ -12,4 +12,4 @@',
                        '- **X / Z:** Rotate',
                        '+- **Arrow keys:** Move pill left/right/down (`↑` also rotates clockwise during play)',
                        '+- **↑ / Space / X / Z:** Rotate clockwise or counter-clockwise',
                    ].join('\n'),
                },
            ],
        };
        const notes = buildUpdateNotes({ diff, fromVersion: '1.0.1', toVersion: '1.0.3', t });
        expect(notes.map((n) => n.text)).toEqual([
            'Arrow keys: Move pill left/right/down (↑ also rotates clockwise during play)',
            '↑ / Space / X / Z: Rotate clockwise or counter-clockwise',
        ]);
        expect(notes.every((n) => !n.text.includes('#keys'))).toBe(true);
    });

    test('produces friendly fallback summary from changed file types when no changelog/README diff exists', () => {
        const diff: UpdateDiff = {
            from_version: '1.0.0',
            to_version: '1.0.1',
            unchanged: 3,
            changes: [
                { path: 'views/game/style.css', status: 'changed', old_size: 10, new_size: 20, diff: '+body{}' },
                { path: 'views/game/app.js', status: 'changed', old_size: 100, new_size: 200, diff: null },
            ],
        };
        const notes = buildUpdateNotes({ diff, fromVersion: '1.0.0', toVersion: '1.0.1', t });
        expect(notes.map((n) => n.text)).toEqual([
            'updated visual styling and layout',
            'updated app behavior and bug fixes',
        ]);
    });

    test('hasCplugCapabilities distinguishes zero-capability plugins from ones declaring permissions/tools', () => {
        const empty: CplugFactsData = {
            id: 'acme/pillpanic',
            name: 'Pill Panic',
            description: 'Game',
            version: '1.0.3',
            entry: '',
            files: 12,
            bytes: 2161567,
            permissions: [],
            tools: [],
            network_hosts: [],
            lan_hosts: [],
            secrets: [],
        };
        expect(hasCplugCapabilities(empty)).toBe(false);
        expect(hasCplugCapabilities(null)).toBe(false);
        expect(hasCplugCapabilities({ ...empty, permissions: [{ name: 'net.fetch', risk: 'high', reason: 'api' }] })).toBe(true);
        expect(hasCplugCapabilities({ ...empty, tools: [{ name: 'run', description: 'runs', gate: 'ask', input_schema: {} }] })).toBe(true);
    });
});
