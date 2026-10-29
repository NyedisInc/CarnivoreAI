/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Funnel from './Funnel.svelte';
import Users from './Users.svelte';
import { AdminApi, type Fetcher } from './admin.js';
import { createHost, createTokenStore, TOKEN_KEY } from './admin-host.svelte.js';
import { createCommunityHost } from './community-host.svelte.js';

let mounted: Array<Record<string, unknown>> = [];
afterEach(() => {
    for (const m of mounted) unmount(m);
    mounted = [];
    document.body.innerHTML = '';
});

const settle = async () => { for (let i = 0; i < 8; i++) { await new Promise((r) => setTimeout(r, 0)); flushSync(); } };

const ME = { user_id: 'me', login: 'root', provider: 'github', is_admin: true };

async function adminHost(fetcher: Fetcher) {
    window.sessionStorage.setItem(TOKEN_KEY, 't');
    const tokens = createTokenStore(globalThis);
    const api = new AdminApi(fetcher, () => tokens.read());
    const host = createHost({ api, tokens });
    await host.adopt();
    return { api, host };
}

const FIXTURE = {
    days: [
        { date: '2026-10-01', start: { chip: { github: 5, email: 2 } }, proof: { chip: { github: 4 } }, done: { chip: { github: 3 } } },
        { date: '2026-09-30', start: { menu: { github: 1 } }, proof: {}, done: {} },
    ],
};

function router(table: Record<string, unknown>): { fetcher: Fetcher; calls: string[] } {
    const calls: string[] = [];
    const fetcher: Fetcher = async (url, init) => {
        calls.push(`${init?.method || 'GET'} ${url}`);
        const key = Object.keys(table).find((k) => url.includes(k));
        const body = key ? table[key] : {};
        return { ok: true, status: 200, json: async () => body, text: async () => String(body) };
    };
    return { fetcher, calls };
}

describe('funnel tab', () => {
    test('renders per day and per source counts as text', async () => {
        const { fetcher, calls } = router({ '/funnel': FIXTURE });
        mounted.push(mount(Funnel, { target: document.body, props: { api: new AdminApi(fetcher, () => 't') } }));
        await settle();
        expect(calls).toEqual(['GET https://api.carnivore.ai/v1/funnel?days=30']);
        const text = document.body.textContent || '';
        expect(text).toContain('2026-10-01');
        const rows = [...document.querySelectorAll('tbody tr')].map((r) =>
            [...r.querySelectorAll('td')].map((c) => c.textContent?.trim()).join('|'));
        expect(rows).toContain('chip|github|5|4|3');
        expect(rows).toContain('chip|email|2|0|0');
        expect(rows).toContain('2026-10-01|7|4|3');
        expect(document.body.innerHTML).not.toContain('<script');
    });

    test('the source never renders server data as markup', () => {
        for (const f of ['Funnel.svelte', 'Users.svelte']) {
            expect(readFileSync(new URL(f, import.meta.url), 'utf8')).not.toContain('{@html');
        }
    });
});

describe('export news list', () => {
    test('the button calls the audited route and nothing else', async () => {
        const { fetcher, calls } = router({ '/users/news-export': 'email\na@b.c\n', '/me': ME, '/users': { users: [{ user_id: 'u1', login: 'a', news_opt_in: true }] } });
        const { api, host } = await adminHost(fetcher);
        const community = createCommunityHost({ api });
        URL.createObjectURL = vi.fn(() => 'blob:x');
        URL.revokeObjectURL = vi.fn();
        mounted.push(mount(Users, { target: document.body, props: { host, community, api } }));
        await settle();
        expect(document.body.textContent).toContain('news');
        const btn = [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'export news list') as HTMLButtonElement;
        btn.click();
        await settle();
        expect(calls.filter((c) => c.includes('export') || c.includes('news'))).toEqual(['GET https://api.carnivore.ai/v1/users/news-export']);
        expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    });

    test('a refusal says nothing was exported', async () => {
        const fetcher: Fetcher = async (url) => url.includes('news-export')
            ? { ok: false, status: 503, json: async () => ({ error: 'audit_unavailable' }) }
            : { ok: true, status: 200, json: async () => (url.includes('/me') ? ME : { users: [{ user_id: 'u1', login: 'a' }] }) };
        const { api, host } = await adminHost(fetcher);
        URL.createObjectURL = vi.fn(() => 'blob:x');
        mounted.push(mount(Users, { target: document.body, props: { host, community: createCommunityHost({ api }), api } }));
        await settle();
        (([...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'export news list')) as HTMLButtonElement).click();
        await settle();
        expect(document.body.textContent).toContain('nothing was exported.');
        expect(URL.createObjectURL).not.toHaveBeenCalled();
    });
});
