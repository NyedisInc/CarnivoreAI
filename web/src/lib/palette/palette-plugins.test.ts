/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const confirmMock = vi.hoisted(() => vi.fn(async () => true));
const authFetchMock = vi.hoisted(() => vi.fn(async () => ({ ok: true })));
const primarySessionMock = vi.hoisted(() => vi.fn(() => 'ses_1'));

vi.mock('../confirm-ok/confirm-ok', () => ({ confirmOk: confirmMock }));
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...actual,
        auth: { ...actual.auth, state: 'signed-in' },
        authFetch: authFetchMock,
    };
});
vi.mock('../../opscenter/api/host', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../opscenter/api/host')>();
    return {
        ...actual,
        primarySessionId: primarySessionMock,
        newSession: vi.fn(),
        newTerminal: vi.fn(),
        startNewProject: vi.fn(),
        openThemes: vi.fn(),
        openSettings: vi.fn(),
        openHosts: vi.fn(),
    };
});
vi.mock('../palette/palette-host', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../palette/palette-host')>();
    return { ...actual, isTauriDesktop: () => false, onMac: () => true };
});

import Palette from './Palette.svelte';
import { appActions } from './palette-actions';
import type { DrawerRowLike } from './palette-sources';
import { resolveActiveSlots, resolvePluginCommands } from '../plugins/slot-actions';
import { pluginsStore, type SlotContribution, type StoreCplugRow } from '../plugins/store.svelte';

function makeRow(overrides: Partial<StoreCplugRow> = {}): StoreCplugRow {
    return {
        id: 'acme.tools',
        name: 'Acme Tools',
        enabled: true,
        state: 'active',
        runtime_paused: false,
        granted_ui_slots: ['commands'],
        routes: ['ping'],
        declared_tools: ['acme_scan'],
        ...overrides,
    };
}

function seedStore(rows: StoreCplugRow[], slots: Record<string, SlotContribution[]>): void {
    pluginsStore.rows = rows;
    pluginsStore.read = true;
    pluginsStore.slots = slots;
    pluginsStore.slotsRead = true;
}

let mountedPalette: Record<string, unknown> | null = null;

beforeEach(() => {
    pluginsStore.resetForTest();
    confirmMock.mockClear();
    confirmMock.mockResolvedValue(true);
    authFetchMock.mockClear();
    primarySessionMock.mockReturnValue('ses_1');
});

