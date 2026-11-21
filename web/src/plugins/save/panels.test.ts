/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount } from 'svelte';

import StoragePanel from './StoragePanel.svelte';
import ScopePanel from './ScopePanel.svelte';
import { setLocale } from '../../lib/i18n/index.svelte';
import { dropsPoints, gbText, sliderMax, sliderValue, type Fetcher, type SaveSettings, type Usage } from './settings-api';

setLocale('en');

const GB = 1024 ** 3;
const USAGE: Usage = {
    used_bytes: 1.8 * GB,
    history_bytes: 1.8 * GB,
    cap_bytes: 4 * GB,
    conversations: 600,
    points: 904,
    current_backups: 2,
    pinned: 3,
    pinned_bytes: 0,
};
const SETTINGS: SaveSettings = {
    cap_gb: 4,
    cap_env_locked: false,
    cap_env_var: 'CLOUDE_TIME_MACHINE_CAP_GB',
};

interface Call {
    path: string;
    method: string;
    body: Record<string, unknown> | null;
}

function harness(over: { settings?: Partial<SaveSettings>; usage?: Partial<Usage>; failPut?: string } = {}) {
    const state = { settings: { ...SETTINGS, ...over.settings }, usage: { ...USAGE, ...over.usage } };
    const calls: Call[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        const call = { path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null };
        calls.push(call);
        if (call.method === 'PUT') {
            if (over.failPut) throw new Error(over.failPut);
            const body = call.body as Record<string, unknown>;
            if (typeof body.cap_gb === 'number') {
                state.settings.cap_gb = body.cap_gb;
                state.usage.cap_bytes = body.cap_gb * GB;
            }
            return state.usage;
        }
        return path.endsWith('/settings') ? state.settings : state.usage;
    }) as unknown as Fetcher;
    return { fetcher, calls, state };
}

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) {
        await Promise.resolve();
        flushSync();
    }
}

async function open(component: typeof StoragePanel | typeof ScopePanel, fetcher: Fetcher) {
    const target = document.createElement('div');
    document.body.append(target);
    mount(component, { target, props: { fetcher } });
    await settle();
    return target;
}

async function drag(target: HTMLElement, to: number): Promise<void> {
    const range = target.querySelector<HTMLInputElement>('[data-tm="cap"]')!;
    range.value = String(to);
    range.dispatchEvent(new Event('input', { bubbles: true }));
    range.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
}

const click = async (target: HTMLElement, selector: string): Promise<void> => {
    target.querySelector<HTMLElement>(selector)!.click();
    await settle();
};

afterEach(() => {
    document.body.innerHTML = '';
});

