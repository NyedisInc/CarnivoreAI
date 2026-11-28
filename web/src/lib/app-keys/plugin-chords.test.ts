/** @vitest-environment jsdom */
import { createRequire } from 'node:module';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const authFetchMock = vi.hoisted(() => vi.fn(async () => ({ ok: true })));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...actual,
        auth: { ...actual.auth, state: 'signed-in' },
        authFetch: authFetchMock,
    };
});

import { APP_CHORDS } from './chords';
import { effectiveAppChords, effectiveChordsWithPlugins } from './effective-chords';
import { pick } from './router';
import { normalizePluginChord, resolvePluginChords } from '../plugins/slot-actions';
import { pluginsStore, type SlotContribution, type StoreCplugRow } from '../plugins/store.svelte';

const require = createRequire(import.meta.url);
const macChords = require('../../../../macOS/app-menu/chords.js') as {
    auditAccelerators: (template: unknown[]) => Array<{ id: string; chord: string; reason: string }>;
    refusalFor: (item: { id?: string; role?: string }, acc: string, taken?: Map<string, string>) => string | null;
};

function makeRow(overrides: Partial<StoreCplugRow> = {}): StoreCplugRow {
    return {
        id: 'acme.keys',
        name: 'Acme Keys',
        enabled: true,
        state: 'active',
        runtime_paused: false,
        granted_ui_slots: ['commands', 'chords'],
        routes: ['ping'],
        declared_tools: ['acme_tool'],
        ...overrides,
    };
}

function seedStore(rows: StoreCplugRow[], slots: Record<string, SlotContribution[]>): void {
    pluginsStore.rows = rows;
    pluginsStore.read = true;
    pluginsStore.slots = slots;
    pluginsStore.slotsRead = true;
}

beforeEach(() => {
    pluginsStore.resetForTest();
    authFetchMock.mockClear();
});

afterEach(() => {
    pluginsStore.resetForTest();
    vi.restoreAllMocks();
});

