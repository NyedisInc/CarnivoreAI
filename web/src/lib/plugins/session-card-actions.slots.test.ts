/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const confirmMock = vi.hoisted(() => vi.fn(async () => true));
const authFetchMock = vi.hoisted(() => vi.fn(async () => ({ ok: true })));

vi.mock('../confirm-ok/confirm-ok', () => ({ confirmOk: confirmMock }));
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...actual,
        auth: { ...actual.auth, state: 'signed-in' },
        authFetch: authFetchMock,
    };
});

import { runSessionCardAction, sessionCardMenuItems } from './session-card-actions';
import { pluginsStore, type SlotContribution, type StoreCplugRow } from './store.svelte';
import type { PluginContext, SessionCardRow } from './types';

function makePluginRow(overrides: Partial<StoreCplugRow> = {}): StoreCplugRow {
    return {
        id: 'acme.row',
        name: 'Acme Row',
        enabled: true,
        state: 'active',
        runtime_paused: false,
        granted_ui_slots: ['session.row_actions'],
        routes: ['inspect', 'purge'],
        declared_tools: [],
        ...overrides,
    };
}

function seedStore(rows: StoreCplugRow[], slots: Record<string, SlotContribution[]>): void {
    pluginsStore.rows = rows;
    pluginsStore.read = true;
    pluginsStore.slots = slots;
    pluginsStore.slotsRead = true;
}

function makeCtx(): PluginContext & { refresh: ReturnType<typeof vi.fn<() => void>> } {
    return { flags: {}, refresh: vi.fn<() => void>() };
}

beforeEach(() => {
    pluginsStore.resetForTest();
    confirmMock.mockClear();
    confirmMock.mockResolvedValue(true);
    authFetchMock.mockClear();
});

afterEach(() => {
    pluginsStore.resetForTest();
    vi.restoreAllMocks();
});

