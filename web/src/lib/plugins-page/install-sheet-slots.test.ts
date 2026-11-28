/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { CardView } from '../catalog/card';
import type { CatalogHost } from '../catalog/catalog';
import type { InstallPreview, InstalledItem } from '../catalog/types';
import type { GithubPreviewResponse } from '../plugins/store.svelte';
import type { Translate } from '../sessions/types';
import { toCplugItem, type CplugRow, type CplugSheet } from './cplugs-adapter';
import type { InstallSheetStore } from './install-sheet-model';
import PluginInstallSheet from './PluginInstallSheet.svelte';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) {
        await tick();
        await Promise.resolve();
    }
    flushSync();
}

function setInputValue(input: HTMLInputElement, val: string): void {
    input.value = val;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
}

function makeStore(overrides: Partial<InstallSheetStore> = {}): InstallSheetStore {
    return {
        previewGithub: vi.fn(async () => ({}) as GithubPreviewResponse),
        installGithub: vi.fn(async () => ({
            id: 'slot-plug',
            kind: 'cplug',
            trust_tier: 'unverified_github',
            trust_badge: 'Unverified GitHub Repo',
            unverified: true,
            code_sha256: 'sha-1',
            scope: 'global' as const,
            enabled: true,
            runtime_active: true,
        })),
        updatePlugin: vi.fn(async () => ({ id: 'slot-plug', enabled: true, state: 'active' }) as CplugRow),
        refresh: vi.fn(async () => true),
        ...overrides,
    };
}

