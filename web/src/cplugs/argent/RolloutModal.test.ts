/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import RolloutModal from './RolloutModal.svelte';
import TetheredRow from './TetheredRow.svelte';
import { canRestartNow, showsProgress, sortedCounts, type RolloutPreview } from './rollout-model';
import { setLocale, t } from '../../lib/i18n/index.svelte';

setLocale('en');

const PREVIEW: RolloutPreview = {
    enabled: true, direction: 'on', total: 7, tethered: 2, pending: 1, will_restart: 3, adopted: 1, subagents: 2, background: 1,
    excluded: { 'settings override': 1, 'codex headers unsupported': 2 }, reasons: { 'settings override': 1, 'codex headers unsupported': 2, busy: 1 },
};
const NONE = { enabled: true, state: 'none', direction: '', epoch: 0, reason: '', counts: {}, reasons: {}, rows: [] };
const RUNNING = { ...NONE, state: 'running', direction: 'on', epoch: 1, counts: { pending: 1, restarted: 1 }, rows: [
    { tmux_name: 'carnivore_a', state: 'restarted', reason: 'pending first traffic' }, { tmux_name: 'carnivore_b', state: 'pending', reason: 'busy' }] };

interface Call { path: string; method: string; body: unknown }

function harness(view: unknown = NONE, preview: unknown = PREVIEW) {
    const calls: Call[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        calls.push({ path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null });
        if (path === '/argent/rollout/preview') return preview;
        if (init?.method === 'POST') return RUNNING;
        return view;
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
async function open(h: ReturnType<typeof harness>): Promise<{ closed: unknown[] }> {
    const closed: unknown[] = [];
    mounted.push(mount(RolloutModal, { target: document.body, props: { fetcher: h.fetcher, pollMs: 0, close: (v: unknown) => closed.push(v) } }));
    await settle();
    return { closed };
}
const q = (key: string) => document.querySelector<HTMLElement>(`[data-argent="${key}"]`);
const start = () => document.querySelector<HTMLButtonElement>('[data-argent="start"]')!;

describe('RolloutModal confirm view', () => {
    test('lists the count, the adopted rows, what dies and every excluded class, and never says all sessions', async () => {
        await open(harness());
        expect(q('summary')!.textContent).toContain('3 running sessions');
        expect(q('adopted')!.textContent).toContain('1 of them');
        expect(q('dies')!.textContent).toContain('2 sub-agents and 1 background jobs');
        expect(document.querySelector('[data-argent-excluded="settings override"]')!.textContent).toContain('1');
        expect(document.querySelector('[data-argent-excluded="codex headers unsupported"]')!.textContent).toContain('2');
        expect(document.body.textContent!.toLowerCase()).not.toMatch(/all (running )?sessions|plugin/);
    });

    test('start stays disabled until the arm box is ticked and sends nothing before then; ticking arms it and start posts the action', async () => {
        const h = harness();
        const { closed } = await open(h);
        expect(start().disabled).toBe(true);
        start().click();
        await settle();
        expect(h.calls.some((c) => c.method === 'POST')).toBe(false);
        document.querySelector<HTMLInputElement>('[data-argent="arm"] input, input[data-argent="arm"]')!.click();
        await settle();
        expect(start().disabled).toBe(false);
        start().click();
        await settle();
        expect(h.calls.find((c) => c.method === 'POST')).toEqual({ path: '/argent/rollout', method: 'POST', body: { action: 'start' } });
        expect(q('run')!.textContent).toContain('restarting sessions as they go idle');
        expect(closed).toEqual([]);
    });

    test('with nothing to restart there is no arm box and start stays off', async () => {
        await open(harness(NONE, { ...PREVIEW, will_restart: 0, excluded: {} }));
        expect(q('summary')!.textContent).toContain('needs a restart');
        expect(q('arm')).toBeNull();
        expect(start().disabled).toBe(true);
    });
});

describe('RolloutModal progress view', () => {
    test('restart now is only on a waiting row and only enabled once the box is ticked', async () => {
        const h = harness(RUNNING);
        await open(h);
        const buttons = document.querySelectorAll<HTMLButtonElement>('[data-argent="restart-now"]');
        expect(buttons).toHaveLength(1);
        expect(buttons[0]!.closest('[data-argent-row]')!.getAttribute('data-argent-row')).toBe('carnivore_b');
        expect(buttons[0]!.disabled).toBe(true);
        document.querySelector<HTMLInputElement>('[data-argent="arm"] input, input[data-argent="arm"]')!.click();
        await settle();
        expect(buttons[0]!.disabled).toBe(false);
        buttons[0]!.click();
        await settle();
        expect(h.calls.find((c) => c.path === '/argent/rollout/restart-now')!.body).toEqual({ tmux_name: 'carnivore_b' });
    });
});

describe('TetheredRow and the model', () => {
    function row(preview: RolloutPreview | null, onreview = () => {}): HTMLElement {
        const target = document.createElement('div');
        document.body.append(target);
        mounted.push(mount(TetheredRow, { target, props: { preview, onreview } }));
        flushSync();
        return target;
    }

    test('says n of m with a count per reason and a review button only while sessions wait', () => {
        const root = row(PREVIEW);
        expect(root.querySelector('[data-argent="tethered"]')!.textContent).toBe('2 of 7 sessions tethered');
        expect(root.querySelector('[data-argent="tethered-pending"]')!.textContent).toContain('1 waiting');
        expect(root.querySelector('[data-argent-reason="codex headers unsupported"]')!.textContent).toContain('2');
        expect(root.querySelector('[data-argent="review"]')).not.toBeNull();
        expect(row({ ...PREVIEW, will_restart: 0 }).querySelector('[data-argent="review"]')).toBeNull();
        expect(row(null).children).toHaveLength(0);
    });

    test('the model sorts counts, spots progress and waiting rows', () => {
        expect(sortedCounts({ a: 1, b: 3, c: 0 })).toEqual([['b', 3], ['a', 1]]);
        expect(showsProgress({ state: 'paused' })).toBe(true);
        expect(showsProgress({ state: 'done' })).toBe(false);
        expect(canRestartNow({ tmux_name: 'x', state: 'failed', reason: '' })).toBe(false);
        expect(t('argent.rollout.hold')).toContain('gateway rollout');
    });
});
