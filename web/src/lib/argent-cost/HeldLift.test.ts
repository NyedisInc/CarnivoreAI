/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import HeldLift from './HeldLift.svelte';
import { cardCostView, type ArgentCostSnapshot, type LiftView } from './cost-view';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => { for (const c of mounted.splice(0)) await unmount(c); document.body.replaceChildren(); });

async function render(lift: LiftView, reply: unknown = { lift_in_argent: true, url: 'https://argent.test/work/items?sel=wi_gov1' }) {
    const calls: { path: string; body: unknown }[] = [];
    const opened: string[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        calls.push({ path, body: JSON.parse(String(init?.body)) });
        return reply;
    }) as never;
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(HeldLift, { target, props: { itemId: 'wi_1', lift, fetcher, open: (url: string) => opened.push(url) } }));
    await tick();
    flushSync();
    return { target, calls, opened };
}

async function press(root: HTMLElement, selector: string): Promise<void> {
    root.querySelector<HTMLButtonElement>(selector)!.click();
    for (let i = 0; i < 4; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

const OWNER: LiftView = { isOwner: true, owner: 'Fixture Owner', governingId: 'wi_gov1', governingTitle: 'Platform migration' };
const OTHER: LiftView = { isOwner: false, owner: 'Fixture Owner', governingId: 'wi_gov1', governingTitle: 'Platform migration' };
const UNNAMED: LiftView = { isOwner: false, owner: '', governingId: 'wi_gov1', governingTitle: 'Platform migration' };

test('the owner has one lift in argent button that opens the returned url and posts only the governing item id', async () => {
    const { target, calls, opened } = await render(OWNER);
    expect(target.textContent).toContain('lift in argent');
    expect(target.querySelector('[data-argent-lift-raise]')).toBeNull();
    await press(target, '[data-argent-lift-open]');
    expect(calls).toEqual([{ path: '/argent/budget/lift', body: { item_id: 'wi_gov1' } }]);
    expect(opened).toEqual(['https://argent.test/work/items?sel=wi_gov1']);
});

test('with no url known it says to lift it in argent and opens nothing', async () => {
    const { target, opened } = await render(OWNER, { lift_in_argent: true, url: null });
    await press(target, '[data-argent-lift-open]');
    expect(opened).toEqual([]);
    expect(target.querySelector('[data-argent-lift-said]')?.textContent).toBe('lift it in argent');
});

test('a non-owner gets no lift button, only ask the owner, which sends the budget request', async () => {
    const { target, calls } = await render(OTHER);
    expect(target.querySelector('[data-argent-lift-open]')).toBeNull();
    expect(target.textContent).toContain('ask Fixture Owner');
    await press(target, '[data-argent-lift-ask]');
    expect(calls).toEqual([{ path: '/argent/budget/requests', body: { item_id: 'wi_1' } }]);
});

test('with no owner named, the row says what governs the hold', async () => {
    const { target } = await render(UNNAMED);
    expect(target.querySelector('[data-argent-lift-governing]')?.textContent).toBe('paused by Platform migration');
});

test('the card view reads the owner flag and the governing item from the snapshot', () => {
    const snap = (flag: boolean | null): ArgentCostSnapshot => ({
        enabled: true, state: 'ok', sessions: { '7': { items: ['wi_1'], cost: { cost_micros: 1 } } },
        items: { wi_1: { name: 'story', held: true, budget: { state: 'paused', cap_micros: 10_000_000, owner_name: 'Fixture Owner', viewer_is_owner: flag,
            governing_item_id: 'wi_gov1', governing_item_title: 'Platform migration' } } },
    });
    expect(cardCostView(snap(true), 7)?.items[0].lift).toEqual(OWNER);
    expect(cardCostView(snap(false), 7)?.items[0].lift.isOwner).toBe(false);
    expect(cardCostView(snap(null), 7)?.items[0].lift.isOwner).toBe(false);
});