describe('PluginInstallSheet -- services, events, and ui_slots consent (M4.1c)', () => {
    test('github mode: zero app permissions + ui_slots renders slot cards, gates canSubmit until slot ticked, displays services/events in fold, and forwards ui_slots + ui_slots_sha + slot_ticks', async () => {
        const preview: GithubPreviewResponse = {
            id: 'slot-plug',
            name: 'Slot Plugin',
            version: '1.0.0',
            kind: 'cplug',
            trust_tier: 'unverified_github',
            trust_badge: 'Unverified GitHub Repo',
            unverified: true,
            code_sha256: 'sha-slot-1',
            permissions: [],
            services: { provides: [{ name: 'kv.v1', methods: ['get', 'set'] }], consumes: ['auth.v1'] },
            events: { on: ['session.started'], emit: ['slot:ready'] },
            ui_contribute: { 'terminal.toolbar': [{ id: 't1', label: 'Ping', route: 'ping' }] },
            consent_sheet: {
                digest: 'sha-slot-1',
                body_sha: 'body-slot-1',
                grants_sha: 'grants-empty',
                permissions: [],
                ui_slots: [
                    {
                        slot: 'terminal.toolbar',
                        count: 1,
                        risk: 'medium',
                        reason: 'adds ping action to terminal toolbar',
                        granted: false,
                        needs_tick: true,
                    },
                ],
                ui_slots_sha: 'slots-sha-1',
            },
            runtime_active: true,
            source: { url: 'https://github.com/acme/slot-plug.git', commit: '12345678', subdir: '' },
        };
        const store = makeStore({ previewGithub: vi.fn(async () => preview) });
        const onDone = vi.fn();

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: { open: true, mode: 'github', t, store, onClose: vi.fn(), onDone },
        });
        await settle();

        setInputValue(target.querySelector<HTMLInputElement>('[data-github-source]')!, 'acme/slot-plug');
        target.querySelector<HTMLButtonElement>('[data-github-preview]')!.click();
        await settle();

        expect(target.querySelector('[data-cap-empty]')).toBeNull();
        expect(target.querySelector('[data-cap-group="ui_slots"]')).not.toBeNull();
        expect(target.querySelector('[data-cap-slot-reason]')?.textContent).toContain('adds ping action to terminal toolbar');

        const folds = Array.from(target.querySelectorAll<HTMLButtonElement>('.oc-fold__toggle'));
        folds[1]!.click();
        await settle();
        expect(target.querySelector('[data-cap-service-provides="kv.v1"]')?.textContent).toContain('get, set');
        expect(target.querySelector('[data-cap-service-consumes="auth.v1"]')?.textContent).toContain('auth.v1');
        expect(target.querySelector('[data-cap-events-on]')?.textContent).toContain('session.started');
        expect(target.querySelector('[data-cap-events-emit]')?.textContent).toContain('slot:ready');

        const enableBtn = target.querySelector<HTMLButtonElement>('[data-install-enable]')!;
        const slotTick = target.querySelector<HTMLInputElement>('[data-cap-slot-tick="terminal.toolbar"]')!;
        expect(slotTick.checked).toBe(false);
        expect(enableBtn.disabled).toBe(true);

        slotTick.click();
        await settle();
        expect(enableBtn.disabled).toBe(false);

        enableBtn.click();
        await settle();
        expect(store.installGithub).toHaveBeenCalledWith({
            source: 'acme/slot-plug',
            enable: true,
            activate_runtime: false,
            ui_slots: ['terminal.toolbar'],
            consent: {
                digest: 'sha-slot-1',
                body_sha: 'body-slot-1',
                grants_sha: 'grants-empty',
                ticks: [],
                ui_slots_sha: 'slots-sha-1',
                slot_ticks: ['terminal.toolbar'],
            },
        });
        expect(onDone).toHaveBeenCalledWith({ id: 'slot-plug', enabled: true });
    });

    test('enable mode: renders services:* / events:* labels + ui_slots from enableSheet and forwards ui_slots + ui_slots_sha + slot_ticks to updatePlugin', async () => {
        const row: CplugRow = {
            id: 'bus-plug',
            runtime: 'sidecar',
            name: 'Bus Plugin',
            version: '1.0.0',
            tier: 'catalog',
            enabled: false,
            state: 'disabled',
            consent_required: true,
            permissions: { app: ['services:kv.v1', 'events:session.started'] },
            grants: { app: [] },
            risks: { 'services:kv.v1': 'medium', 'events:session.started': 'low' },
            reasons: { 'services:kv.v1': 'call kv service', 'events:session.started': 'react to sessions' },
            services: { consumes: ['kv.v1'] },
            events: { on: ['session.started'] },
            ui_contribute: { 'project.panels': [{ id: 'p1', label: 'Panel', route: 'panel' }] },
        };
        const item = toCplugItem(row, t);
        const sheet: CplugSheet = {
            digest: 'en-d',
            body_sha: 'en-b',
            grants_sha: 'en-g',
            permissions: [
                { name: 'services:kv.v1', risk: 'medium', granted: false },
                { name: 'events:session.started', risk: 'low', granted: false },
            ],
            ui_slots: [
                {
                    slot: 'project.panels',
                    count: 1,
                    risk: 'medium',
                    reason: 'show panel tab',
                    granted: false,
                    needs_tick: true,
                },
            ],
            ui_slots_sha: 'en-slots-sha',
        };
        const store = makeStore();
        const onDone = vi.fn();

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: {
                open: true,
                mode: 'enable',
                item,
                store,
                loadSheet: async () => sheet,
                t,
                onClose: vi.fn(),
                onDone,
            },
        });
        await settle();

        expect(target.textContent).toContain('call the kv.v1 plugin service');
        expect(target.textContent).toContain('emit or subscribe to the session.started plugin event');

        const permTick = target.querySelector<HTMLInputElement>('[data-cap-tick="services:kv.v1"]')!;
        const slotTick = target.querySelector<HTMLInputElement>('[data-cap-slot-tick="project.panels"]')!;
        const enableBtn = target.querySelector<HTMLButtonElement>('[data-install-enable]')!;
        expect(enableBtn.disabled).toBe(true);

        permTick.click();
        await settle();
        expect(enableBtn.disabled).toBe(true);

        slotTick.click();
        await settle();
        expect(enableBtn.disabled).toBe(false);

        enableBtn.click();
        await settle();

        expect(store.updatePlugin).toHaveBeenCalledWith('bus-plug', {
            enabled: true,
            grants: { app: ['services:kv.v1', 'events:session.started'], ui_slots: ['project.panels'] },
            consent: {
                digest: 'en-d',
                body_sha: 'en-b',
                grants_sha: 'en-g',
                ticks: ['services:kv.v1'],
                ui_slots_sha: 'en-slots-sha',
                slot_ticks: ['project.panels'],
            },
        });
        expect(onDone).toHaveBeenCalledWith({ id: 'slot-plug', enabled: true });
    });

    test('catalog mode: gracefully transitions to enable step if loadSheet reveals ungranted ui_slots omitted from catalog preview', async () => {
        const preview: InstallPreview = {
            digest: 'cat-d',
            body_sha: 'cat-b',
            plan_token: 'cat-plan',
            cplug_facts_sha: 'cat-facts',
            cplug_facts: {
                id: 'warez-slots',
                name: 'Warez Slots',
                description: 'Contributes slots',
                version: '1.0.0',
                entry: 'main.py',
                files: 2,
                bytes: 256,
                permissions: [{ name: 'sessions.read', risk: 'low', reason: 'read' }],
                tools: [],
                network_hosts: [],
                lan_hosts: [],
                secrets: [],
            },
        };
        const sheetAfterInstall: CplugSheet = {
            digest: 'cat-d',
            body_sha: 'cat-b',
            grants_sha: 'cat-g',
            permissions: [{ name: 'sessions.read', risk: 'low', granted: false }],
            ui_slots: [
                {
                    slot: 'session.row_actions',
                    count: 1,
                    risk: 'medium',
                    reason: 'adds row button',
                    granted: false,
                    needs_tick: true,
                },
            ],
            ui_slots_sha: 'cat-slots-sha',
        };
        const host = {
            previewInstall: vi.fn(async () => preview),
            install: vi.fn(async () => ({ install_id: 'inst-ws', name: 'warez-slots' }) as InstalledItem),
            listProjects: vi.fn(async () => []),
        } as unknown as CatalogHost;
        const card = {
            id: 'pub/warez-slots',
            name: 'warez-slots',
            headline: 'Warez Slots',
            version: '1.0.0',
            isCplug: true,
            isPlugin: false,
            untrusted: false,
        } as unknown as CardView;
        const store = makeStore();
        const onDone = vi.fn();

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: {
                open: true,
                mode: 'catalog',
                card,
                host,
                store,
                loadSheet: async () => sheetAfterInstall,
                t,
                onClose: vi.fn(),
                onDone,
            },
        });
        await settle();

        target.querySelector<HTMLButtonElement>('[data-install-enable]')!.click();
        await settle();

        expect(host.install).toHaveBeenCalledTimes(1);
        expect(store.updatePlugin).not.toHaveBeenCalled();
        expect(onDone).not.toHaveBeenCalled();

        expect(target.querySelector('[data-install-sheet="enable"]')).not.toBeNull();
        const slotTick = target.querySelector<HTMLInputElement>('[data-cap-slot-tick="session.row_actions"]')!;
        expect(slotTick).not.toBeNull();
        expect(target.querySelector<HTMLButtonElement>('[data-install-enable]')!.disabled).toBe(true);

        slotTick.click();
        await settle();
        expect(target.querySelector<HTMLButtonElement>('[data-install-enable]')!.disabled).toBe(false);

        target.querySelector<HTMLButtonElement>('[data-install-enable]')!.click();
        await settle();

        expect(store.updatePlugin).toHaveBeenCalledWith('warez-slots', {
            enabled: true,
            grants: { app: ['sessions.read'], ui_slots: ['session.row_actions'] },
            consent: {
                digest: 'cat-d',
                body_sha: 'cat-b',
                grants_sha: 'cat-g',
                ticks: [],
                ui_slots_sha: 'cat-slots-sha',
                slot_ticks: ['session.row_actions'],
            },
        });
        expect(onDone).toHaveBeenCalledWith({ id: 'slot-plug', enabled: true });
    });
});
