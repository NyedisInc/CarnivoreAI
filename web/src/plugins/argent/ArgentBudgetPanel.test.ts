/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import ArgentBudgetPanel from './ArgentBudgetPanel.svelte';
import { formatMicros } from '../../lib/argent-cost/money';
import { setLocale } from '../../lib/i18n/index.svelte';

setLocale('en');

interface Call { path: string; method: string; body: unknown }

function harness(items: Record<string, unknown>, failWith?: number, code?: string, requests: unknown[] = []) {
    const calls: Call[] = [];
    const h = { calls, lift: {} as unknown, fetcher: null as never };
    const fetcher = (async (path: string, init?: RequestInit) => {
        calls.push({ path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null });
        if (init?.method === 'POST' && failWith) throw Object.assign(new Error('refused'), { status: failWith, code });
        if (init?.method === 'POST' && path.endsWith('/requests')) return { id: 'br_1', state: 'pending', requested_micros: 10_000_000 };
        if (path === '/argent/budget/requests') return { enabled: true, requests };
        return init?.method === 'POST' && path.endsWith('/lift') ? h.lift : { items };
    }) as never;
    h.fetcher = fetcher;
    return h;
}

const HELD = { wi_1: { name: 'checkout rewrite', held: true, budget: { state: 'paused', spent_micros: 10_000_000, cap_micros: 10_000_000, owner_name: 'Fixture Owner', effective_spent_micros: 10_000_000 } } };
const mounted: ReturnType<typeof mount>[] = [];
async function unmountAll(): Promise<void> { for (const c of mounted.splice(0)) await unmount(c); document.body.replaceChildren(); }
afterEach(unmountAll);

async function render(h: ReturnType<typeof harness>, open: (url: string) => void = () => {}): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(ArgentBudgetPanel, { target, props: { fetcher: h.fetcher, pollMs: 0, open } }));
    for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
    return target;
}

const el = (root: HTMLElement, key: string) => root.querySelector<HTMLElement>(`[data-argent="${key}"]`);

function type(root: HTMLElement, selector: string, text: string): void {
    const box = root.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector)!;
    box.value = text;
    box.dispatchEvent(new Event('input', { bubbles: true }));
}

describe('ArgentBudgetPanel', () => {
    test('draws nothing while no item is held, even with budgets near the cap', async () => {
        const root = await render(harness({ wi_1: { name: 'x', held: false, budget: { state: 'warn', spent_micros: 8, cap_micros: 10, owner_name: 'o', effective_spent_micros: 8 } } }));
        expect(el(root, 'budgets')).toBeNull();
    });

    test('a held item shows spend, cap and owner; ask posts the request; lift in argent asks where and opens the url', async () => {
        const h = harness(HELD);
        const opened: string[] = [];
        const root = await render(h, (url) => opened.push(url));
        expect(el(root, 'budget-row')!.textContent!.trim()).toBe('checkout rewrite: spent $10.00 of $10.00, budget owner Fixture Owner');
        expect(el(root, 'raise')).toBeNull();
        expect(el(root, 'overage')).toBeNull();
        (el(root, 'ask') as HTMLButtonElement).click();
        await settle();
        expect(h.calls.filter((c) => c.method === 'POST')).toEqual([]);
        expect((root.querySelector('[data-argent-ask-amount]') as HTMLInputElement).value).toBe('');
        type(root, '[data-argent-ask-amount]', '10');
        type(root, '[data-argent-ask-reason]', '  release week  ');
        await settle();
        (root.querySelector('[data-argent-ask-send]') as HTMLButtonElement).click();
        await settle();
        expect(h.calls.filter((c) => c.method === 'POST').at(-1)).toEqual({ path: '/argent/budget/requests', method: 'POST', body: { item_id: 'wi_1', amount_micros: 10_000_000, reason: 'release week' } });
        expect(root.querySelector('[data-argent-asked]')!.textContent).toBe('asked $10.00 more; waiting on Fixture Owner');
        h.lift = { lift_in_argent: true, url: 'https://argent.test/work/items?sel=wi_1' };
        (el(root, 'lift') as HTMLButtonElement).click();
        await settle();
        expect(h.calls.at(-1)).toEqual({ path: '/argent/budget/lift', method: 'POST', body: { item_id: 'wi_1' } });
        expect(opened).toEqual(['https://argent.test/work/items?sel=wi_1']);
    });

    test('a refused ask says it is not available yet, never sent', async () => {
        const h = harness(HELD, 501, 'budget_request_unavailable');
        const root = await render(h);
        (el(root, 'ask') as HTMLButtonElement).click();
        await settle();
        type(root, '[data-argent-ask-amount]', '5');
        type(root, '[data-argent-ask-reason]', 'release week');
        await settle();
        (root.querySelector('[data-argent-ask-send]') as HTMLButtonElement).click();
        await settle();
        expect(root.querySelector('[data-argent-ask-said]')!.textContent).toBe('asking for more budget is not available yet; ask Fixture Owner in argent');
        expect(root.textContent).not.toContain('sent to argent');
    });

    test('a pending ask shows asked and waiting in place of the form; the notice link opens the form on its item', async () => {
        const pending = [{ id: 'br_1', item_id: 'wi_1', requested_micros: 4_000_000, approved_micros: null, state: 'pending', decision_reason: '', created_at: 1, decided_at: null }];
        const root = await render(harness(HELD, undefined, undefined, pending));
        expect(root.querySelector('[data-argent-asked]')!.textContent).toBe('asked $4.00 more; waiting on Fixture Owner');
        expect(el(root, 'ask')).toBeNull();
        await unmountAll();
        window.location.hash = '#settings/features/argent/settings?ask=wi_1';
        try {
            const opened = await render(harness(HELD));
            expect(opened.querySelector('[data-argent-ask-form]')).not.toBeNull();
            const other = await render(harness({ ...HELD, wi_2: { ...HELD.wi_1, name: 'other' } }));
            expect(other.querySelectorAll('[data-argent-ask-form]').length).toBe(1);
        } finally {
            window.location.hash = '';
        }
    });

    test('a non-owner sees what governs the hold, and lift uses the governing id; no url says lift it in argent', async () => {
        const h = harness({ wi_1: { name: 'child', held: true, budget: { state: 'paused', spent_micros: null, cap_micros: null, owner_name: '', effective_spent_micros: null,
            governing_item_id: 'wi_gov1', governing_item_title: 'Platform migration' } } });
        const opened: string[] = [];
        const root = await render(h, (url) => opened.push(url));
        expect(el(root, 'budget-row')!.textContent!.trim()).toBe('child: paused by Platform migration');
        h.lift = { lift_in_argent: true, url: null };
        (el(root, 'lift') as HTMLButtonElement).click();
        await settle();
        expect(h.calls.at(-1)!.body).toEqual({ item_id: 'wi_gov1' });
        expect(opened).toEqual([]);
        expect(el(root, 'said')!.textContent).toBe('lift it in argent');
    });

    test('money format: four decimals under a dollar, a dash for unmeasured, never $0.00 for a nonzero amount', () => {
        expect([null, 0, 1, 20_000, 999_999, 1_234_500, 1_234_567_890].map(formatMicros)).toEqual(['-', '$0.00', '$0.0001', '$0.02', '$1.00', '$1.23', '$1,234.57']);
    });
});

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}
