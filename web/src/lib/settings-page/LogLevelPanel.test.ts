/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import LogLevelPanel from './LogLevelPanel.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

interface Call { method: string; body: { level: string | null } | null }

function harness(level = 'info', source: 'setting' | 'env' = 'env') {
    const state = { level, source, env_level: 'info', choices: ['error', 'warn', 'info', 'debug'], expires_at: null as string | null };
    const calls: Call[] = [];
    const fetcher = (async (_path: string, init?: RequestInit) => {
        const body = init?.body ? JSON.parse(String(init.body)) : null;
        calls.push({ method: init?.method ?? 'GET', body });
        if (body) {
            state.level = body.level ?? state.env_level;
            state.source = body.level ? 'setting' : 'env';
        }
        return structuredClone(state);
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
    mounted.push(mount(LogLevelPanel, { target, props: { fetcher: h.fetcher } }));
    await settle();
    return target;
}

const cards = (root: HTMLElement) => [...root.querySelectorAll<HTMLInputElement>('input[type="radio"]')];

describe('LogLevelPanel', () => {
    test('shows the four levels with the one in force checked, and no reset while on env', async () => {
        const root = await render(harness());
        expect(cards(root).map((c) => String(c.checked))).toEqual(['false', 'false', 'true', 'false']);
        expect(root.querySelector('[data-log-level="reset"]')).toBeNull();
        expect(root.querySelector('[data-log-level="source"]')!.textContent).toContain('LOG_LEVEL');
    });

    test('clicking debug PUTs it and shows what the server holds, with the reset button', async () => {
        const h = harness();
        const root = await render(h);
        cards(root)[3]!.click();
        await settle();
        expect(h.calls.at(-1)).toEqual({ method: 'PUT', body: { level: 'debug' } });
        expect(cards(root)[3]!.checked).toBe(true);
        expect(root.querySelector('[data-log-level="reset"]')).not.toBeNull();
    });

    test('reset sends null and returns to the env level', async () => {
        const h = harness('debug', 'setting');
        const root = await render(h);
        root.querySelector<HTMLElement>('[data-log-level="reset"]')!.click();
        await settle();
        expect(h.calls.at(-1)).toEqual({ method: 'PUT', body: { level: null } });
        expect(cards(root)[2]!.checked).toBe(true);
        expect(root.querySelector('[data-log-level="reset"]')).toBeNull();
    });

    test('a failed read is said, not swallowed', async () => {
        const fetcher = (async () => { throw new Error('boom'); }) as never;
        const target = document.createElement('div');
        document.body.append(target);
        mounted.push(mount(LogLevelPanel, { target, props: { fetcher } }));
        await settle();
        expect(target.querySelector('[role="alert"]')!.textContent).toContain('boom');
    });

    test('a temporary debug says "debug until" and the panel re-reads the level once it has expired (#1897)', async () => {
        const h = harness('info');
        const real = h.fetcher as unknown as (path: string, init?: RequestInit) => Promise<Record<string, unknown>>;
        let reads = 0;
        const fetcher = (async (path: string, init?: RequestInit) => {
            reads += 1;
            if (reads === 1) {
                return { level: 'debug', source: 'env', env_level: 'info', choices: ['error', 'warn', 'info', 'debug'],
                    expires_at: new Date(Date.now() + 100).toISOString() };
            }
            return real(path, init);
        }) as never;
        const target = document.createElement('div');
        document.body.append(target);
        mounted.push(mount(LogLevelPanel, { target, props: { fetcher } }));
        await settle();
        expect(cards(target).map((c) => String(c.checked))).toEqual(['false', 'false', 'false', 'true']);
        expect(target.querySelector('[data-log-level="expires"]')!.textContent).toMatch(/debug until \d\d:\d\d/);
        expect(target.querySelector('[data-log-level="reset"]')).not.toBeNull();
        await new Promise((resolve) => setTimeout(resolve, 1400));
        await settle();
        expect(reads).toBe(2);
        expect(cards(target).map((c) => String(c.checked))).toEqual(['false', 'false', 'true', 'false']);
        expect(target.querySelector('[data-log-level="expires"]')).toBeNull();
    });
});
