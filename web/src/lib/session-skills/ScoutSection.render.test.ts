/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const calls: Array<{ method: string; path: string }> = [];
let getReply: unknown;
let postError: unknown = null;
let quickOutcome: unknown;
const quickCalls: unknown[][] = [];
const modalCalls: unknown[] = [];

vi.mock('../../opscenter/api/auth.svelte', async (orig) => {
    const real = (await orig()) as Record<string, unknown>;
    return {
        ...real,
        authFetch: async (path: string, init: RequestInit = {}) => {
            calls.push({ method: init.method ?? 'GET', path });
            if (init.method === 'POST') {
                if (postError) throw postError;
                return { pasted_bytes: 10, items_listed: 3 };
            }
            return getReply;
        },
    };
});
vi.mock('../catalog/catalog', () => ({
    browserCatalogHost: () => ({ item: async () => ({ id: 'pub/a', kind: 'skill', name: 'a', publisher: 'pub', latest: '1', card: { title: 'a', brief: 'b' }, fm: { description: 'd' }, versions: [{ v: '1' }] }) }),
}));
vi.mock('../catalog/quick-add', () => ({
    quickAdd: async (...args: unknown[]) => {
        quickCalls.push(args);
        return quickOutcome;
    },
}));
vi.mock('../modal', () => ({
    openModal: async (...args: unknown[]) => {
        modalCalls.push(args);
        return { outcome: 'installed', row: {} };
    },
    openModalCount: () => 0,
}));

import ScoutSection from './ScoutSection.svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');
let mounted: Record<string, unknown> | null = null;

async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

async function section(): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(ScoutSection, { target, props: { sessionId: 'ses_1', workingDir: '/work/lab' } });
    await settle();
    return target;
}

beforeEach(() => {
    calls.length = 0;
    quickCalls.length = 0;
    modalCalls.length = 0;
    postError = null;
    quickOutcome = { outcome: 'installed', row: {} };
    getReply = { state: 'ready', suggestions: [{ item_id: 'pub/a', name: 'a', reason: 'fits <b>bold</b>' }] };
});
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

test('suggestions render as chips and the reason stays text', async () => {
    const root = await section();
    const chip = root.querySelector('[data-scout-chip="pub/a"]')!;
    expect(chip.textContent).toContain('add a');
    expect(chip.textContent).toContain('fits <b>bold</b>');
    expect(chip.querySelector('b')).toBeNull();
});

test('the button posts the scout request; a refusal shows the server sentence', async () => {
    getReply = { state: 'none', suggestions: [] };
    postError = new ApiError('x', 409, null, { detail: { code: 'pane_dialog_open', message: 'the agent is waiting on a question' } });
    const root = await section();
    (root.querySelector('[data-scout-button]') as HTMLElement).click();
    await settle();
    expect(calls.some((c) => c.method === 'POST' && c.path === '/sessions/ses_1/skills/scout')).toBe(true);
    expect(root.querySelector('[data-scout-error]')?.textContent).toContain('the agent is waiting on a question');
});

test('a chip installs one-click into the project; a sheet answer opens the consent sheet', async () => {
    const root = await section();
    (root.querySelector('[data-scout-chip="pub/a"] button') as HTMLElement).click();
    await settle();
    expect(quickCalls[0]!.slice(1)).toEqual(['pub/a', 'project', '/work/lab']);
    expect(modalCalls.length).toBe(0);
    expect(root.querySelector('[data-scout-chip="pub/a"]')?.textContent).toContain('a added');

    unmount(mounted!);
    document.body.innerHTML = '';
    quickOutcome = { outcome: 'sheet', prefill: { scope: 'project', projectPath: '/work/lab' } };
    const again = await section();
    (again.querySelector('[data-scout-chip="pub/a"] button') as HTMLElement).click();
    await settle();
    expect(modalCalls.length).toBe(1);
});

test('a scout already waiting on mount keeps polling and shows the answer when it lands (u147-01)', async () => {
    vi.useFakeTimers();
    try {
        getReply = { state: 'waiting', suggestions: [] };
        const root = await section();
        expect((root.querySelector('[data-scout-button]') as HTMLButtonElement).disabled).toBe(true);
        getReply = { state: 'ready', suggestions: [{ item_id: 'pub/a', name: 'a', reason: 'r' }] };
        await vi.advanceTimersByTimeAsync(4100);
        await settle();
        expect(root.querySelector('[data-scout-chip="pub/a"]')).not.toBeNull();
    } finally {
        vi.useRealTimers();
    }
});

test('when polling gives up the button comes back, so an ignored scout cannot lock the feature (u147-01)', async () => {
    vi.useFakeTimers();
    try {
        getReply = { state: 'waiting', suggestions: [] };
        const root = await section();
        for (let i = 0; i < 32; i += 1) {
            await vi.advanceTimersByTimeAsync(4100);
            await settle();
        }
        expect((root.querySelector('[data-scout-button]') as HTMLButtonElement).disabled).toBe(false);
    } finally {
        vi.useRealTimers();
    }
});