describe('session.row_actions in sessionCardMenuItems and runSessionCardAction', () => {
    test('surfaces active consented row actions only on session rows with keyless/danger/disabled metadata', async () => {
        seedStore([makePluginRow()], {
            'session.row_actions': [
                {
                    plugin_id: 'acme.row',
                    install_key: 'acme.row',
                    slot: 'session.row_actions',
                    declared_slot: 'session.row_actions',
                    item: {
                        id: 'purge',
                        label: 'Purge Cache',
                        route: 'purge',
                        tone: 'danger',
                        confirm: 'Purge session cache?',
                    },
                },
                {
                    plugin_id: 'acme.row',
                    install_key: 'acme.row',
                    slot: 'session.row_actions',
                    declared_slot: 'session.row_actions',
                    item: {
                        id: 'locked_step',
                        label: 'Locked Step',
                        route: 'inspect',
                        disabled: true,
                        tooltip: 'Not available now',
                        order: 680,
                    },
                },
            ],
        });

        const ctx = makeCtx();
        const sessionRow: SessionCardRow = { name: 'cloude_api', unread: false, kind: 'session', sessionUuid: 'uuid-99', sessionId: 'ses_99' };
        const items = sessionCardMenuItems(sessionRow, ctx).filter((i) => i.id.startsWith('cplug-slot:'));
        expect(items).toEqual([
            {
                id: 'cplug-slot:acme.row:purge',
                label: 'Purge Cache',
                order: 650,
                locked: false,
                keyless: true,
                danger: true,
            },
            {
                id: 'cplug-slot:acme.row:locked_step',
                label: 'Locked Step',
                order: 680,
                locked: false,
                keyless: true,
                disabled: true,
                reason: 'Not available now',
            },
        ]);

        expect(sessionCardMenuItems({ name: 'b1', unread: false, kind: 'browser' }, ctx).some((i) => i.id.startsWith('cplug-slot:'))).toBe(false);
        expect(sessionCardMenuItems({ name: 'layout:1', unread: false, kind: 'layout' }, ctx).some((i) => i.id.startsWith('cplug-slot:'))).toBe(false);

        confirmMock.mockResolvedValueOnce(false);
        expect(await runSessionCardAction('cplug-slot:acme.row:purge', sessionRow, ctx)).toBe(true);
        expect(authFetchMock).not.toHaveBeenCalled();
        expect(ctx.refresh).not.toHaveBeenCalled();

        confirmMock.mockResolvedValueOnce(true);
        expect(await runSessionCardAction('cplug-slot:acme.row:purge', sessionRow, ctx)).toBe(true);
        expect(authFetchMock).toHaveBeenCalledTimes(1);
        const [url, init] = authFetchMock.mock.calls[0] as unknown as [string, RequestInit];
        expect(url).toBe('/cplug-owner/act');
        expect(JSON.parse(String(init.body))).toEqual({
            cplug_id: 'acme.row',
            route: 'purge',
            session_ref: 'uuid-99',
        });
        expect(ctx.refresh).toHaveBeenCalledTimes(1);

        expect(await runSessionCardAction('cplug-slot:acme.row:locked_step', sessionRow, ctx)).toBe(false);
    });

    test('supplies non-empty fallback reason when disabled=true omits tooltip (Probe 3A)', async () => {
        seedStore([makePluginRow()], {
            'session.row_actions': [
                {
                    plugin_id: 'acme.row',
                    install_key: 'acme.row',
                    slot: 'session.row_actions',
                    declared_slot: 'session.row_actions',
                    item: {
                        id: 'disabled_no_tip',
                        label: 'Disabled No Tip',
                        route: 'inspect',
                        disabled: true,
                    },
                },
            ],
        });

        const ctx = makeCtx();
        const sessionRow: SessionCardRow = { name: 'cloude_api', unread: false, kind: 'session', sessionUuid: 'uuid-99' };
        const items = sessionCardMenuItems(sessionRow, ctx).filter((i) => i.id.startsWith('cplug-slot:'));
        expect(items).toEqual([
            {
                id: 'cplug-slot:acme.row:disabled_no_tip',
                label: 'Disabled No Tip',
                order: 650,
                locked: false,
                keyless: true,
                disabled: true,
                reason: 'Unavailable',
            },
        ]);
        expect(await runSessionCardAction('cplug-slot:acme.row:disabled_no_tip', sessionRow, ctx)).toBe(false);
    });

    test('re-validates plugin active state at runtime and blocks unconsented row metadata fallback', async () => {
        seedStore(
            [
                makePluginRow({
                    id: 'unconsented.plug',
                    granted_ui_slots: [],
                    session_row_actions: [{ id: 'leak', label: 'Leak', route: 'inspect' }],
                }),
                makePluginRow(),
            ],
            {
                'session.row_actions': [
                    {
                        plugin_id: 'acme.row',
                        install_key: 'acme.row',
                        slot: 'session.row_actions',
                        declared_slot: 'session.row_actions',
                        item: { id: 'inspect', label: 'Inspect', route: 'inspect' },
                    },
                ],
            },
        );

        const ctx = makeCtx();
        const sessionRow: SessionCardRow = { name: 'cloude_api', unread: false, sessionId: 'ses_1' };
        expect(sessionCardMenuItems(sessionRow, ctx).map((i) => i.id).filter((id) => id.startsWith('cplug-slot:'))).toEqual([
            'cplug-slot:acme.row:inspect',
        ]);

        seedStore([makePluginRow({ runtime_paused: true })], {
            'session.row_actions': [
                {
                    plugin_id: 'acme.row',
                    install_key: 'acme.row',
                    slot: 'session.row_actions',
                    declared_slot: 'session.row_actions',
                    item: { id: 'inspect', label: 'Inspect', route: 'inspect' },
                },
            ],
        });

        expect(await runSessionCardAction('cplug-slot:acme.row:inspect', sessionRow, ctx)).toBe(false);
        expect(authFetchMock).not.toHaveBeenCalled();
    });
});
