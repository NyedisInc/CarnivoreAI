/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import ArgentWriteback from './ArgentWriteback.svelte';
import { setLocale } from '../../lib/i18n/index.svelte';

setLocale('en');

interface Call { path: string; method: string; body: unknown }

function harness(items: unknown[], failEdit = false) {
    const calls: Call[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        calls.push({ path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null });
        if (failEdit && path.endsWith('/edit')) throw Object.assign(new Error('refused'), { status: 422, payload: { detail: { code: 'blocked_secret' } } });
        return { items };
    }) as never;
    return { fetcher, calls };
}

const WAITING = [{ id: 7, item_title: 'checkout rewrite', session_name: 'api', commits: 2, body: 'checkout rewrite | Ann\'s session api | commits: 2' }];
const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => { for (const c of mounted.splice(0)) await unmount(c); document.body.replaceChildren(); });

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

async function render(h: ReturnType<typeof harness>): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(ArgentWriteback, { target, props: { fetcher: h.fetcher, pollMs: 0 } }));
    await settle();
    return target;
}

const el = (root: HTMLElement, key: string) => root.querySelector<HTMLElement>(`[data-argent="${key}"]`);

describe('ArgentWriteback', () => {
    test('draws nothing while no comment waits', async () => {
        expect(el(await render(harness([])), 'writeback')).toBeNull();
    });

    test('approve sends the edited text first, then approves; discard posts discard', async () => {
        const h = harness(WAITING);
        const root = await render(h);
        expect(el(root, 'writeback-row')!.textContent).toBe('checkout rewrite: session api, 2 commits');
        const box = root.querySelector<HTMLTextAreaElement>('textarea')!;
        box.value = 'edited by hand';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        (el(root, 'writeback-approve') as HTMLButtonElement).click();
        await settle();
        expect(h.calls.filter((c) => c.method === 'POST')).toEqual([
            { path: '/argent/writeback/7/edit', method: 'POST', body: { body: 'edited by hand' } },
            { path: '/argent/writeback/7/approve', method: 'POST', body: null },
        ]);
        (el(root, 'writeback-discard') as HTMLButtonElement).click();
        await settle();
        expect(h.calls.at(-2)).toEqual({ path: '/argent/writeback/7/discard', method: 'POST', body: null });
    });

    test('an edit the server refuses for a secret shows the plain sentence and does not approve', async () => {
        const h = harness(WAITING, true);
        const root = await render(h);
        const box = root.querySelector<HTMLTextAreaElement>('textarea')!;
        box.value = 'oops';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        (el(root, 'writeback-approve') as HTMLButtonElement).click();
        await settle();
        expect(el(root, 'writeback-problem')!.textContent).toContain('looks like it holds a credential');
        expect(h.calls.some((c) => c.path.endsWith('/approve'))).toBe(false);
    });
});
