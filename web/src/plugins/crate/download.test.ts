/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { resourcePush } from '../sdk';
import { setLocale } from '../../lib/i18n/index.svelte';
import type { Fetcher } from './crate-api';
import CratePanel from './CratePanel.svelte';

setLocale('en');

const BUNDLE_ID = 'crate-20261017T000000Z-project-1a2b3c4d';
const SUMMARY = { folders: { primary: { path: '/state/crates', state: 'ok', reason: null, free_bytes: 5 }, second: null }, encrypt_default: false, recipients: [], running_job: null, bundles: 1 };
const BUNDLE = { bundle_id: BUNDLE_ID, scope: 'project', label: 'before the move', created_at: '2026-10-17T00:00:00Z', verified_at: null, conversations: 3,
    locations: [{ where: '/state/crates/crate-x.crate', verified_at: null, state: 'present' }] };

const listing = (async (path: string) => (path.startsWith('/cplugs/crate/summary') ? SUMMARY : path.startsWith('/cplugs/crate/bundles') ? { bundles: [BUNDLE] } : { crates: [], imports: [] })) as unknown as Fetcher;

const mounted: Array<Record<string, unknown>> = [];

async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) {
        await Promise.resolve();
        flushSync();
    }
}

beforeEach(() => {
    localStorage.setItem('claude_tunnel_token', 'ACCESS-TOKEN');
    URL.createObjectURL = vi.fn(() => 'blob:x');
    URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
    for (const instance of mounted.splice(0)) unmount(instance);
    document.body.innerHTML = '';
    localStorage.clear();
    vi.unstubAllGlobals();
    resourcePush().store.closed();
});

test('the download button fetches with the bearer token and saves the bytes under the server name', async () => {
    const seen: Array<{ url: string; auth: string | null }> = [];
    vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
        seen.push({ url: String(url), auth: new Headers(init?.headers).get('Authorization') });
        return Promise.resolve(new Response('crate-bytes', { status: 200, headers: { 'Content-Type': 'application/octet-stream', 'Content-Disposition': 'attachment; filename="crate-x.crate"' } }));
    });
    const saved: string[] = [];
    const realCreate = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
        const el = realCreate(tag);
        if (tag === 'a') el.click = () => void saved.push((el as HTMLAnchorElement).download);
        return el;
    }) as typeof document.createElement);

    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(CratePanel as never, { target, props: { fetcher: listing } }) as Record<string, unknown>);
    await settle();
    const control = target.querySelector<HTMLElement>(`[data-crt-download="${BUNDLE_ID}"]`);
    expect(control).not.toBeNull();
    control!.click();
    await settle();
    await new Promise((r) => setTimeout(r, 0));
    const call = seen.find((c) => c.url.includes(`/bundles/${BUNDLE_ID}/download`));
    expect(call, 'a download fetch was made').toBeDefined();
    expect(call!.auth).toBe('Bearer ACCESS-TOKEN');
    expect(saved).toEqual(['crate-x.crate']);
});

test('a refused download shows the row error and re-enables the button', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve(new Response(JSON.stringify({ detail: { code: 'bundle_not_in_folder' } }), { status: 404, headers: { 'Content-Type': 'application/json' } })));
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(CratePanel as never, { target, props: { fetcher: listing } }) as Record<string, unknown>);
    await settle();
    const control = target.querySelector<HTMLButtonElement>(`[data-crt-download="${BUNDLE_ID}"]`)!;
    control.click();
    await settle();
    await new Promise((r) => setTimeout(r, 0));
    await settle();
    expect(target.querySelector('[role="alert"]')).not.toBeNull();
    expect(target.querySelector<HTMLButtonElement>(`[data-crt-download="${BUNDLE_ID}"]`)!.disabled).toBe(false);
});
