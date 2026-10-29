/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { DEBOUNCE_MS, DeepSearchController } from './deepsearch.svelte';
import { readAnswer, type DeepAnswer, type DeepSearchApi } from './deepsearch-api';

const group = (id: string, extra: Record<string, unknown> = {}) => ({
    conversation_id: id, matches: 1, hits: [{ line: 1, kind: 'user', snippet: `hit \u0002flux\u0003 ${id}`, file_kind: 'conversation' }], ...extra,
});

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

test('local hits are on screen before a slow computer answers, then its conversations merge in, tagged and deduped', async () => {
    let releasePeers!: (a: DeepAnswer) => void;
    const peers = new Promise<DeepAnswer>((resolve) => { releasePeers = resolve; });
    const api: DeepSearchApi = {
        search: async () => readAnswer({ query: 'flux', total_conversations: 2, groups: [group('c1'), group('c2')] }),
        peers: () => peers,
    };
    const controller = new DeepSearchController(api, async () => 'none');
    controller.query = 'flux';
    controller.onType();
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS + 1);

    expect(controller.phase).toBe('done');
    expect(controller.groups.map((g) => g.conversationId)).toEqual(['c1', 'c2']);

    releasePeers(readAnswer({
        total_conversations: 2, total_matches: 2,
        groups: [group('c2', { host_key: 'peer-studio', host_label: 'studio' }), group('c3', { host_key: 'peer-studio', host_label: 'studio' })],
        peer_unavailable: [{ host_key: 'peer-lap', host_label: 'laptop', reason: 'not_ready' }],
    }));
    await vi.advanceTimersByTimeAsync(0);

    expect(controller.groups.map((g) => g.conversationId)).toEqual(['c1', 'c3', 'c2']);
    expect(controller.groups.find((g) => g.conversationId === 'c2')!.alsoOn).toEqual(['studio']);
    expect(controller.groups.find((g) => g.conversationId === 'c3')!.hostLabel).toBe('studio');
    expect(controller.total).toBe(3);
    expect(controller.peerDown).toEqual([{ hostKey: 'peer-lap', label: 'laptop', notReady: true }]);
});

test('a peers call that fails leaves the local results alone', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const api: DeepSearchApi = {
        search: async () => readAnswer({ query: 'flux', total_conversations: 1, groups: [group('c1')] }),
        peers: async () => { throw new Error('down'); },
    };
    const controller = new DeepSearchController(api, async () => 'none');
    controller.query = 'flux';
    controller.onType();
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS + 1);
    expect(controller.phase).toBe('done');
    expect(controller.groups.map((g) => g.conversationId)).toEqual(['c1']);
});

test('show more does not drop the paired computers answer to the first page (u136-01)', async () => {
    let releasePeers!: (a: DeepAnswer) => void;
    const peers = new Promise<DeepAnswer>((resolve) => { releasePeers = resolve; });
    let peerSignal: AbortSignal | null = null;
    const many = Array.from({ length: 20 }, (_, i) => group(`c${i}`));
    const api: DeepSearchApi = {
        search: async (_q, offset) => readAnswer({ query: 'flux', total_conversations: 40, groups: offset === 0 ? many : [group('c30')] }),
        peers: (_q, signal) => { peerSignal = signal; return peers; },
    };
    const controller = new DeepSearchController(api, async () => 'none');
    controller.query = 'flux';
    controller.onType();
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS + 1);
    await controller.more();
    expect(peerSignal!.aborted).toBe(false);
    releasePeers(readAnswer({ total_conversations: 1, total_matches: 1, groups: [group('p1', { host_key: 'peer-studio', host_label: 'studio' })] }));
    await vi.advanceTimersByTimeAsync(0);
    expect(controller.groups.map((g) => g.conversationId)).toContain('p1');
});

test('a new query still retires the old peers request (u136-01)', async () => {
    let first: AbortSignal | null = null;
    const api: DeepSearchApi = {
        search: async () => readAnswer({ query: 'flux', total_conversations: 1, groups: [group('c1')] }),
        peers: (_q, signal) => { first ??= signal; return new Promise<DeepAnswer>(() => {}); },
    };
    const controller = new DeepSearchController(api, async () => 'none');
    controller.query = 'flux';
    controller.onType();
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS + 1);
    controller.query = 'fluxx';
    controller.onType();
    expect(first!.aborted).toBe(true);
});
