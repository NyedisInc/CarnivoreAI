/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Queue from './Queue.svelte';
import { AdminApi, type Fetcher, type Me } from './admin.js';
import { QUEUE_STATUSES } from './queue-stage.js';
import { createHost, createTokenStore } from './admin-host.svelte.js';

const ADMIN: Me = { user_id: 'u1', login: 'a@example.test', provider: 'email', email: 'a@example.test', is_admin: true };

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
});

async function paint(submissions: (status: string) => { status: number; body: unknown }) {
    const stats = { submissionCalls: 0, inFlight: 0, maxInFlight: 0 };
    const fetcher: Fetcher = async (url) => {
        if (url.endsWith('/v1/me')) return { ok: true, status: 200, json: async () => ADMIN };
        stats.submissionCalls += 1;
        stats.inFlight += 1;
        stats.maxInFlight = Math.max(stats.maxInFlight, stats.inFlight);
        await new Promise((resolve) => setTimeout(resolve, 2));
        stats.inFlight -= 1;
        const answer = submissions(new URL(url).searchParams.get('status') || '');
        return { ok: answer.status < 300, status: answer.status, json: async () => answer.body };
    };
    const tokens = createTokenStore(globalThis);
    tokens.write('tok');
    const host = createHost({ api: new AdminApi(fetcher, () => tokens.read()), tokens });
    await host.adopt();
    mounted = mount(Queue, { target: document.body, props: { host } });
    flushSync();
    await new Promise((resolve) => setTimeout(resolve, 150));
    return { host, stats };
}

describe('admin auto-load', () => {
    test('a failing queue load is attempted once, not looped', async () => {
        const { host, stats } = await paint(() => ({ status: 500, body: { code: 'boom' } }));
        expect(host.queueLoaded).toBe(false);
        expect(host.refusal).not.toBeNull();
        expect(stats.submissionCalls).toBe(1);
    });

    test('a good queue load never has more than one submissions call in flight', async () => {
        const { host, stats } = await paint((status) => ({ status: 200, body: { status, count: 0, submissions: [] } }));
        expect(host.queueLoaded).toBe(true);
        expect(stats.submissionCalls).toBe(QUEUE_STATUSES.length);
        expect(stats.maxInFlight).toBe(1);
    });
});