describe('storage panel', () => {
    test('shows live usage against the cap and the counts', async () => {
        const { fetcher } = harness();
        const target = await open(StoragePanel, fetcher);
        expect(target.querySelector('[data-tm="figures"]')!.textContent).toContain('1.8 gb of 4.0 gb used');
        expect(target.querySelector('[data-tm="counts"]')!.textContent).toContain('904 conversation backups, 600 conversations, 3 pinned');
        expect(target.querySelector('.oc-gauge')!.getAttribute('data-scale')).toBe('2');
        expect(target.querySelector<HTMLInputElement>('[data-tm="cap"]')!.value).toBe('4');
    });

    test('raising the cap writes it on release', async () => {
        const { fetcher, calls } = harness();
        const target = await open(StoragePanel, fetcher);
        await drag(target, 8);
        const puts = calls.filter((c) => c.method === 'PUT');
        expect(puts).toEqual([{ path: '/cplugs/save/settings', method: 'PUT', body: { cap_gb: 8 } }]);
        expect(target.querySelector('[data-tm="note"]')!.textContent).toContain('8 gb');
        expect(target.querySelector('[data-tm="warn"]')).toBeNull();
    });

    test('lowering below what is stored asks first and writes nothing until confirm', async () => {
        const { fetcher, calls } = harness();
        const target = await open(StoragePanel, fetcher);
        await drag(target, 1);
        expect(calls.some((c) => c.method === 'PUT')).toBe(false);
        expect(target.querySelector('[data-tm="warn"]')!.textContent).toContain('oldest unpinned conversation backups will be dropped');
        await click(target, '[data-tm="confirm"]');
        expect(calls.filter((c) => c.method === 'PUT').map((c) => c.body)).toEqual([{ cap_gb: 1 }]);
        expect(target.querySelector('[data-tm="warn"]')).toBeNull();
    });

    test('the meter and the lowering warning count history, which is what the cap limits (u127-02)', async () => {
        const { fetcher, calls, state } = harness();
        state.usage = { ...USAGE, used_bytes: 3 * GB, history_bytes: 0.5 * GB };
        const target = await open(StoragePanel, fetcher);
        expect(target.querySelector('[data-tm="figures"]')!.textContent).toContain('0.5 gb of 4.0 gb used');
        await drag(target, 1);
        expect(target.querySelector('[data-tm="warn"]')).toBeNull();
        expect(calls.filter((c) => c.method === 'PUT').map((c) => c.body)).toEqual([{ cap_gb: 1 }]);
    });

    test('cancel puts the slider back and writes nothing', async () => {
        const { fetcher, calls } = harness();
        const target = await open(StoragePanel, fetcher);
        await drag(target, 1);
        await click(target, '[data-tm="cancel"]');
        expect(calls.some((c) => c.method === 'PUT')).toBe(false);
        expect(target.querySelector<HTMLInputElement>('[data-tm="cap"]')!.value).toBe('4');
        expect(target.querySelector('[data-tm="warn"]')).toBeNull();
    });

    test('a cap the environment decides is shown and cannot be moved', async () => {
        const { fetcher } = harness({ settings: { cap_gb: 9, cap_env_locked: true } });
        const target = await open(StoragePanel, fetcher);
        expect(target.querySelector<HTMLInputElement>('[data-tm="cap"]')!.disabled).toBe(true);
        expect(target.querySelector('[data-tm="locked"]')!.textContent).toContain('CLOUDE_TIME_MACHINE_CAP_GB');
    });

    test('a refused save shows the reason and restores the slider', async () => {
        const { fetcher } = harness({ failPut: 'disk full' });
        const target = await open(StoragePanel, fetcher);
        await drag(target, 8);
        expect(target.querySelector('[data-tm="problem"]')!.textContent).toContain('disk full');
        expect(target.querySelector<HTMLInputElement>('[data-tm="cap"]')!.value).toBe('4');
    });

    test('a reply that is not usage shows a problem, never NaN', async () => {
        const target = await open(StoragePanel, (async () => ({})) as unknown as Fetcher);
        expect(target.querySelector('[data-tm="problem"]')!.textContent).toContain('did not answer');
        expect(target.querySelector('[data-tm="cap"]')).toBeNull();
    });

    test('the helpers', () => {
        expect(gbText(1.8 * GB)).toBe('1.8 gb');
        expect(dropsPoints(1, 1.8 * GB)).toBe(true);
        expect(dropsPoints(2, 1.8 * GB)).toBe(false);
        expect(sliderValue(0.4)).toBe(1);
        expect(sliderMax(4)).toBe(32);
        expect(sliderMax(40.2)).toBe(41);
    });
});

describe('capture scope panel', () => {
    const scopeFetcher = (calls: Call[]): Fetcher =>
        (async (path: string, init?: RequestInit) => {
            const call = { path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null };
            calls.push(call);
            const scope = call.method === 'PUT' ? (call.body as { capture_scope: string }).capture_scope : 'human';
            return { capture_scope: scope, default: 'human', choices: ['human', 'human+subsessions', 'all'] };
        }) as unknown as Fetcher;

    test('reads the scope in force and saves a choice at once, to the plugin route', async () => {
        const calls: Call[] = [];
        const target = await open(ScopePanel, scopeFetcher(calls));
        expect(target.querySelector('[data-tm-scope="human"]')!.getAttribute('aria-checked')).toBe('true');
        await click(target, '[data-tm-scope="all"]');
        expect(calls.filter((c) => c.method === 'PUT')).toEqual([{ path: '/cplugs/save/capture-scope', method: 'PUT', body: { capture_scope: 'all' } }]);
        expect(target.querySelector('[data-tm-scope="all"]')!.getAttribute('aria-checked')).toBe('true');
    });
});
