/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import WebPushPanel from './WebPushPanel.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { Fetcher } from './web-push/api';

setLocale('en');

const ROW = { id: 's1', service: 'fcm.googleapis.com', device_id: null, created_at: null, last_result: { status: 201, at: '2026-09-30T01:02:03+00:00' } };

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
});

async function render(env: { supported: boolean; standalone: boolean }, rows = [ROW]) {
    const calls: string[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? 'GET'} ${path}`);
        if (path === '/push/test') return { sent: [{ id: 's1', status: 201 }] };
        return { subscriptions: rows };
    }) as unknown as Fetcher;
    mounted.push(mount(WebPushPanel, { target: document.body, props: { fetcher, env } }));
    await tick();
    await tick();
    flushSync();
    return calls;
}

describe('WebPushPanel', () => {
    test('installed app with push support shows alerts on, the list and the last result', async () => {
        await render({ supported: true, standalone: true });
        expect(document.querySelector('[data-wp="on"]')).not.toBeNull();
        expect(document.querySelector('[data-wp-row="s1"]')?.textContent).toContain('fcm.googleapis.com');
        expect(document.querySelector('[data-wp-row="s1"]')?.textContent).toContain('201');
    });

    test('a plain browser tab hides alerts on and says to install', async () => {
        await render({ supported: true, standalone: false });
        expect(document.querySelector('[data-wp="on"]')).toBeNull();
        expect(document.querySelector('[data-wp="install-hint"]')).not.toBeNull();
    });

    test('send test posts to /push/test and reports the count', async () => {
        const calls = await render({ supported: false, standalone: false });
        (document.querySelector('[data-wp="test"]') as HTMLButtonElement).click();
        await new Promise((resolve) => setTimeout(resolve, 10));
        await tick();
        flushSync();
        expect(calls).toContain('POST /push/test');
        expect(document.querySelector('[data-wp="note"]')?.textContent).toContain('1');
    });
});
