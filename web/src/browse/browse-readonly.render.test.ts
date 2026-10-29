/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { createI18n } from '../../../client/js/i18n/runtime.js';
import { viewport } from '../opscenter/engine/viewport.svelte';
import { ensurePanel, unmountPanel } from '../lib/mount';
import fixture from './fixtures/index.fixture.json';
import { staticCatalogHost } from './static-host';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);
const CONTAINER = 'browse-root';
const SIGNATURE =
    'untrusted comment: signature from minisign secret key\nRUToHYwCxY1tHoRbrhxFfYxzu5ykwie80b7tPiV9H4qARZ3pYk8g4AIeEPg1iJl2t0JZLgkAcPPz2JIZd/KSJyvkMV7Vz6mwQA4=\ntrusted comment: x\nAA==\n';

const fakeFetch = vi.fn(async (url: RequestInfo | URL) => {
    if (String(url) === 'v1/index.json') return new Response(JSON.stringify(fixture), { status: 200 });
    if (String(url) === 'v1/index.json.minisig') return new Response(SIGNATURE, { status: 200 });
    return new Response('', { status: 404 });
}) as unknown as typeof fetch;

beforeEach(() => {
    localStorage.clear();
    const c = document.createElement('div');
    c.id = CONTAINER;
    document.body.appendChild(c);
});
afterEach(() => {
    unmountPanel(CONTAINER);
    document.body.innerHTML = '';
    viewport.narrow = false;
});

async function mount(readonly: boolean, ready = '.catalog-card'): Promise<void> {
    const Screen = (await import('../lib/catalog/CatalogScreen.svelte')).default;
    const handle = ensurePanel(CONTAINER, Screen as never, { host: staticCatalogHost(fakeFetch), t, bands: true, readonly } as never) as { show: () => void };
    handle.show();
    await vi.waitFor(() => expect(document.querySelector(ready)).not.toBeNull());
}

describe('the read only Warez screen', () => {
    test('lists the index and draws no write or app-only control', async () => {
        await mount(true);
        expect(document.querySelectorAll('.catalog-card').length).toBeGreaterThan(5);
        expect(document.querySelector('[data-act="add"], [data-act="add-menu"], [data-act="update"]')).toBeNull();
        expect(document.querySelector('[data-group="installed"], [data-group="yours"], [data-group="look"]')).toBeNull();
        expect(document.querySelector('[data-key="store:updates"], [data-key*="updates"]')).toBeNull();
        expect(document.querySelector('#warez-elite-open')).toBeNull();
        expect(document.querySelector('#catalog-submit-open, [data-keys-button], [data-catalog-signin-cta]')).toBeNull();
        expect(document.body.textContent).not.toMatch(/publish a skill|publish yours|refresh the index/);
        expect(document.querySelector('[data-group="store"]')).not.toBeNull();
    }, 30000);

    test('opens a detail with get carnivore, the copyable id and no rating, and prints the trust line', async () => {
        await mount(true);
        (document.querySelector('.catalog-card__open') as HTMLElement).click();
        await vi.waitFor(() => expect(document.querySelector('.screen__detail [data-act="get"]')).not.toBeNull());
        const detail = document.querySelector('.screen__detail') as HTMLElement;
        const get = detail.querySelector('[data-act="get"]') as HTMLAnchorElement;
        expect(get.textContent?.trim()).toBe('get carnivore');
        expect(get.getAttribute('href')).toBe('https://carnivore.ai');
        expect(detail.querySelector('[data-online-id] code')?.textContent).toMatch(/^[a-z0-9_-]+\/[a-z0-9_.-]+$/i);
        expect(detail.querySelector('[data-act="copy"]')).not.toBeNull();
        expect(detail.querySelector('[data-detail-rating], [data-detail-sec="ratings"], [data-act="install"]')).toBeNull();
        const trust = document.querySelector('[data-trust-line]')?.textContent ?? '';
        expect(trust).toContain(`signed index serial ${fixture.serial}`);
        expect(trust).toContain('signing key 1E6D8DC5028C1DE8');
    });

    test('control: the same mount not read only still draws the add button', async () => {
        await mount(false);
        expect(document.querySelector('[data-act="add"]')).not.toBeNull();
        expect(document.querySelector('[data-trust-line]')).toBeNull();
    });

    test('phone: no exit arrow at the Warez root, an inner back stays; not read only still draws the arrow', async () => {
        viewport.narrow = true;
        await mount(true, '.screen__menu');
        expect(document.querySelector('[data-page-back]')).toBeNull();
        (document.querySelector('.screen__menu [data-key]') as HTMLElement).click();
        await vi.waitFor(() => expect(document.querySelector('[data-back]')).not.toBeNull());
        expect(document.querySelector('[data-page-back]')).toBeNull();
        (document.querySelector('[data-back]') as HTMLElement).click();
        await vi.waitFor(() => expect(document.querySelector('[data-back]')).toBeNull());
        unmountPanel(CONTAINER);
        document.body.innerHTML = '<div id="browse-root"></div>';
        await mount(false, '.screen__menu');
        expect(document.querySelector('[data-page-back]')).not.toBeNull();
    }, 30000);
});
