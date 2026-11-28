/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const authFetchMock = vi.hoisted(() => vi.fn(async () => ({ ok: true })));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...actual,
        auth: { ...actual.auth, state: 'signed-in' },
        authFetch: authFetchMock,
    };
});

import './index';
import BadgeSlot from './BadgeSlot.svelte';
import { badgeSlotPlan } from './slot';
import { pluginsStore, type SlotContribution, type StoreCplugRow } from '../plugins/store.svelte';

const here = path.dirname(fileURLToPath(import.meta.url));

function makePluginRow(overrides: Partial<StoreCplugRow> = {}): StoreCplugRow {
    return {
        id: 'acme.badges',
        name: 'Acme Badges',
        enabled: true,
        state: 'active',
        runtime_paused: false,
        granted_ui_slots: ['session.badges'],
        routes: ['open_ci'],
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

let handle: ReturnType<typeof mount> | null = null;

beforeEach(() => {
    pluginsStore.resetForTest();
    authFetchMock.mockClear();
});

afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    pluginsStore.resetForTest();
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

describe('plugin session.badges source', () => {
    test('renders scoped and global plugin badges with mapped tones and inert/interactive semantics', async () => {
        seedStore([makePluginRow()], {
            'session.badges': [
                {
                    plugin_id: 'acme.badges',
                    install_key: 'acme.badges',
                    slot: 'session.badges',
                    declared_slot: 'session.badges',
                    item: {
                        id: 'ci_fail',
                        badge: 'CI fail',
                        tone: 'danger',
                        tooltip: 'Build 42 failed',
                        route: 'open_ci',
                        when: { session_ref: 'uuid-1' },
                    },
                },
                {
                    plugin_id: 'acme.badges',
                    install_key: 'acme.badges',
                    slot: 'session.badges',
                    declared_slot: 'session.badges',
                    item: {
                        id: 'other_row',
                        badge: 'Other Only',
                        tone: 'warn',
                        data: { session_id: 'ses_other' },
                    },
                },
                {
                    plugin_id: 'acme.badges',
                    install_key: 'acme.badges',
                    slot: 'session.badges',
                    declared_slot: 'session.badges',
                    item: {
                        id: 'global_accent',
                        badge: 'Synced',
                        tone: 'accent',
                    },
                },
            ],
        });

        const row1 = { session_uuid: 'uuid-1', session_id: 'ses_1', name: 'cloude_one' };
        const plan1 = badgeSlotPlan(row1)!;
        expect(plan1.items.map((i) => ({ text: i.text, tone: i.tone, interactive: Boolean(i.activate) }))).toEqual([
            { text: 'CI fail', tone: 'bad', interactive: true },
            { text: 'Synced', tone: 'accent', interactive: false },
        ]);

        const row2 = { session_uuid: 'uuid-2', session_id: 'ses_other', name: 'cloude_two' };
        const plan2 = badgeSlotPlan(row2)!;
        expect(plan2.items.map((i) => ({ text: i.text, tone: i.tone }))).toEqual([
            { text: 'Synced', tone: 'accent' },
            { text: 'Other Only', tone: 'warn' },
        ]);

        const host = document.createElement('div');
        const rowClick = vi.fn();
        host.addEventListener('click', rowClick);
        document.body.appendChild(host);
        handle = mount(BadgeSlot, { target: host, props: { plan: plan1 } });
        flushSync();

        const btn = host.querySelector('button.row-badge[data-tone="bad"]') as HTMLButtonElement;
        expect(btn.textContent).toBe('CI fail');
        expect(btn.title).toBe('Build 42 failed');
        expect(host.querySelector('span.row-badge[data-tone="accent"]')?.textContent).toBe('Synced');

        btn.click();
        expect(rowClick).not.toHaveBeenCalled();
        await vi.waitFor(() => expect(authFetchMock).toHaveBeenCalledTimes(1));
        const [url, init] = authFetchMock.mock.calls[0] as unknown as [string, RequestInit];
        expect(url).toBe('/cplug-owner/act');
        expect(JSON.parse(String(init.body))).toEqual({
            cplug_id: 'acme.badges',
            route: 'open_ci',
            session_ref: 'uuid-1',
        });
    });

    test('filters out unconsented, paused, and malformed plugin badges', () => {
        seedStore(
            [
                makePluginRow({ id: 'paused.badges', runtime_paused: true }),
                makePluginRow({ id: 'noconsent.badges', granted_ui_slots: [] }),
                makePluginRow({ id: 'bad.badges' }),
            ],
            {
                'session.badges': [
                    {
                        plugin_id: 'paused.badges',
                        install_key: 'paused.badges',
                        slot: 'session.badges',
                        declared_slot: 'session.badges',
                        item: { id: 'p', badge: 'Paused', tone: 'warn' },
                    },
                    {
                        plugin_id: 'noconsent.badges',
                        install_key: 'noconsent.badges',
                        slot: 'session.badges',
                        declared_slot: 'session.badges',
                        item: { id: 'n', badge: 'NoConsent', tone: 'warn' },
                    },
                    {
                        plugin_id: 'bad.badges',
                        install_key: 'bad.badges',
                        slot: 'session.badges',
                        declared_slot: 'session.badges',
                        item: { id: 'xss', badge: 'Bad', href: 'javascript:alert(1)' },
                    },
                ],
            },
        );

        expect(badgeSlotPlan({ session_uuid: 'uuid-1', name: 'cloude_one' })).toBeNull();
    });

    test('BadgeSlot.svelte maps info and accent tones onto --oc-* tokens', () => {
        const src = fs.readFileSync(path.join(here, 'BadgeSlot.svelte'), 'utf8');
        expect(src).toContain(".row-badge[data-tone='info']");
        expect(src).toContain('--oc-cyan');
        expect(src).toContain(".row-badge[data-tone='accent']");
        expect(src).toContain('--oc-orange');
    });
});
