/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import ProviderCard from './ProviderCard.svelte';
import type { Binding, Conversation, Fetcher, Provider } from './api';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);

const provider = {
    id: 'p1', name: 'Bridge', enabled: true,
    stream: { state: 'live', cursor: 0, gap: null, last_event_at: null, last_inbound_at: null, last_outbound_at: null, bridge: null, flow: 'flowing' },
    secrets: {}, idempotency: { proven: false, last_proven_at: null },
} as unknown as Provider;
const conversations = [{ id: 'c1', provider_id: 'p1', label: 'Family chat' }] as unknown as Conversation[];
const bindings = [
    { id: 'b1', conversation_id: 'c1' }, { id: 'b2', conversation_id: 'c1' }, { id: 'b3', conversation_id: 'other' },
] as unknown as Binding[];

let mounted: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (mounted) void unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

function card(calls: string[]): HTMLElement {
    const fetcher = (async (path: string, init?: { method?: string }) => {
        calls.push(`${init?.method ?? 'GET'} ${path}`);
        return {};
    }) as unknown as Fetcher;
    const act = async (work: () => Promise<void>): Promise<boolean> => { await work(); return true; };
    mounted = mount(ProviderCard, { target: document.body, props: { t, provider, conversations, bindings, busy: false, act, fetcher } });
    flushSync();
    return document.body;
}

const q = (sel: string): HTMLElement | null => document.body.querySelector<HTMLElement>(sel);

describe('conversation removal', () => {
    it('the first click deletes nothing; it names the bindings that go with the conversation', () => {
        const calls: string[] = [];
        card(calls);
        q('[data-messaging="conversation-remove"]')!.click();
        flushSync();
        expect(calls.filter((c) => c.startsWith('DELETE'))).toEqual([]);
        expect(q('[data-messaging="conversation-remove-confirm"]')!.textContent).toContain('2');
    });

    it('cancel puts the plain remove button back and deletes nothing', () => {
        const calls: string[] = [];
        card(calls);
        q('[data-messaging="conversation-remove"]')!.click();
        flushSync();
        q('[data-messaging="conversation-remove-cancel"]')!.click();
        flushSync();
        expect(q('[data-messaging="conversation-remove"]')).not.toBeNull();
        expect(calls).toEqual([]);
    });

    it('the second click sends the delete once', async () => {
        const calls: string[] = [];
        card(calls);
        q('[data-messaging="conversation-remove"]')!.click();
        flushSync();
        q('[data-messaging="conversation-remove-confirm"]')!.click();
        await vi.waitFor(() => expect(calls.filter((c) => c.startsWith('DELETE'))).toHaveLength(1));
    });
});
