/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import AppUpdatePanel from './AppUpdatePanel.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

interface Call { path: string; method: string; body: unknown }

function harness(patch: Record<string, unknown> = {}) {
    const status = {
        attached: true, state: 'current', current_version: '1.16.2', latest_version: '', percent: null,
        detail: null, auto_update: false, ...patch,
    };
    const calls: Call[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        const body = init?.body ? JSON.parse(String(init.body)) : null;
        calls.push({ path, method: init?.method ?? 'GET', body });
        if (path === '/app-update/auto-update') status.auto_update = body.enabled;
        return structuredClone(status);
    }) as never;
    return { fetcher, calls };
}

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
});

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

async function render(h: ReturnType<typeof harness>): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(AppUpdatePanel, { target, props: { fetcher: h.fetcher, pollMs: 0 } }));
    await settle();
    return target;
}

const el = (root: HTMLElement, key: string) => root.querySelector<HTMLElement>(`[data-app-update="${key}"]`);

describe('AppUpdatePanel', () => {
    test('with no app attached it shows the server version and never a question mark', async () => {
        const root = await render(harness({ attached: false, state: 'unavailable', current_version: '1.17.0' }));
        expect(el(root, 'version')!.textContent).toContain('1.17.0');
        expect(root.textContent).not.toContain('?');
    });

    test('shows the version, the state, and the switch OFF by default', async () => {
        const root = await render(harness());
        expect(el(root, 'version')!.textContent).toContain('1.16.2');
        expect(el(root, 'state')!.textContent).toContain('up to date');
        expect(el(root, 'auto')!.getAttribute('aria-checked')).toBe('false');
        expect(el(root, 'install')).toBeNull();
    });

    test('flipping the switch PUTs enabled true and shows it on', async () => {
        const h = harness();
        const root = await render(h);
        el(root, 'auto')!.click();
        await settle();
        expect(h.calls.at(-1)).toEqual({ path: '/app-update/auto-update', method: 'PUT', body: { enabled: true } });
        expect(el(root, 'auto')!.getAttribute('aria-checked')).toBe('true');
    });

    test('an available update offers update now, which POSTs /install', async () => {
        const h = harness({ state: 'available', latest_version: '1.17.0' });
        const root = await render(h);
        expect(el(root, 'state')!.textContent).toContain('update available: 1.17.0');
        el(root, 'install')!.click();
        await settle();
        expect(h.calls.at(-1)).toMatchObject({ path: '/app-update/install', method: 'POST' });
    });

    test('check now POSTs /check; no desktop app attached offers neither button', async () => {
        const h = harness();
        const root = await render(h);
        el(root, 'check')!.click();
        await settle();
        expect(h.calls.at(-1)).toMatchObject({ path: '/app-update/check', method: 'POST' });
        const none = await render(harness({ attached: false, state: 'unavailable' }));
        expect(none.querySelector('[data-app-update="check"]')).toBeNull();
        expect(none.querySelector('[data-app-update="state"]')!.textContent).toContain('no desktop app is attached');
    });
});