describe('plugin chords resolution and protection', () => {
    it('normalizes CmdOrCtrl per keyboard family and rejects unknown modifiers', () => {
        expect(normalizePluginChord('CmdOrCtrl+Shift+Y', 'mac')).toBe('shift+cmd+y');
        expect(normalizePluginChord('CmdOrCtrl+Shift+Y', 'other')).toBe('ctrl+shift+y');
        expect(normalizePluginChord('SuperMagic+Y', 'mac')).toBe('');
    });

    it('appends valid slots, row.chords, and command shortcuts with inFields=false', async () => {
        seedStore(
            [
                makeRow({
                    commands: [{ id: 'cmd_ping', title: 'Ping From Cmd', route: 'ping', shortcut: 'Alt+Cmd+Y' }],
                    chords: [{ shortcut: 'Shift+Cmd+U', command: 'cmd_ping' }],
                }),
            ],
            {
                chords: [
                    {
                        plugin_id: 'acme.keys',
                        install_key: 'acme.keys',
                        slot: 'chords',
                        declared_slot: 'chords',
                        item: { id: 'slot_tool', label: 'Run Tool', shortcut: 'Shift+Cmd+Y', tool: 'acme_tool' },
                    },
                ],
            },
        );

        const base = effectiveAppChords(APP_CHORDS, {}, 'mac');
        const full = effectiveChordsWithPlugins(APP_CHORDS, {}, 'mac', () => 'ses_42');
        expect(full.slice(0, base.length)).toEqual(base);

        const pluginChords = full.slice(base.length);
        expect(pluginChords.map((c) => c.id)).toEqual([
            'cplug.acme.keys.cmd_ping',
            'cplug.acme.keys.cmd_ping',
            'cplug.acme.keys.slot_tool',
        ]);
        for (const chord of pluginChords) {
            expect(chord.inFields).toBe(false);
        }

        const matched = pick(full, { key: 'y', code: 'KeyY', metaKey: true, shiftKey: true });
        expect(matched?.id).toBe('cplug.acme.keys.slot_tool');
        expect(matched?.run(new KeyboardEvent('keydown'))).toBe(true);
        await vi.waitFor(() => expect(authFetchMock).toHaveBeenCalledTimes(1));
        const [url, init] = authFetchMock.mock.calls[0] as unknown as [string, RequestInit];
        expect(url).toBe('/cplug-owner/tool');
        expect(JSON.parse(String(init.body))).toEqual({
            cplug_id: 'acme.keys',
            tool: 'acme_tool',
            args: {},
            session_ref: 'ses_42',
        });
    });

    it('blocks protected, terminal-owned, text-editing, ACTIONS, user-rebound, and duplicate chords', () => {
        const blockedShortcuts = [
            'Cmd+C',
            'Cmd+T',
            'Cmd+L',
            'Cmd+D',
            'Shift+Cmd+T',
            'Cmd+Space',
            'Cmd+Tab',
            'Cmd+N',
            'Cmd+Shift+N',
            'Cmd+O',
            'Ctrl+Alt+Cmd+C',
            'Cmd+K',
            'Cmd+F',
            'Cmd+ArrowLeft',
            'Alt+Backspace',
            'Ctrl+C',
            'Cmd+R',
            'Alt+Cmd+I',
            'Cmd+J',
        ];

        seedStore(
            [
                makeRow({ id: 'alpha.plug' }),
                makeRow({ id: 'beta.plug' }),
            ],
            {
                chords: [
                    ...blockedShortcuts.map((shortcut, idx) => ({
                        plugin_id: 'alpha.plug',
                        install_key: 'alpha.plug',
                        slot: 'chords',
                        declared_slot: 'chords',
                        item: { id: `blocked_${idx}`, label: `Blocked ${idx}`, shortcut, route: 'ping' },
                    })),
                    {
                        plugin_id: 'alpha.plug',
                        install_key: 'alpha.plug',
                        slot: 'chords',
                        declared_slot: 'chords',
                        item: { id: 'winner', label: 'Winner', shortcut: 'Shift+Cmd+Y', route: 'ping' },
                    },
                    {
                        plugin_id: 'beta.plug',
                        install_key: 'beta.plug',
                        slot: 'chords',
                        declared_slot: 'chords',
                        item: { id: 'loser', label: 'Loser', shortcut: 'Shift+Cmd+Y', route: 'ping' },
                    },
                ],
            },
        );

        const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
        const effective = effectiveAppChords(APP_CHORDS, { mac: { 'history.back': ['cmd+j'] } }, 'mac');
        const resolved = resolvePluginChords('mac', effective);

        expect(resolved.map((c) => c.id)).toEqual(['cplug.alpha.plug.winner']);
        expect(warnSpy).toHaveBeenCalled();
    });

    it('rejects non-Ctrl+Shift chords on non-Mac families and enforces consent', () => {
        seedStore(
            [
                makeRow({ id: 'other.plug', granted_ui_slots: ['chords'] }),
                makeRow({ id: 'noconsent.plug', granted_ui_slots: [] }),
            ],
            {
                chords: [
                    {
                        plugin_id: 'other.plug',
                        install_key: 'other.plug',
                        slot: 'chords',
                        declared_slot: 'chords',
                        item: { id: 'bad_alt', label: 'AltGr Bad', shortcut: 'Ctrl+Alt+Y', route: 'ping' },
                    },
                    {
                        plugin_id: 'other.plug',
                        install_key: 'other.plug',
                        slot: 'chords',
                        declared_slot: 'chords',
                        item: { id: 'good_other', label: 'Good Other', shortcut: 'Ctrl+Shift+Y', route: 'ping' },
                    },
                    {
                        plugin_id: 'noconsent.plug',
                        install_key: 'noconsent.plug',
                        slot: 'chords',
                        declared_slot: 'chords',
                        item: { id: 'steal', label: 'No Consent', shortcut: 'Ctrl+Shift+U', route: 'ping' },
                    },
                ],
            },
        );

        const resolved = resolvePluginChords('other', effectiveAppChords(APP_CHORDS, {}, 'other'));
        expect(resolved.map((c) => c.id)).toEqual(['cplug.other.plug.good_other']);
    });

    it('blocks unconsented ui_contribute.chords referencing a command (Probe 1C) and disabled chords', () => {
        seedStore(
            [
                makeRow({
                    id: 'p.bypass_chord',
                    granted_ui_slots: [],
                    commands: [{ id: 'cmd_ping', title: 'Cmd Ping', route: 'ping' }],
                    ui_contribute: { chords: [{ command: 'cmd_ping', shortcut: 'Shift+Cmd+Y' }] },
                    chords: [{ command: 'cmd_ping', shortcut: 'Shift+Cmd+Y' }],
                }),
                makeRow({
                    id: 'p.disabled_chord',
                    granted_ui_slots: ['commands', 'chords'],
                    commands: [{ id: 'cmd_ok', title: 'Cmd OK', route: 'ping' }],
                    chords: [{ command: 'cmd_ok', shortcut: 'Shift+Cmd+U', disabled: true } as never],
                }),
            ],
            {},
        );

        const resolved = resolvePluginChords('mac', effectiveAppChords(APP_CHORDS, {}, 'mac'));
        expect(resolved).toEqual([]);
    });
});

describe('macOS/app-menu/chords.js reserved & duplicate audit', () => {
    it('flags duplicate explicit accelerators and reserves file/OS/hotkey chords', () => {
        const findings = macChords.auditAccelerators([
            {
                id: 'test',
                submenu: [
                    { id: 'test.one', accelerator: 'Shift+Cmd+Y' },
                    { id: 'test.two', accelerator: 'Shift+Cmd+Y' },
                ],
            },
        ]);
        expect(findings).toHaveLength(1);
        expect(findings[0]).toMatchObject({ id: 'test.one', chord: 'Shift+Cmd+Y' });

        const anonFindings = macChords.auditAccelerators([
            {
                id: 'menu',
                submenu: [
                    { accelerator: 'Shift+Cmd+Y' },
                    { accelerator: 'Shift+Cmd+Y' },
                ],
            },
        ]);
        expect(anonFindings).toHaveLength(1);
        expect(anonFindings[0]).toMatchObject({ chord: 'Shift+Cmd+Y' });

        expect(macChords.refusalFor({ id: 'file.new_session' }, 'Cmd+N')).toBeNull();
        expect(macChords.refusalFor({ id: 'other.item' }, 'Cmd+N')).toMatch(/file\.js/);
        for (const reserved of ['Ctrl+Alt+Cmd+C', 'Cmd+T', 'Cmd+L', 'Cmd+D', 'Shift+Cmd+T', 'Cmd+Space', 'Cmd+Tab']) {
            expect(macChords.refusalFor({ id: 'any' }, reserved), reserved).not.toBeNull();
        }
    });
});
