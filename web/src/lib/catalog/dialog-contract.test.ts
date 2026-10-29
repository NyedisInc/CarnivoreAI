/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { openModalCount } from '../modal';
import { unmountPanel } from '../mount';
import { CATALOG_SCREEN_CONTAINER, unmountCatalogScreen } from './screen-host';
import type { CatalogHost } from './catalog';
import type { CatalogItem, InstalledItem } from './types';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

function settle(ms = 0): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

const ITEMS: CatalogItem[] = [
    {
        id: 'acme/deploy',
        name: 'deploy',
        publisher: 'acme',
        latest: '1.0',
        card: { title: 'Deploy Runner' },
        versions: [{ v: '1.0', digest: 'aa' }],
    },
];

const LEDGER: InstalledItem[] = [
    {
        install_id: 'iA',
        item_id: 'acme/deploy',
        scope: 'global',
        revision: 1,
        version: '1.0',
        auto_update: false,
    } as InstalledItem,
];

function hostFor(): CatalogHost {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    return {
        listItems: () => Promise.resolve({ index: { as_of: '2026-09-15' }, items: ITEMS, untrusted: [] }),
        refreshIndex: refuse,
        listInstalled: () => Promise.resolve({ items: LEDGER }),
        previewInstall: refuse,
        install: refuse,
        uninstall: () => new Promise<never>(() => {}),
        item: (id: string) =>
            Promise.resolve(ITEMS.find((entry) => entry.id === id) ?? ({} as CatalogItem)),
        patchInstalled: refuse,
        applyUpdate: refuse,
        runningSessions: () => [],
        oneShot: refuse,
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
    } as unknown as CatalogHost;
}

let container: HTMLElement;

beforeEach(() => {
    container = document.createElement('div');
    container.id = CATALOG_SCREEN_CONTAINER;
    document.body.appendChild(container);
});

async function dismissEverything(): Promise<void> {
    for (let guard = 0; guard < 8; guard += 1) {
        const open = document.querySelector('.modal-overlay');
        if (!open) return;
        open.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        await settle();
    }
}

afterEach(async () => {
    await dismissEverything();
    unmountCatalogScreen();
    unmountPanel(CATALOG_SCREEN_CONTAINER);
    document.body.innerHTML = '';
});

async function paint(): Promise<void> {
    const { ensurePanel } = await import('../mount');
    const CatalogScreen = (await import('./CatalogScreen.svelte')).default;
    const handle = ensurePanel(
        CATALOG_SCREEN_CONTAINER,
        CatalogScreen as never,
        { host: hostFor(), t } as never,
    ) as Record<string, unknown>;
    (handle.show as () => void)();
    await settle();
}

async function openDetail(): Promise<HTMLButtonElement> {
    const opener = document.querySelector('.catalog-card__open') as HTMLButtonElement;
    opener.focus();
    opener.click();
    await settle();
    return opener;
}

async function openConfirm(): Promise<HTMLButtonElement> {
    const trigger = document.querySelector('[data-act="uninstall"]') as HTMLButtonElement;
    trigger.focus();
    trigger.click();
    await settle();
    return trigger;
}

function overlay(): HTMLElement | null {
    return document.querySelector('.modal-overlay');
}

function press(key: string, shiftKey = false): void {
    const target = (document.activeElement as HTMLElement | null) ?? document.body;
    target.dispatchEvent(new KeyboardEvent('keydown', { key, shiftKey, bubbles: true }));
}

describe('escape belongs to the top-most surface, never to the one underneath', () => {
    test('escape over an open sheet closes the SHEET and leaves the screen up', async () => {
        await paint();
        await openDetail();
        await openConfirm();
        expect(openModalCount()).toBe(1);

        press('Escape');
        await settle();

        expect(openModalCount()).toBe(0);
        expect(overlay()).toBeNull();
        expect(container.querySelector('.oc-page')).not.toBeNull();
    });

    test('and the screen stays up on escape once nothing is open above it (a page never closes on Escape)', async () => {
        await paint();
        await openDetail();
        await openConfirm();
        press('Escape');
        await settle();
        document.body.focus();
        press('Escape');
        await settle();
        expect(container.querySelector('.oc-page')).not.toBeNull();
    });
});

describe('a dialog takes focus, keeps it, and hands it back', () => {
    test('the sheet focuses itself, so it can hear its own keys', async () => {
        await paint();
        await openDetail();
        await openConfirm();
        expect(overlay()!.contains(document.activeElement)).toBe(true);
    });

    test('tab from the last control wraps to the first, and never leaves', async () => {
        await paint();
        await openDetail();
        await openConfirm();
        const focusable = [...overlay()!.querySelectorAll('button:not([disabled])')];
        expect(focusable.length).toBeGreaterThan(1);

        (focusable[focusable.length - 1] as HTMLElement).focus();
        press('Tab');
        expect(document.activeElement).toBe(focusable[0]);
    });

    test('shift-tab from the first control wraps to the last', async () => {
        await paint();
        await openDetail();
        await openConfirm();
        const focusable = [...overlay()!.querySelectorAll('button:not([disabled])')];

        (focusable[0] as HTMLElement).focus();
        press('Tab', true);
        expect(document.activeElement).toBe(focusable[focusable.length - 1]);
    });

    test('closing gives focus back to the control that opened it', async () => {
        await paint();
        await openDetail();
        const trigger = await openConfirm();
        expect(document.activeElement).not.toBe(trigger);

        press('Escape');
        await settle();

        expect(document.activeElement).toBe(trigger);
    });
});
