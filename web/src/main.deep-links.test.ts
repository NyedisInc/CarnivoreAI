/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';

import { createI18n } from '../../client/js/i18n/runtime.js';
import { ensurePanel, panelInstance, unmountPanel } from './lib/mount';
import { WAREZ_SCREEN_CONTAINER as CATALOG_SCREEN_CONTAINER } from './lib/catalog/warez-host';
import CatalogScreen from './lib/catalog/CatalogScreen.svelte';
import type { CatalogHost } from './lib/catalog/catalog';
import { LEDGER_SCREEN_CONTAINER } from './lib/ledger/screen-host';
import { THEMES_SCREEN_CONTAINER } from './lib/themes-page/screen-host';
import LedgerScreen from './lib/ledger/LedgerScreen.svelte';
import type { LedgerHost } from './lib/ledger/ledger-host';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

/** A catalog host that answers empty and refuses every write. */
function catalogHost(): CatalogHost {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    return {
        listItems: () => Promise.resolve({ index: { as_of: '2026-09-19' }, items: [], untrusted: [] }),
        refreshIndex: refuse,
        listInstalled: () => Promise.resolve({ items: [] }),
        previewInstall: refuse,
        install: refuse,
        uninstall: refuse,
        item: refuse,
        patchInstalled: refuse,
        applyUpdate: refuse,
        runningSessions: () => [],
        oneShot: refuse,
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
    } as unknown as CatalogHost;
}

/** A ledger host that answers empty and refuses every write. */
function ledgerHost(): LedgerHost {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    return {
        providerLedger: () => Promise.resolve({ accounts: [], total: null, loop: null }),
        listAccounts: () => Promise.resolve([]),
        saveAccount: refuse,
        removeAccount: refuse,
        loginProviderAccount: refuse,
        openSession: refuse,
    } as unknown as LedgerHost;
}

type ScreenHandle = { show?: () => void; close?: () => void; isOpen?: () => boolean };

function catalogIsOpen(): boolean {
    return !!(panelInstance(CATALOG_SCREEN_CONTAINER) as ScreenHandle | null)?.isOpen?.();
}

function ledgerIsOpen(): boolean {
    return !!(panelInstance(LEDGER_SCREEN_CONTAINER) as ScreenHandle | null)?.isOpen?.();
}

function themesIsOpen(): boolean {
    return !!(panelInstance(THEMES_SCREEN_CONTAINER) as ScreenHandle | null)?.isOpen?.();
}

describe('booting the app wires the catalog and ledger hash routes, with no home mounted', () => {
    beforeEach(() => {
        for (const id of [CATALOG_SCREEN_CONTAINER, LEDGER_SCREEN_CONTAINER, THEMES_SCREEN_CONTAINER]) {
            const el = document.createElement('div');
            el.id = id;
            document.body.appendChild(el);
        }
        ensurePanel(CATALOG_SCREEN_CONTAINER, CatalogScreen as never, { host: catalogHost(), t } as never);
        ensurePanel(LEDGER_SCREEN_CONTAINER, LedgerScreen as never, { host: ledgerHost(), t } as never);
        window.location.hash = '';
    });

    afterEach(() => {
        unmountPanel(CATALOG_SCREEN_CONTAINER);
        unmountPanel(LEDGER_SCREEN_CONTAINER);
        unmountPanel(THEMES_SCREEN_CONTAINER);
        document.body.innerHTML = '';
        window.location.hash = '';
    });

    test('a cold #catalog hash opens on boot, a hashchange moves between the two, and leaving the fragment closes both', async () => {
        window.location.hash = '#catalog';
        await import('./main');
        expect(catalogIsOpen()).toBe(true);
        expect(ledgerIsOpen()).toBe(false);

        window.location.hash = '#ledger';
        window.dispatchEvent(new Event('hashchange'));
        expect(ledgerIsOpen()).toBe(true);
        expect(catalogIsOpen()).toBe(false);

        window.location.hash = '#themes';
        window.dispatchEvent(new Event('hashchange'));
        expect(themesIsOpen()).toBe(true);
        expect(ledgerIsOpen()).toBe(false);

        window.location.hash = '';
        window.dispatchEvent(new Event('hashchange'));
        expect(catalogIsOpen()).toBe(false);
        expect(ledgerIsOpen()).toBe(false);
        expect(themesIsOpen()).toBe(false);
    });
});
