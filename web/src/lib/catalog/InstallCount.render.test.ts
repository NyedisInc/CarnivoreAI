/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import InstallCount from './InstallCount.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { CatalogHost } from './catalog';
import type { ItemInstalls } from './types';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

/** An item three people have reported installing. */
const COUNTED: ItemInstalls = {
    item_id: 'example-owner/sme',
    count: 3,
    by_version: { '1.0.0': 3 },
};

const UNREPORTED: ItemInstalls = {
    item_id: 'example-owner/sme',
    count: 0,
    by_version: {},
};

interface Recorder {
    host: CatalogHost;
    calls: string[];
}

function hostFor(answer: ItemInstalls | Error): Recorder {
    const recorder: Recorder = { host: null as never, calls: [] };
    const refuse = (name: string) => () => {
        recorder.calls.push(name);
        return Promise.reject(new Error('the count fact must not call this'));
    };
    recorder.host = {
        itemInstalls: (itemId: string) => {
            recorder.calls.push(`itemInstalls:${itemId}`);
            return answer instanceof Error
                ? Promise.reject(answer)
                : Promise.resolve(answer);
        },
        itemRatings: refuse('itemRatings'),
        catalogPreferences: refuse('catalogPreferences'),
        listItems: refuse('listItems'),
        refreshIndex: refuse('refreshIndex'),
        listInstalled: refuse('listInstalled'),
        previewInstall: refuse('previewInstall'),
        install: refuse('install'),
        uninstall: refuse('uninstall'),
        item: refuse('item'),
        patchInstalled: refuse('patchInstalled'),
        applyUpdate: refuse('applyUpdate'),
        runningSessions: () => [],
        oneShot: refuse('oneShot'),
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
        catalogSession: refuse('catalogSession'),
        startDeviceFlow: refuse('startDeviceFlow'),
        pollDeviceFlow: refuse('pollDeviceFlow'),
        signOutOfCatalog: refuse('signOutOfCatalog'),
    } as unknown as CatalogHost;
    return recorder;
}

let panel: Record<string, unknown> | null = null;

function paint(host: CatalogHost): void {
    const target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(InstallCount, {
        target,
        props: { itemId: 'example-owner/sme', host, t } as never,
    }) as never;
}

/** Let every microtask settle. */
function settle(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

afterEach(() => {
    if (panel) unmount(panel as never);
    panel = null;
    document.body.innerHTML = '';
});

describe('a read that did not land', () => {
    test('it says so, and paints NO number at all', async () => {
        const recorder = hostFor(new Error('no route to host'));
        paint(recorder.host);
        await settle();
        expect(document.body.textContent).toContain(
            i18n.t('skill.installs.unavailable', { reason: 'no route to host' }),
        );
        expect(document.querySelector('.installs__count')).toBeNull();
        expect(document.body.textContent).not.toMatch(/\d/);
    });

    test('and it is NOT reported as "nobody has reported installing this"', async () => {
        const recorder = hostFor(new Error('down'));
        paint(recorder.host);
        await settle();
        expect(document.body.textContent).not.toContain(i18n.t('skill.installs.none'));
    });
});

describe('the count, and the one time it may not be shown', () => {
    test('NEGATIVE CONTROL AND ITS PAIR: zero shows no number, three does', async () => {
        const unreported = hostFor(UNREPORTED);
        paint(unreported.host);
        await settle();
        expect(document.body.textContent).toContain(i18n.t('skill.installs.none'));
        expect(document.querySelector('.installs__count')).toBeNull();

        unmount(panel as never);
        panel = null;
        document.body.innerHTML = '';

        const counted = hostFor(COUNTED);
        paint(counted.host);
        await settle();
        expect(document.querySelector('.installs__count')).not.toBeNull();
        expect(document.body.textContent).toContain(
            i18n.t('skill.installs.count', { count: 3 }),
        );
    });

    test('a singular count reads as one install, not "1 installs"', async () => {
        const recorder = hostFor({ item_id: 'a/b', count: 1 });
        paint(recorder.host);
        await settle();
        expect(document.body.textContent).toContain(
            i18n.t('skill.installs.count', { count: 1 }),
        );
    });
});

describe('what this fact is allowed to touch', () => {
    test('NEGATIVE CONTROL: it reads the count and calls nothing else', async () => {
        const recorder = hostFor(COUNTED);
        paint(recorder.host);
        await settle();
        expect(recorder.calls).toEqual(['itemInstalls:example-owner/sme']);
    });

    test('and with no item it asks for nothing at all', async () => {
        const recorder = hostFor(COUNTED);
        const target = document.createElement('div');
        document.body.appendChild(target);
        panel = mount(InstallCount, {
            target,
            props: { itemId: null, host: recorder.host, t } as never,
        }) as never;
        await settle();
        expect(recorder.calls).toEqual([]);
    });
});
