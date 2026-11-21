/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import ArgentSettings from './ArgentSettings.svelte';
import { setLocale } from '../../lib/i18n/index.svelte';

setLocale('en');

interface Call { path: string; method: string; body: unknown }

function harness(over: Record<string, unknown> = {}, refuse = false) {
    const status = {
        feature_on: true,
        settings: { server_url: 'https://cp.example', gateway_url: 'https://gw.example', ca_path: '', enabled: false, refuse_direct_launch: false },
        state: 'up', refusal: null,
        login: { state: 'logged_in', display_name: 'Fixture Person', flow: { state: 'idle' } },
        ...over,
    };
    const calls: Call[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        const body = init?.body ? JSON.parse(String(init.body)) : null;
        calls.push({ path, method: init?.method ?? 'GET', body });
        if (path === '/argent/rollout/preview') return { enabled: true, direction: 'on', total: 0, tethered: 0, pending: 0, will_restart: 0, adopted: 0, subagents: 0, background: 0, excluded: {}, reasons: {} };
        if (path === '/argent/rollout') return { enabled: true, state: 'none', direction: '', epoch: 0, reason: '', counts: {}, reasons: {}, rows: [] };
        if (path === '/argent/settings' && init?.method === 'PUT') {
            if (refuse) throw Object.assign(new Error('refused'), { status: 409 });
            Object.assign(status.settings, body);
        }
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
    mounted.push(mount(ArgentSettings, { target, props: { fetcher: h.fetcher, pollMs: 0 } }));
    await settle();
    return target;
}

const el = (root: HTMLElement, key: string) => root.querySelector<HTMLElement>(`[data-argent="${key}"]`);

describe('ArgentSettings', () => {
    test('shows the state, the login and the switch OFF by default, with no word plugin', async () => {
        const root = await render(harness());
        expect(el(root, 'state')!.textContent).toContain('the gateway is up');
        expect(el(root, 'login')!.textContent).toContain('logged in as Fixture Person');
        expect(el(root, 'switch')!.getAttribute('aria-checked')).toBe('false');
        expect(root.textContent!.toLowerCase()).not.toContain('plugin');
    });

    test('flipping the switch PUTs enabled true and shows it on', async () => {
        const h = harness();
        const root = await render(h);
        el(root, 'switch')!.click();
        await settle();
        expect(h.calls.find((c) => c.method === 'PUT')).toEqual({ path: '/argent/settings', method: 'PUT', body: { enabled: true } });
        expect(el(root, 'switch')!.getAttribute('aria-checked')).toBe('true');
        expect(document.querySelector('[data-argent="rollout"]')).not.toBeNull();
    });

    test('a refused switch stays off and says something', async () => {
        const root = await render(harness({}, true));
        el(root, 'switch')!.click();
        await settle();
        expect(el(root, 'switch')!.getAttribute('aria-checked')).toBe('false');
        expect(el(root, 'problem')).not.toBeNull();
        expect(document.querySelector('[data-argent="rollout"]')).toBeNull();
    });

    test('a named refusal from the status is shown in plain words', async () => {
        const root = await render(harness({ state: 'cap_too_low', refusal: { code: 'cap_too_low', message: 'x' } }));
        expect(el(root, 'refusal')!.textContent).toContain('the gateway body cap is too low');
    });

    test('log in starts the device login, and a pending login shows its code and address', async () => {
        const h = harness({ login: { state: 'logged_out', display_name: '', flow: { state: 'idle' } } });
        const root = await render(h);
        el(root, 'log-in')!.click();
        await settle();
        expect(h.calls.some((c) => c.path === '/argent/login/start' && c.method === 'POST')).toBe(true);
        const pending = await render(harness({ login: { state: 'pending', display_name: '', flow: { state: 'pending', user_code: 'ABCD-EFGH', verification_uri: 'https://cp.example/device?user_code=ABCD-EFGH' } } }));
        expect(el(pending, 'code')!.textContent).toContain('ABCD-EFGH');
        expect(el(pending, 'link')!.getAttribute('href')).toContain('/device');
    });
});
