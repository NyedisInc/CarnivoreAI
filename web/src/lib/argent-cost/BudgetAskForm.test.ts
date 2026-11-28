/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';

import BudgetAskForm from './BudgetAskForm.svelte';
import { defaultAsk, parseDollars, pendingFor, MAX_ASK_MICROS } from './budget-ask';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => { for (const c of mounted.splice(0)) await unmount(c); document.body.replaceChildren(); });

async function settle(): Promise<void> { for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); } flushSync(); }

async function render(props: Record<string, unknown> = {}, refuse?: unknown) {
  const calls: { path: string; body: Record<string, unknown> }[] = [];
  const sent: number[] = [];
  const fetcher = (async (path: string, init?: RequestInit) => {
    calls.push({ path, body: JSON.parse(String(init?.body)) });
    if (refuse) throw refuse;
    return { id: 'br_1', state: 'pending', requested_micros: 1 };
  }) as never;
  const target = document.createElement('div');
  document.body.append(target);
  const all = { itemId: 'wi_1', capMicros: 10_000_000, owner: 'Fixture Owner', fetcher, onsent: () => sent.push(1) };
  mounted.push(mount(BudgetAskForm, { target, props: Object.defineProperties(all, Object.getOwnPropertyDescriptors(props)) as never }));
  await settle();
  return { target, calls, sent };
}

function type(root: HTMLElement, selector: string, text: string): void {
  const box = root.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector)!;
  box.value = text;
  box.dispatchEvent(new Event('input', { bubbles: true }));
}
async function press(root: HTMLElement, selector: string): Promise<void> { root.querySelector<HTMLButtonElement>(selector)!.click(); await settle(); }

test('dollars become whole micros, anything else is refused (negative controls), and the first suggestion is the overage, never the cap', () => {
  expect(parseDollars('12.5')).toBe(12_500_000);
  expect(parseDollars(' $1,000 ')).toBe(1_000_000_000);
  expect(parseDollars('0.0001')).toBe(100);
  for (const bad of ['', '0', '0.000000', '-5', '1e3', '12.1234567', 'abc', '5 dollars', String(MAX_ASK_MICROS / 1_000_000 + 1)]) expect(parseDollars(bad), bad).toBeNull();
  expect(parseDollars(String(MAX_ASK_MICROS / 1_000_000))).toBe(MAX_ASK_MICROS);
  expect(defaultAsk(10_000_000, 12_500_000, true)).toBe('2.50');
  expect(defaultAsk(10_000_000, 22_345_600, true)).toBe('12.3456');
  expect(defaultAsk(10_000_000, 4_000_000, true)).toBe('');
  expect(defaultAsk(10_000_000, 10_000_000, true)).toBe('');
  expect(defaultAsk(10_000_000, 12_500_000, false)).toBe('');
  expect(defaultAsk(10_000_000)).toBe('');
  expect(defaultAsk(null, 5, true)).toBe('');
  expect(pendingFor([{ id: 'a', item_id: 'wi_1', state: 'approved' } as never], 'wi_1')).toBeNull();
});

test('it validates amount and reason before sending, then sends the agreed body and shows pending', async () => {
  const { target, calls, sent } = await render();
  expect(target.querySelector('[data-argent-ask-form]')).toBeNull();
  await press(target, '[data-argent="ask"]');
  expect((target.querySelector('[data-argent-ask-amount]') as HTMLInputElement).value).toBe('');
  expect(target.textContent).toContain('extra amount (usd)');
  await press(target, '[data-argent-ask-send]');
  expect(calls).toEqual([]);
  expect(target.textContent).toContain('give a reason, up to 500 characters');
  type(target, '[data-argent-ask-reason]', 'x'.repeat(501));
  type(target, '[data-argent-ask-amount]', '0');
  await press(target, '[data-argent-ask-send]');
  expect(calls).toEqual([]);
  expect(target.textContent).toContain('type an amount above zero, up to $1,000,000.00');
  type(target, '[data-argent-ask-reason]', '  release week  ');
  type(target, '[data-argent-ask-amount]', '$7.25');
  await press(target, '[data-argent-ask-send]');
  expect(calls).toEqual([{ path: '/argent/budget/requests', body: { item_id: 'wi_1', amount_micros: 7_250_000, reason: 'release week' } }]);
  expect(target.querySelector('[data-argent-asked]')?.textContent).toBe('asked $7.25 more; waiting on Fixture Owner');
  expect(target.querySelector('[data-argent-ask-form]')).toBeNull();
  expect(sent).toEqual([1]);
});

