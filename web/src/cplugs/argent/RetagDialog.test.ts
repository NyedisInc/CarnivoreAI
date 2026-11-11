/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import RetagDialog from './RetagDialog.svelte';
import { setLocale } from '../../lib/i18n/index.svelte';

setLocale('en');

interface Call { path: string; method: string; body: unknown }

function harness(failWith = '') {
    const calls: Call[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        calls.push({ path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null });
        if (path === '/sessions/list') return [{ session: { id: 'ses_1' }, label: 'api', tmux_session: 'carnivore_api' }, { session: { id: 'remote:p:x' }, label: 'far', host_key: 'peer-1' }];
        if (path === '/argent/work-items') return { items: [{ id: 'wi_s2', kind: 'story', title: 'second story' }] };
        if (failWith) throw Object.assign(new Error('refused'), { status: 422, payload: { detail: { code: failWith } } });
        return { moved_micros: 450000 };
    }) as never;
    return { fetcher, calls };
}

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => { for (const c of mounted.splice(0)) await unmount(c); document.body.replaceChildren(); });

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

async function open(h: ReturnType<typeof harness>): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(RetagDialog, { target, props: { fetcher: h.fetcher } }));
    await settle();
    (target.querySelector('[data-argent="retag-open"]') as HTMLButtonElement).click();
    await settle();
    return target;
}

function fill(target: HTMLElement, selector: string, value: string): void {
    const el = target.querySelector(selector) as HTMLInputElement | HTMLSelectElement;
    el.value = value;
    el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
}

async function fillAll(target: HTMLElement, reason: string): Promise<void> {
    fill(target, '[data-argent="retag-session"]', 'ses_1');
    fill(target, '[data-argent="retag-item"]', 'wi_s2');
    fill(target, '[data-argent="retag-since"]', '2026-11-01T10:00');
    fill(target, '[data-argent="retag-until"]', '2026-11-02T10:00');
    fill(target, '[data-argent="retag-reason"]', reason);
    await settle();
}

describe('RetagDialog', () => {
    test('is folded until asked and reads nothing before that', async () => {
        const h = harness();
        const target = document.createElement('div');
        document.body.append(target);
        mounted.push(mount(RetagDialog, { target, props: { fetcher: h.fetcher } }));
        await settle();
        expect(target.querySelector('[data-argent="retag-send"]')).toBeNull();
        expect(h.calls).toEqual([]);
    });

    test('lists only this computer\'s sessions, waits for every field, then posts the window and ids', async () => {
        const h = harness();
        const target = await open(h);
        const sessions = [...target.querySelectorAll('[data-argent="retag-session"] option')].map((o) => (o as HTMLOptionElement).value);
        expect(sessions).toEqual(['', 'ses_1']);
        const send = target.querySelector('[data-argent="retag-send"]') as HTMLButtonElement;
        await fillAll(target, 'ab');
        expect(send.disabled).toBe(true);
        await fillAll(target, 'wrong story picked');
        expect(send.disabled).toBe(false);
        send.click();
        await settle();
        const post = h.calls.find((c) => c.path === '/argent/retag')!;
        const body = post.body as Record<string, string>;
        expect(post.method).toBe('POST');
        expect(body).toMatchObject({ session_id: 'ses_1', work_item_id: 'wi_s2', reason: 'wrong story picked' });
        expect(body.since).toBe(new Date('2026-11-01T10:00').toISOString());
        expect(target.querySelector('[data-argent="retag-said"]')?.textContent).toContain('$0.45');
    });

    test('a refusal is shown in plain words by its code', async () => {
        const target = await open(harness('range_too_long'));
        await fillAll(target, 'wrong story picked');
        (target.querySelector('[data-argent="retag-send"]') as HTMLButtonElement).click();
        await settle();
        expect(target.querySelector('[data-argent="retag-problem"]')?.textContent).toContain('longer than 31 days');
    });
});
