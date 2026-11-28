/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import CatalogCard from './CatalogCard.svelte';
import CatalogDetail from './CatalogDetail.svelte';
import DetailActions from './DetailActions.svelte';
import PluginPane from '../plugins-page/PluginPane.svelte';
import { toCplugItem, type CplugRow } from '../plugins-page/cplugs-adapter';
import { cardView } from './card';
import type { CatalogHost } from './catalog';
import { disableAndUninstallPlugin, isInstalledRevoked, revocationOfItem } from './revocation';
import type { InstalledItem } from './types';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

let handles: Array<Record<string, unknown>> = [];
afterEach(() => {
    for (const h of handles) unmount(h);
    handles = [];
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

function stubHost(overrides: Partial<CatalogHost> = {}): CatalogHost {
    const noop = () => Promise.reject(new Error('unused'));
    return {
        listItems: noop,
        refreshIndex: noop,
        listInstalled: noop,
        previewInstall: noop,
        install: noop,
        uninstall: vi.fn(async () => {}),
        item: () => Promise.resolve({}),
        patchInstalled: noop,
        applyUpdate: noop,
        runningSessions: () => [],
        oneShot: noop,
        listProjects: () => Promise.resolve([]),
        ...overrides,
    } as unknown as CatalogHost;
}

describe('M5.3 revocation enforcement & installed controls', () => {
    test('revocationOfItem & isInstalledRevoked detect wire and heldReason signals', () => {
        expect(revocationOfItem({ revoked: true, revocation_reason: 'key compromise', revoked_since: '2026-11-20' })).toEqual({
            revoked: true,
            reason: 'key compromise',
            since: '2026-11-20',
        });
        expect(revocationOfItem({ revocation_state: 'revoked', revocation_reason: 'malicious update' }).revoked).toBe(true);
        expect(revocationOfItem({ revoked: false }).revoked).toBe(false);
        expect(isInstalledRevoked({ heldReason: 'revoked' })).toBe(true);
        expect(isInstalledRevoked({ heldReason: 'revoked: compromised tag' })).toBe(true);
        expect(isInstalledRevoked({ revoked: true })).toBe(true);
        expect(isInstalledRevoked({ heldReason: 'start hook failed' })).toBe(false);
    });

    test('CatalogCard & CatalogDetail disable install/update and render RevokedBanner for revoked items', () => {
        const card = cardView(
            {
                id: 'evil/bad-plug',
                name: 'bad-plug',
                publisher: 'evil',
                latest: '1.0.0',
                kind: 'cplug',
                revoked: true,
                revocation_reason: 'steals credentials',
                revoked_since: '2026-11-25T10:00:00Z',
                card: { title: 'Bad Plug', brief: 'compromised' },
                versions: [{ v: '1.0.0', digest: 'a'.repeat(64) }],
            } as never,
            false,
        );

        expect(card.revoked).toBe(true);
        expect(card.revocationReason).toBe('steals credentials');

        handles.push(
            mount(CatalogCard, {
                target: document.body,
                props: {
                    card,
                    t,
                    state: { kind: 'idle' },
                    onInstall: vi.fn(),
                    onUpdate: vi.fn(),
                    onOpen: vi.fn(),
                },
            }),
        );
        flushSync();

        const btn = document.querySelector('[data-act="revoked"]') as HTMLButtonElement;
        expect(btn).not.toBeNull();
        expect(btn.disabled).toBe(true);

        const detailWrap = document.createElement('div');
        document.body.appendChild(detailWrap);
        handles.push(
            mount(CatalogDetail, {
                target: detailWrap,
                props: {
                    card,
                    item: null,
                    host: stubHost(),
                    installed: [],
                    rowState: { kind: 'idle' },
                    t,
                    onInstall: vi.fn(),
                    onLedgerChange: vi.fn(),
                },
            }),
        );
        flushSync();

        expect(detailWrap.querySelector('[data-revoked-banner]')).not.toBeNull();
        expect(detailWrap.textContent).toContain('steals credentials');
        expect(detailWrap.querySelector('[data-act="install"]')).toBeNull();
    });

    test('DetailActions allows uninstalling an installed revoked copy while blocking update/install', () => {
        const card = cardView(
            {
                id: 'evil/bad-plug',
                name: 'bad-plug',
                latest: '1.1.0',
                kind: 'cplug',
                revoked: true,
                revocation_reason: 'revoked by admin',
                versions: [{ v: '1.1.0', digest: 'b'.repeat(64) }],
            } as never,
            false,
        );
        const installed: InstalledItem = {
            install_id: 'inst-rev',
            item_id: 'evil/bad-plug',
            scope: 'global',
            revision: 2,
            version: '1.0.0',
            update_available: true,
        };

        handles.push(
            mount(DetailActions, {
                target: document.body,
                props: {
                    card,
                    installed,
                    rowState: { kind: 'update-available' },
                    host: stubHost(),
                    t,
                    onInstall: vi.fn(),
                    onLedgerChange: vi.fn(),
                },
            }),
        );
        flushSync();

        expect(document.querySelector('[data-act="update"]')).toBeNull();
        expect(document.querySelector('[data-act="install-other"]')).toBeNull();
        expect(document.querySelector('[data-act="uninstall"]')).not.toBeNull();
    });

    test('PluginPane mounts RevokedBanner and fires 1-click Disable & Uninstall when heldReason is revoked', async () => {
        const row: CplugRow = {
            id: 'bad-plug',
            runtime: 'sidecar',
            item_id: 'evil/bad-plug',
            install_id: 'inst-1',
            name: 'Bad Plug',
            description: 'Revoked plugin',
            enabled: true,
            state: 'unavailable',
            detail: 'revoked',
            revoked: true,
            revocation_reason: 'malware detected',
            revoked_since: '2026-11-25T12:00:00Z',
        };
        const plugin = toCplugItem(row, t);
        const onDisableAndUninstall = vi.fn();

        handles.push(
            mount(PluginPane, {
                target: document.body,
                props: {
                    plugin,
                    tab: 'overview',
                    onTab: vi.fn(),
                    onConfirmOff: vi.fn(),
                    onCancelOff: vi.fn(),
                    onGrant: vi.fn(),
                    loadActivity: async () => [],
                    onDisableAndUninstall,
                    t,
                },
            }),
        );
        flushSync();

        const banner = document.querySelector('[data-revoked-banner]');
        expect(banner).not.toBeNull();
        expect(banner?.textContent).toContain('malware detected');
        const btn = document.querySelector('[data-act="disable-uninstall"]') as HTMLButtonElement;
        expect(btn).not.toBeNull();
        btn.click();
        expect(onDisableAndUninstall).toHaveBeenCalledTimes(1);

        const disable = vi.fn(async () => {});
        const uninstall = vi.fn(async () => {});
        const res = await disableAndUninstallPlugin({
            enabled: true,
            disable,
            installId: 'inst-1',
            uninstall,
            t,
        });
        expect(res).toEqual({ done: true, error: null });
        expect(disable).toHaveBeenCalledTimes(1);
        expect(uninstall).toHaveBeenCalledWith('inst-1');
    });
});