afterEach(() => {
    if (mountedPalette) unmount(mountedPalette);
    mountedPalette = null;
    pluginsStore.resetForTest();
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe('command palette plugin commands', () => {
    it('includes active consented commands from slots and [[ui.commands]] and passes sessionRef on execution', async () => {
        seedStore(
            [
                makeRow({
                    commands: [
                        { id: 'deploy', title: 'Deploy Preview', steps: [{ route: 'ping' }], confirm: 'Deploy now?' },
                        { id: 'leaked_contrib', title: 'Should Not Leak', route: 'ping' },
                    ],
                    ui_contribute: {
                        commands: [{ id: 'leaked_contrib', title: 'Should Not Leak', route: 'ping' }],
                    },
                    granted_ui_slots: ['commands'],
                }),
            ],
            {
                commands: [
                    {
                        plugin_id: 'acme.tools',
                        install_key: 'acme.tools',
                        slot: 'commands',
                        declared_slot: 'commands',
                        item: {
                            id: 'scan',
                            label: 'Run Security Scan',
                            tool: 'acme_scan',
                            shortcut: 'Alt+Cmd+S',
                            order: 10,
                        },
                    },
                    {
                        plugin_id: 'acme.tools',
                        install_key: 'acme.tools',
                        slot: 'commands',
                        declared_slot: 'commands',
                        item: {
                            id: 'disabled_cmd',
                            label: 'Disabled Cmd',
                            route: 'ping',
                            disabled: true,
                        },
                    },
                ],
            },
        );

        const rows: DrawerRowLike[] = [{ name: 'cloude_api', session_id: 'ses_1', session_uuid: 'uuid-111' }];
        const actions = appActions(rows);
        const titles = actions.map((a) => a.title);

        expect(titles).toContain('Run Security Scan');
        expect(titles).toContain('Deploy Preview');
        expect(titles).not.toContain('Disabled Cmd');

        const scan = actions.find((a) => a.id === 'plugin-cmd:acme.tools:scan')!;
        expect(scan.subtitle).toContain('Acme Tools');
        expect(scan.subtitle).toContain('Alt+Cmd+S');
        await scan.run({ popout: false });

        expect(authFetchMock).toHaveBeenCalledTimes(1);
        const [url, init] = authFetchMock.mock.calls[0] as unknown as [string, RequestInit];
        expect(url).toBe('/cplug-owner/tool');
        expect(JSON.parse(String(init.body))).toEqual({
            cplug_id: 'acme.tools',
            tool: 'acme_scan',
            args: {},
            session_ref: 'uuid-111',
        });

        const deploy = actions.find((a) => a.id === 'plugin-cmd:acme.tools:deploy')!;
        confirmMock.mockResolvedValueOnce(false);
        const cancelled = await deploy.run({ popout: false });
        expect(cancelled).toBe(false);
        expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({ message: 'Deploy now?' }));
        expect(authFetchMock).toHaveBeenCalledTimes(1);

        confirmMock.mockResolvedValueOnce(true);
        await deploy.run({ popout: false });
        expect(authFetchMock).toHaveBeenCalledTimes(2);
        const [deployUrl, deployInit] = authFetchMock.mock.calls[1] as unknown as [string, RequestInit];
        expect(deployUrl).toBe('/cplug-owner/act');
        expect(JSON.parse(String(deployInit.body))).toEqual({
            cplug_id: 'acme.tools',
            route: 'deploy',
            session_ref: 'uuid-111',
        });
    });

    it('excludes disabled/paused/unconsented plugins and dangerous labels or hrefs', () => {
        seedStore(
            [
                makeRow({ id: 'disabled.plug', enabled: false, commands: [{ id: 'a', title: 'Hidden Disabled', route: 'ping' }] }),
                makeRow({ id: 'paused.plug', runtime_paused: true, commands: [{ id: 'b', title: 'Hidden Paused', route: 'ping' }] }),
                makeRow({
                    id: 'unconsented.plug',
                    granted_ui_slots: [],
                    commands: [{ id: 'c', title: 'Unconsented Contrib', route: 'ping' }],
                    ui_contribute: { commands: [{ id: 'c', title: 'Unconsented Contrib', route: 'ping' }] },
                }),
                makeRow({ id: 'xss.plug' }),
            ],
            {
                commands: [
                    {
                        plugin_id: 'xss.plug',
                        install_key: 'xss.plug',
                        slot: 'commands',
                        declared_slot: 'commands',
                        item: { id: 'bad_href', label: 'Bad Href', href: 'javascript:alert(1)' },
                    },
                    {
                        plugin_id: 'xss.plug',
                        install_key: 'xss.plug',
                        slot: 'commands',
                        declared_slot: 'commands',
                        item: { id: 'bad_lbl', label: 'Bad\u0000Label', route: 'ping' },
                    },
                    {
                        plugin_id: 'unconsented.plug',
                        install_key: 'unconsented.plug',
                        slot: 'commands',
                        declared_slot: 'commands',
                        item: { id: 'leaked', label: 'Unconsented Slot', route: 'ping' },
                    },
                ],
            },
        );

        const pluginItems = appActions([]).filter((a) => a.id.startsWith('plugin-cmd:'));
        expect(pluginItems).toEqual([]);
    });

    it('handles safe internal and external href commands without touching unsafe URLs', async () => {
        const openSpy = vi.fn();
        vi.stubGlobal('open', openSpy);
        seedStore([makeRow()], {
            commands: [
                {
                    plugin_id: 'acme.tools',
                    install_key: 'acme.tools',
                    slot: 'commands',
                    declared_slot: 'commands',
                    item: { id: 'ext', label: 'Open Docs', href: 'https://example.com/docs' },
                },
            ],
        });

        const item = appActions([]).find((a) => a.id === 'plugin-cmd:acme.tools:ext')!;
        await item.run({ popout: false });
        expect(openSpy).toHaveBeenCalledWith('https://example.com/docs', '_blank', 'noopener,noreferrer');
    });

    it('Palette.svelte acquires slots on mount and updates its reactive corpus when slots change', () => {
        const acquireSpy = vi.spyOn(pluginsStore, 'acquire').mockImplementation(() => () => {});
        seedStore([makeRow()], { commands: [] });

        mountedPalette = mount(Palette, { target: document.body, props: { initial: '> AcmeCommand', onClose: () => {} } }) as Record<string, unknown>;
        flushSync();

        expect(acquireSpy).toHaveBeenCalledWith({ includeSlots: true });
        expect(document.body.textContent).not.toContain('AcmeCommand Launch');

        seedStore([makeRow()], {
            commands: [
                {
                    plugin_id: 'acme.tools',
                    install_key: 'acme.tools',
                    slot: 'commands',
                    declared_slot: 'commands',
                    item: { id: 'launch', label: 'AcmeCommand Launch', route: 'ping' },
                },
            ],
        });
        flushSync();

        expect(document.body.textContent).toContain('AcmeCommand Launch');
    });

    it('blocks unconsented ui_contribute.commands with steps (Probe 1B), disabled [[ui.commands]], and !read/undeclared macros (Probe 1D)', () => {
        seedStore(
            [
                makeRow({
                    id: 'p.bypass_cmd',
                    granted_ui_slots: [],
                    commands: [{ id: 'evil_cmd', title: 'Evil Bypass Cmd', route: 'ping', steps: ['x'] }],
                    ui_contribute: {
                        commands: [{ id: 'evil_cmd', title: 'Evil Bypass Cmd', route: 'ping', steps: ['x'] }],
                    },
                }),
                makeRow({
                    id: 'p.consented_bad_steps',
                    granted_ui_slots: ['commands'],
                    commands: [{ id: 'evil_steps', title: 'Evil Steps', route: 'ping', steps: ['x'] }],
                    ui_contribute: {
                        commands: [{ id: 'evil_steps', title: 'Evil Steps', route: 'ping', steps: ['x'] }],
                    },
                }),
                makeRow({
                    id: 'p.disabled_meta',
                    granted_ui_slots: [],
                    commands: [
                        { id: 'disabled_steps', title: 'Disabled Steps', steps: [{ action: 'ui.invalidate' }], disabled: true },
                        { id: 'ping', title: 'Disabled Bare Route', disabled: true },
                    ],
                }),
            ],
            {},
        );
        expect(resolvePluginCommands()).toEqual([]);

        pluginsStore.resetForTest();
        pluginsStore.read = false;
        pluginsStore.rows = [];
        pluginsStore.slotsRead = true;
        pluginsStore.slots = {
            commands: [
                {
                    plugin_id: 'unknown.plug',
                    install_key: 'unknown.plug',
                    slot: 'commands',
                    declared_slot: 'commands',
                    item: { id: 'evil_macro', label: 'Evil', macro: 'undeclared_macro' },
                },
            ],
        };
        expect(resolveActiveSlots('commands')).toEqual([]);

        pluginsStore.rows = [
            makeRow({ id: 'known.unconsented', granted_ui_slots: [], macros: ['allowed_macro'] }),
            makeRow({ id: 'known.consented', granted_ui_slots: ['commands'], macros: ['allowed_macro'] }),
        ];
        pluginsStore.slots = {
            commands: [
                {
                    plugin_id: 'known.unconsented',
                    install_key: 'known.unconsented',
                    slot: 'commands',
                    declared_slot: 'commands',
                    item: { id: 'ok_macro', label: 'No Consent', macro: 'allowed_macro' },
                },
                {
                    plugin_id: 'known.consented',
                    install_key: 'known.consented',
                    slot: 'commands',
                    declared_slot: 'commands',
                    item: { id: 'bad_macro', label: 'Undeclared Macro', macro: 'undeclared_macro' },
                },
                {
                    plugin_id: 'known.consented',
                    install_key: 'known.consented',
                    slot: 'commands',
                    declared_slot: 'commands',
                    item: { id: 'good_macro', label: 'Declared Macro', macro: 'allowed_macro' },
                },
            ],
        };
        expect(resolveActiveSlots('commands').map((e) => e.id)).toEqual(['good_macro']);
    });
});
