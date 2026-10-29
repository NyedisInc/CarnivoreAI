/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterEach, beforeEach, describe, expect, test } from 'vitest';

import { createI18n } from '../../client/js/i18n/runtime.js';
import { ensurePanel, panelInstance, unmountPanel } from './lib/mount';
import { WAREZ_SCREEN_CONTAINER as CATALOG_SCREEN_CONTAINER } from './lib/catalog/warez-host';
import CatalogScreen from './lib/catalog/CatalogScreen.svelte';
import type { CatalogHost } from './lib/catalog/catalog';
import { LEDGER_SCREEN_CONTAINER } from './lib/ledger/screen-host';
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

const LATCH_FILE = path.join(
    path.dirname(fileURLToPath(import.meta.url)),
    '..',
    '..',
    'client',
    'js',
    'app-boot-complete.js',
);

function loadLatchScript(): void {
    new Function(fs.readFileSync(LATCH_FILE, 'utf8'))();
}

function legacyScreenReset(): void {
    const web = (window as unknown as {
        CloudeWeb?: { closeWarezScreen?: () => boolean; closeLedgerScreen?: () => boolean };
    }).CloudeWeb;
    web?.closeWarezScreen?.();
    web?.closeLedgerScreen?.();
}

describe('a cold-load fragment is applied after the legacy boot reset, not before it', () => {
    beforeEach(() => {
        for (const id of [CATALOG_SCREEN_CONTAINER, LEDGER_SCREEN_CONTAINER]) {
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
        document.body.innerHTML = '';
        window.location.hash = '';
    });

    test('the bundle defers its first read, the reset runs, then the signal opens the overlay', async () => {
        loadLatchScript();
        const latch = (window as unknown as {
            AppBootComplete: { EVENT: string; announce: () => void; isComplete: () => boolean };
        }).AppBootComplete;
        expect(latch.isComplete()).toBe(false);

        window.location.hash = '#catalog';
        await import('./main');

        expect(catalogIsOpen()).toBe(false);
        expect(ledgerIsOpen()).toBe(false);

        legacyScreenReset();
        latch.announce();

        expect(catalogIsOpen()).toBe(true);
        expect(ledgerIsOpen()).toBe(false);

        (panelInstance(CATALOG_SCREEN_CONTAINER) as ScreenHandle).close?.();
        expect(catalogIsOpen()).toBe(false);
        latch.announce();
        expect(catalogIsOpen()).toBe(false);

        window.location.hash = '#ledger';
        window.dispatchEvent(new Event('hashchange'));
        expect(ledgerIsOpen()).toBe(true);
        expect(catalogIsOpen()).toBe(false);

        window.location.hash = '';
        window.dispatchEvent(new Event('hashchange'));
        expect(catalogIsOpen()).toBe(false);
        expect(ledgerIsOpen()).toBe(false);
    });
});
