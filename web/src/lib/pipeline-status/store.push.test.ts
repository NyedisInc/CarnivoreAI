import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/** A localStorage that holds a token, so the auth gate reads signed in. */
function signedInStorage() {
    const map = new Map<string, string>([['claude_tunnel_token', 'an-access-token']]);
    return {
        getItem: (k: string): string | null => map.get(k) ?? null,
        setItem: (k: string, v: string): void => void map.set(k, v),
        removeItem: (k: string): void => void map.delete(k),
    };
}

beforeEach(() => {
    vi.useFakeTimers();
    (globalThis as { localStorage?: unknown }).localStorage = signedInStorage();
    vi.resetModules();
});

afterEach(() => {
    vi.useRealTimers();
    delete (globalThis as { localStorage?: unknown }).localStorage;
    delete (globalThis as { ResourcePush?: unknown }).ResourcePush;
});

async function load() {
    const store = await import('./store.svelte');
    const { resourcePush } = await import('../resource-push/boot');
    const reads: string[] = [];
    const fetcher = (async (path: string) => {
        reads.push(path);
        return { state: 'caught_up', lag: { files: 0, seconds: 0 }, plugins: {}, recent: [] };
    }) as never;
    return { store, push: resourcePush().store, reads, fetcher };
}

describe('the pipeline status read', () => {
    it('answers the pipeline topic', async () => {
        const { store } = await load();
        expect(store.PIPELINE_STATUS_TOPICS).toEqual(['pipeline']);
    });

    it('stops polling while the topic is live, re-reads on a frame naming it, and polls again when the socket drops', async () => {
        const { store, push, reads, fetcher } = await load();
        const { status, release } = store.acquireStatus(fetcher);
        await vi.advanceTimersByTimeAsync(0);
        expect(reads).toHaveLength(1);

        push.hello({ resource_topics: [] });
        await vi.advanceTimersByTimeAsync(store.PIPELINE_STATUS_POLL_MS * 2);
        const polled = reads.length;
        expect(polled).toBeGreaterThanOrEqual(3);

        push.hello({ resource_topics: ['pipeline'] });
        await vi.advanceTimersByTimeAsync(0);
        const afterHello = reads.length;
        await vi.advanceTimersByTimeAsync(store.PIPELINE_STATUS_POLL_MS * 6);
        expect(reads).toHaveLength(afterHello);

        push.frame({ topics: ['automations'] });
        await vi.advanceTimersByTimeAsync(0);
        expect(reads).toHaveLength(afterHello); // another topic reads nothing

        push.frame({ topics: ['pipeline'] });
        await vi.advanceTimersByTimeAsync(0);
        expect(reads).toHaveLength(afterHello + 1);
        expect(status.data?.recent).toEqual([]);

        push.closed();
        await vi.advanceTimersByTimeAsync(store.PIPELINE_STATUS_POLL_MS * 2);
        expect(reads.length).toBeGreaterThan(afterHello + 1);
        release();
    });
});
