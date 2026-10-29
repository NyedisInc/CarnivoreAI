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

/** Let every microtask and every timer shorter than `ms` settle. */
function settle(ms = 0): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

const ITEMS: CatalogItem[] = [
    {
        id: 'alex/deploy',
        name: 'deploy',
        publisher: 'alex',
        latest: '1.0',
        card: { title: 'Deploy Runner' },
        versions: [{ v: '1.0', digest: 'aa' }],
    },
    {
        id: 'zoe/audit',
        name: 'audit',
        publisher: 'zoe',
        latest: '3.1',
        card: { title: 'Security Audit' },
        versions: [{ v: '3.1', digest: 'bb' }],
    },
];

function bothInstalled(): InstalledItem[] {
    return [
        {
            install_id: 'iA',
            item_id: 'alex/deploy',
            scope: 'global',
            revision: 1,
            version: '1.0',
            auto_update: false,
        } as InstalledItem,
        {
            install_id: 'iB',
            item_id: 'zoe/audit',
            scope: 'global',
            revision: 1,
            version: '3.1',
            auto_update: false,
        } as InstalledItem,
    ];
}

function hostFor(
    over: Record<string, unknown> = {},
    ledger: InstalledItem[] = [],
): CatalogHost {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    return {
        listItems: () => Promise.resolve({ index: { as_of: '2026-09-15' }, items: ITEMS, untrusted: [] }),
        refreshIndex: refuse,
        listInstalled: () => Promise.resolve({ items: ledger }),
        previewInstall: refuse,
        install: refuse,
        uninstall: refuse,
        item: (id: string) =>
            Promise.resolve(ITEMS.find((entry) => entry.id === id) ?? ({} as CatalogItem)),
        patchInstalled: refuse,
        applyUpdate: refuse,
        runningSessions: () => [],
        oneShot: refuse,
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
        ...over,
    } as unknown as CatalogHost;
}

let container: HTMLElement;

beforeEach(() => {
    container = document.createElement('div');
    container.id = CATALOG_SCREEN_CONTAINER;
    document.body.appendChild(container);
});

/**
 * Close anything still open, then take the screen down.
 *
 * TEARING THE DOM OUT DOES NOT RESOLVE A MODAL. `openModal` holds a
 * promise and a count that only its own `close` settles, so a case that
 * ends with a sheet up leaks that count into the next case, where the
 * in-flight guard then refuses to open anything. Escape is how a person
 * closes it, so it is how this closes it too.
 */
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

async function paint(host: CatalogHost): Promise<void> {
    const { ensurePanel } = await import('../mount');
    const CatalogScreen = (await import('./CatalogScreen.svelte')).default;
    const handle = ensurePanel(
        CATALOG_SCREEN_CONTAINER,
        CatalogScreen as never,
        { host, t } as never,
    ) as Record<string, unknown>;
    (handle.show as () => void)();
    await settle();
}

/* the reading pane */
async function select(title: string): Promise<void> {
    const card = [...document.querySelectorAll('.catalog-card')].find((node) =>
        (node.textContent ?? '').includes(title),
    );
    (card!.querySelector('.catalog-card__open') as HTMLButtonElement).click();
    await settle();
}

function confirmSheet(): void {
    const buttons = [...document.querySelectorAll('.modal-overlay .modal-btn-primary')];
    (buttons[buttons.length - 1] as HTMLButtonElement).click();
}

function cancelSheet(): void {
    const buttons = [
        ...document.querySelectorAll('.modal-overlay .modal-btn:not(.modal-btn-primary)'),
    ];
    (buttons[buttons.length - 1] as HTMLButtonElement).click();
}

describe("an answer lands on the row the request was fired on", () => {
    test('uninstalling one row while reading another leaves the other alone', async () => {
        let release!: () => void;
        const inFlight = new Promise<void>((resolve) => {
            release = resolve;
        });
        const sent: string[] = [];
        await paint(
            hostFor(
                {
                    uninstall: (id: string) => {
                        sent.push(id);
                        return inFlight.then(() => ({}));
                    },
                },
                bothInstalled(),
            ),
        );

        await select('Deploy Runner');
        (document.querySelector('[data-act="uninstall"]') as HTMLButtonElement).click();
        await settle();
        confirmSheet();
        await settle();
        expect(sent).toEqual(['iA']);

        await select('Security Audit');
        release();
        await settle(10);

        expect(document.querySelector('[data-act="uninstall"]')).not.toBeNull();

        await select('Deploy Runner');
        expect(document.querySelector('[data-act="uninstall"]')).toBeNull();
        expect(document.querySelector('[data-act="install"]')).not.toBeNull();
    });
});

describe('a cancelled confirm sends nothing', () => {
    test('cancelling the uninstall sheet never calls the server', async () => {
        const sent: string[] = [];
        await paint(
            hostFor(
                {
                    uninstall: (id: string) => {
                        sent.push(id);
                        return Promise.resolve({});
                    },
                },
                bothInstalled(),
            ),
        );

        await select('Deploy Runner');
        (document.querySelector('[data-act="uninstall"]') as HTMLButtonElement).click();
        await settle();
        expect(document.querySelector('.modal-overlay')).not.toBeNull();

        cancelSheet();
        await settle(10);

        expect(sent).toEqual([]);
        expect(document.querySelector('[data-act="uninstall"]')).not.toBeNull();
    });
});

describe('two clicks on one control are one sheet', () => {
    test('a double click on install opens exactly one install sheet', async () => {
        const sheetRequired = () => Promise.reject(Object.assign(new Error('sheet'), { body: { code: 'sheet_required' } }));
        await paint(hostFor({ install: sheetRequired }, []));
        await select('Security Audit');

        const install = document.querySelector('[data-act="install"]') as HTMLButtonElement;
        install.click();
        install.click();
        await settle();

        expect(openModalCount()).toBe(1);
        expect(document.querySelectorAll('.modal-overlay')).toHaveLength(1);
    });

    test('a double click on uninstall opens exactly one confirm sheet', async () => {
        await paint(hostFor({ uninstall: () => new Promise<never>(() => {}) }, bothInstalled()));
        await select('Deploy Runner');

        const remove = document.querySelector('[data-act="uninstall"]') as HTMLButtonElement;
        remove.click();
        remove.click();
        await settle();

        expect(openModalCount()).toBe(1);
    });
});