test('a 409 reads already asked and a 501 reads not available yet, in the catalog words, never Argent text', async () => {
  const pending = await render({}, Object.assign(new Error('SECRET-RAW-TEXT'), { status: 409, code: 'budget_request_pending' }));
  await press(pending.target, '[data-argent="ask"]');
  type(pending.target, '[data-argent-ask-amount]', '5');
  type(pending.target, '[data-argent-ask-reason]', 'release week');
  await press(pending.target, '[data-argent-ask-send]');
  expect(pending.target.querySelector('[data-argent-ask-said]')?.textContent).toBe('already asked; waiting on Fixture Owner');
  expect(pending.sent).toEqual([1]);
  const dark = await render({ owner: '' }, Object.assign(new Error('SECRET-RAW-TEXT'), { status: 501, code: 'budget_request_unavailable' }));
  await press(dark.target, '[data-argent="ask"]');
  type(dark.target, '[data-argent-ask-amount]', '5');
  type(dark.target, '[data-argent-ask-reason]', 'release week');
  await press(dark.target, '[data-argent-ask-send]');
  expect(dark.target.querySelector('[data-argent-ask-said]')?.textContent).toBe('asking for more budget is not available yet; ask the budget owner in argent');
  expect(document.body.textContent).not.toContain('SECRET-RAW-TEXT');
});

test('an ask pending on this item shows the line and no form; another item is not affected', async () => {
  const rows = [{ id: 'br_1', item_id: 'wi_1', requested_micros: 4_000_000, approved_micros: null, state: 'pending', decision_reason: '', created_at: 1, decided_at: null },
    { id: 'br_0', item_id: 'wi_1', requested_micros: 1, approved_micros: 1, state: 'approved', decision_reason: '', created_at: 0, decided_at: 1 }];
  const own = await render({ requests: rows });
  expect(own.target.querySelector('[data-argent-asked]')?.textContent).toBe('asked $4.00 more; waiting on Fixture Owner');
  expect(own.target.querySelector('[data-argent="ask"]')).toBeNull();
  const other = await render({ requests: rows, itemId: 'wi_2' });
  expect(other.target.querySelector('[data-argent="ask"]')).not.toBeNull();
  const decided = await render({ requests: [rows[1]] });
  expect(decided.target.querySelector('[data-argent="ask"]')).not.toBeNull();
});

test('after a send, a listing that decides the ask ends the waiting line and gives the ask button back', async () => {
  const listing = new SvelteMap<string, unknown>();
  const { target } = await render({ get requests() { return [...listing.values()]; } });
  await press(target, '[data-argent="ask"]');
  type(target, '[data-argent-ask-amount]', '10');
  type(target, '[data-argent-ask-reason]', 'release week');
  await press(target, '[data-argent-ask-send]');
  expect(target.querySelector('[data-argent-asked]')).not.toBeNull();
  listing.set('br_1', { id: 'br_1', item_id: 'wi_1', requested_micros: 10_000_000, approved_micros: null, state: 'denied', decision_reason: 'no', created_at: 1, decided_at: 2 });
  await settle();
  expect(target.querySelector('[data-argent-asked]')).toBeNull();
  expect(target.querySelector('[data-argent="ask"]')).not.toBeNull();
});

test('a held item over its cap starts the field at the overage and posts exactly what the field holds', async () => {
  const { target, calls } = await render({ spentMicros: 12_500_000, held: true });
  await press(target, '[data-argent="ask"]');
  expect((target.querySelector('[data-argent-ask-amount]') as HTMLInputElement).value).toBe('2.50');
  type(target, '[data-argent-ask-reason]', 'release week');
  await press(target, '[data-argent-ask-send]');
  expect(calls).toEqual([{ path: '/argent/budget/requests', body: { item_id: 'wi_1', amount_micros: 2_500_000, reason: 'release week' } }]);
});

test('an item under its cap, or not held, starts empty and sending the empty field refuses', async () => {
  for (const props of [{ spentMicros: 4_000_000, held: true }, { spentMicros: 12_500_000, held: false }]) {
    const { target, calls } = await render(props);
    await press(target, '[data-argent="ask"]');
    expect((target.querySelector('[data-argent-ask-amount]') as HTMLInputElement).value).toBe('');
    type(target, '[data-argent-ask-reason]', 'release week');
    await press(target, '[data-argent-ask-send]');
    expect(calls).toEqual([]);
    expect(target.textContent).toContain('type an amount above zero');
  }
});
