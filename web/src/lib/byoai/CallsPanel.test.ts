/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import CallsPanel from './CallsPanel.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { Fetcher } from './api';

setLocale('en');

const NOW = Date.now() / 1000;
const row = (id: number, over: Record<string, unknown> = {}) => ({
    id, ts: NOW - id * 60, feature: 'pack.placement.enhanced', capability: 'chat', connection_id: 'local-1', preset: 'ollama',
    model: '~anthropic/claude-sonnet-4.5', ok: 1, latency_ms: 1234, input_tokens: 378, output_tokens: 1800, cost_usd: 0.0012, error: null, ...over,
});
const SUMMARY = {
    range: '24h', calls: 3, errors: 1, spend: 0.0036, tokens_in: 1134, tokens_out: 5400, median_ms: 1234, p95_ms: 1234,
    by_feature: [{ key: 'pack.placement.enhanced', calls: 3, spend: 0.0036 }], by_model: [{ key: '~anthropic/claude-sonnet-4.5', calls: 3, spend: 0.0036 }],
    options: { feature: ['pack.placement.enhanced'], connection: ['local-1'], model: ['~anthropic/claude-sonnet-4.5'] },
};

function harness() {
    const paths: string[] = [];
    const fetcher = (async (path: string) => {
        paths.push(path);
        if (path === '/ai/presets') return { presets: [] };
        if (path === '/ai/connections') return { revision: 1, connections: [{ id: 'local-1', label: 'llm-a' }], defaults: {}, features: {} };
        if (path === '/ai/features') return { features: [{ id: 'pack.placement.enhanced', capability: 'chat', label_key: 'ai.feature.pack_placement', description_key: null, target: null }] };
        if (path.startsWith('/ai/calls/summary')) return SUMMARY;
        if (path.startsWith('/ai/calls')) {
            if (path.includes('before=2')) return { calls: [row(1)], total: 3, start: 3, latest: 1, next: null, prev: 1 };
            if (path.includes('result=error')) return { calls: [row(2, { ok: 0, error: '401 unauthorized\nmore' })], total: 1, start: 1, latest: 2, next: null, prev: null };
            return { calls: [row(2, { ok: 0, error: '401 unauthorized\nmore' }), row(3)], total: 3, start: 1, latest: 3, next: 2, prev: null };
        }
        return {};
    }) as unknown as Fetcher;
    return { fetcher, paths };
}

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const m of mounted.splice(0)) await unmount(m);
    document.body.replaceChildren();
});
async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}
const $ = (sel: string): HTMLElement => document.body.querySelector<HTMLElement>(sel)!;

describe('ai recent calls', () => {
    test('reads as names, pages on the server, filters in the query and expands a row', async () => {
        const h = harness();
        mounted.push(mount(CallsPanel, { target: document.body, props: { fetcher: h.fetcher } }));
        await settle();
        expect(document.body.textContent).toContain('today');
        expect($('[data-ai-call="3"] [data-ai-cell="feature"]').textContent).toBe('pack placement');
        expect($('[data-ai-call="3"] [data-ai-cell="model"]').textContent).toContain('claude-sonnet-4.5');
        expect($('[data-ai-call="3"] [data-ai-cell="tokens"]').textContent).toBe('378 in / 1.8k out');
        expect($('[data-ai-call="2"] [data-ai-cell="error"]').textContent).toBe('401 unauthorized');
        expect($('[data-ai="calls-count"]').textContent).toBe('1 to 2 of 3');
        expect(($('[data-ai="calls-newer"]') as HTMLButtonElement).disabled).toBe(true);

        $('[data-ai-call="3"] .ai-row').click();
        await settle();
        expect($('[data-ai="calls-detail"]').textContent).toContain('pack.placement.enhanced');

        $('[data-ai="calls-older"]').click();
        await settle();
        expect(h.paths.some((p) => p.includes('before=2'))).toBe(true);
        expect($('[data-ai="calls-count"]').textContent).toBe('3 to 3 of 3');

        $('[data-ai-result="error"]').click();
        await settle();
        expect(h.paths.at(-2)).toContain('result=error');
        expect($('[data-ai="calls-count"]').textContent).toBe('1 to 1 of 1');
        expect($('[data-ai="calls-clear"]')).toBeTruthy();
    });
});
