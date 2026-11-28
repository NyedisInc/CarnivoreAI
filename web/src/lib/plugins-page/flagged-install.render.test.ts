/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { cardView } from '../catalog/card';
import type { CatalogHost } from '../catalog/catalog';
import InstallSheet from '../catalog/InstallSheet.svelte';
import type { InstallRequest, InstalledItem } from '../catalog/types';
import type { ManagerAdapter } from '../manager-frame/types';
import PluginInstallSheet from './PluginInstallSheet.svelte';
import PluginsScreen from './PluginsScreen.svelte';
import { toCplugItem, type CplugRow } from './cplugs-adapter';
import type { InstallSheetStore } from './install-sheet-model';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const settle = async () => {
    for (let i = 0; i < 40; i += 1) {
        await Promise.resolve();
        flushSync();
    }
};

let handles: Array<Record<string, unknown>> = [];
afterEach(() => {
    for (const h of handles) unmount(h);
    handles = [];
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

const FLAGGED_FACTS = {
    id: 'flagged-plug',
    name: 'Flagged Plug',
    description: 'Uses shell access',
    version: '1.0.0',
    entry: 'main.py',
    files: 2,
    bytes: 512,
    permissions: [],
    tools: [],
    network_hosts: [],
    lan_hosts: [],
    secrets: [],
};

function flaggedPreview() {
    return {
        body: '{}',
        body_sha: 'sha-flagged',
        digest: 'dg-flagged',
        plan_token: 'pt-flagged',
        cplug_facts: FLAGGED_FACTS,
        cplug_facts_sha: 'facts-flagged',
        flagged: true,
        requires_warning_ack: true,
        warning_reasons: ['executes shell subprocesses'],
        review: {
            status: 'reviewed',
            verdict: 'flagged',
            summary: 'Runs shell helper commands. Verify host permissions before enabling.',
            warnings: [],
        },
    };
}

describe('M5.3 flagged plugin warning badge & required ack UI', () => {
    test('PluginInstallSheet shows FlaggedWarningBox and blocks install until checkbox is ticked', async () => {
        const installs: InstallRequest[] = [];
        const card = cardView(
            {
                id: 'acme/flagged-plug',
                name: 'flagged-plug',
                publisher: 'acme',
                latest: '1.0.0',
                kind: 'cplug',
                versions: [
                    {
                        v: '1.0.0',
                        review: { status: 'reviewed', verdict: 'flagged', summary: 'Runs shell helper commands.' },
                    },
                ],
            } as never,
            false,
        );

        const host = {
            listItems: async () => ({ items: [] }),
            refreshIndex: async () => ({ items: [] }),
            listInstalled: async () => ({ items: [] }),
            previewInstall: async () => flaggedPreview() as never,
            install: async (req: InstallRequest) => {
                installs.push(req);
                return {
                    install_id: 'inst-flag-1',
                    item_id: 'acme/flagged-plug',
                    scope: 'global',
                    revision: 1,
                    version: '1.0.0',
                } as InstalledItem;
            },
            uninstall: async () => {},
            item: async () => ({}),
            patchInstalled: async () => ({}) as InstalledItem,
            applyUpdate: async () => ({}) as InstalledItem,
            runningSessions: () => [],
            oneShot: async () => ({}),
            listProjects: async () => [],
        } as unknown as CatalogHost;

        const store: InstallSheetStore = {
            previewGithub: async () => ({} as never),
            installGithub: async () => ({ id: 'x', enabled: false }) as never,
            updatePlugin: vi.fn(async () => ({}) as never),
        };

        handles.push(
            mount(PluginInstallSheet, {
                target: document.body,
                props: {
                    open: true,
                    mode: 'catalog',
                    card,
                    host,
                    store,
                    loadSheet: async () => ({
                        id: 'flagged-plug',
                        revision: 1,
                        permissions: [],
                        ui_slots: [],
                        digest: 'dg-flagged',
                        body_sha: 'sha-flagged',
                        grants_sha: 'g-sha',
                    }),
                    onClose: vi.fn(),
                    onDone: vi.fn(),
                    t,
                },
            }),
        );
        await settle();

        const box = document.querySelector('[data-flagged-warning-box]');
        expect(box).not.toBeNull();
        expect(box?.textContent).toContain('Runs shell helper commands.');
        expect(box?.textContent).toContain('executes shell subprocesses');

        const installBtn = document.querySelector('[data-install-disabled]') as HTMLButtonElement;
        expect(installBtn.disabled).toBe(true);

        const ackTick = document.querySelector('[data-flagged-ack]') as HTMLInputElement;
        expect(ackTick.checked).toBe(false);
        ackTick.click();
        await settle();

        expect(installBtn.disabled).toBe(false);
        installBtn.click();
        await settle();

        expect(installs).toHaveLength(1);
        expect(installs[0]?.consent).toMatchObject({
            cplug_accepted: true,
            cplug_flagged_ack: true,
            acknowledge_flagged: true,
        });
    });

    test('InstallSheet for card.isCplug requires FlaggedWarningBox tick before install', async () => {
        const installs: InstallRequest[] = [];
        const card = cardView(
            {
                id: 'acme/flagged-plug',
                name: 'flagged-plug',
                publisher: 'acme',
                latest: '1.0.0',
                kind: 'cplug',
                versions: [{ v: '1.0.0', review: { status: 'reviewed', verdict: 'flagged', summary: 'Flagged review.' } }],
            } as never,
            false,
        );
        const host = {
            listItems: async () => ({ items: [] }),
            refreshIndex: async () => ({ items: [] }),
            listInstalled: async () => ({ items: [] }),
            previewInstall: async () => flaggedPreview() as never,
            install: async (req: InstallRequest) => {
                installs.push(req);
                return { install_id: 'i2', item_id: 'acme/flagged-plug', scope: 'global', revision: 1 } as InstalledItem;
            },
            uninstall: async () => {},
            item: async () => ({}),
            patchInstalled: async () => ({}) as InstalledItem,
            applyUpdate: async () => ({}) as InstalledItem,
            runningSessions: () => [],
            oneShot: async () => ({}),
            listProjects: async () => [],
        } as unknown as CatalogHost;

        handles.push(
            mount(InstallSheet, {
                target: document.body,
                props: { card, host, t, close: vi.fn() },
            }),
        );
        await settle();

        expect(document.querySelector('[data-flagged-warning-box]')).not.toBeNull();
        const confirmBtn = document.querySelector('.modal-footer .modal-btn-primary') as HTMLButtonElement;
        expect(confirmBtn.disabled).toBe(true);

        (document.querySelector('.cplugfacts input') as HTMLInputElement).click();
        await settle();
        expect(confirmBtn.disabled).toBe(true);

        (document.querySelector('[data-flagged-ack]') as HTMLInputElement).click();
        await settle();
        expect(confirmBtn.disabled).toBe(false);

        confirmBtn.click();
        await settle();

        expect(installs[0]?.consent).toMatchObject({
            cplug_accepted: true,
            cplug_flagged_ack: true,
            acknowledge_flagged: true,
        });
    });

    test('PluginsScreen displays Clean and Flagged verdict badges on plugin cards', async () => {
        const cleanRow: CplugRow = {
            id: 'clean-plug',
            runtime: 'sidecar',
            name: 'Clean Plug',
            description: 'Safe plugin',
            enabled: false,
            state: 'disabled',
            review_verdict: 'clean',
            flagged: false,
        };
        const flaggedRow: CplugRow = {
            id: 'flagged-plug',
            runtime: 'sidecar',
            name: 'Flagged Plug',
            description: 'Flagged plugin',
            enabled: false,
            state: 'disabled',
            review_verdict: 'flagged',
            flagged: true,
        };
        const adapter: ManagerAdapter = {
            list: async () => [toCplugItem(cleanRow, t), toCplugItem(flaggedRow, t)],
            setEnabled: async (id) => toCplugItem(id.includes('clean') ? cleanRow : flaggedRow, t),
        };

        const screen = mount(PluginsScreen, {
            target: document.body,
            props: { adapter, catalog: null, t },
        });
        handles.push(screen);
        (screen as unknown as { show: () => void }).show();
        await settle();

        const cleanBadges = document.querySelector('[data-plugin-badges="clean-plug"]');
        const flaggedBadges = document.querySelector('[data-plugin-badges="flagged-plug"]');
        expect(cleanBadges?.querySelector('[data-plugin-verdict="clean"]')?.textContent).toContain('clean');
        expect(flaggedBadges?.querySelector('[data-plugin-verdict="flagged"]')?.textContent).toContain('flagged');
    });
});
