/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import SideloadSwitch from './SideloadSwitch.svelte';
import { createSideloadStore, type SideloadApi } from './sideload-store.svelte';
import { durationValue, hoursOf, sourceLine, type SideloadStatus } from './sideload-switch';

const t = (key: string, params?: Record<string, unknown> | null): string => (params && 'count' in params ? `${key}|${params.count}` : key);
const OFF: SideloadStatus = { enabled: false, expires_at: null, hours: 12, items: [] };
const ITEM = { id: 'a', item_id: 'local/a', source: '/x', synced_at: 1, changed: [] };
let mounted: Record<string, unknown> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; });

function api(overrides: Partial<SideloadApi> = {}): SideloadApi {
    return {
        load: async () => OFF,
        save: vi.fn(async () => OFF),
        folder: vi.fn(async () => ({})),
        git: vi.fn(async () => ({})),
        resync: vi.fn(async () => ({})),
        remove: vi.fn(async () => ({})),
        ...overrides,
    };
}

async function settle(): Promise<void> {
    for (let i = 0; i < 12; i += 1) await tick();
    flushSync();
}

async function draw(calls: SideloadApi) {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(SideloadSwitch, { target, props: { t, store: createSideloadStore(calls) } });
    await settle();
    return target;
}

async function turnOn(root: HTMLElement): Promise<void> {
    root.querySelector<HTMLElement>('[data-sideload-toggle]')!.click();
    await settle();
    document.querySelector<HTMLButtonElement>('[data-sideload-confirm-go]')!.click();
    await settle();
}

function select(root: HTMLElement): HTMLSelectElement {
    return root.querySelector<HTMLSelectElement>('select[data-facet="sideload-duration"]')!;
}

describe('SideloadSwitch', () => {
    test('off draws no count and disabled loaders; turning it on sends the shown duration and shows the count', async () => {
        const save = vi.fn(async () => ({ enabled: true, expires_at: 99, hours: 12, items: [ITEM] }));
        const root = await draw(api({ save }));
        expect(root.querySelector('[data-sideload-count]')).toBeNull();
        expect(root.querySelector<HTMLButtonElement>('[data-sideload-open="folder"]')!.disabled).toBe(true);
        expect(root.querySelector<HTMLButtonElement>('[data-sideload-open="git"]')!.disabled).toBe(true);
        await turnOn(root);
        expect(save).toHaveBeenCalledExactlyOnceWith(true, 12);
        expect(root.querySelector('[data-sideload-count]')?.textContent).toBe('plugins.page.sideload.count|1');
        expect(root.querySelector<HTMLButtonElement>('[data-sideload-open="folder"]')!.disabled).toBe(false);
    });

    test('the select offers the five durations; picked while off it is sent at turn-on, until turned off is null', async () => {
        const save = vi.fn(async () => ({ enabled: true, expires_at: null, hours: null, items: [] }));
        const root = await draw(api({ save }));
        expect([...select(root).options].map((o) => o.value)).toEqual(['1', '12', '24', '168', 'off']);
        expect(select(root).value).toBe('12');
        select(root).value = 'off';
        select(root).dispatchEvent(new Event('change', { bubbles: true }));
        await settle();
        expect(save).not.toHaveBeenCalled();
        await turnOn(root);
        expect(save).toHaveBeenCalledExactlyOnceWith(true, null);
        expect(root.querySelector('[data-sideload-until]')?.textContent).toBe('plugins.page.sideload.until_off');
    });

    test('picking a duration while on re-arms the switch at once', async () => {
        const save = vi.fn(async () => ({ enabled: true, expires_at: 5000, hours: 24, items: [] }));
        const root = await draw(api({ load: async () => ({ enabled: true, expires_at: 100, hours: 12, items: [] }), save }));
        expect(root.querySelector('[data-sideload-until]')?.textContent).toBe('plugins.page.sideload.until');
        select(root).value = '24';
        select(root).dispatchEvent(new Event('change', { bubbles: true }));
        await settle();
        expect(save).toHaveBeenCalledExactlyOnceWith(true, 24);
    });

    test('a refused write says so and the switch stays off', async () => {
        const root = await draw(api({ save: vi.fn(async () => { throw new Error('403'); }) }));
        await turnOn(root);
        expect(root.querySelector('[data-sideload-failed]')).not.toBeNull();
        expect(root.querySelector('[data-sideload-toggle]')?.getAttribute('aria-checked')).toBe('false');
    });
});

describe('sideload helpers', () => {
    test('duration values round trip, an older server without hours reads as twelve', () => {
        expect(durationValue(null)).toBe('off');
        expect(durationValue(undefined)).toBe('12');
        expect(hoursOf('off')).toBeNull();
        expect(hoursOf('168')).toBe(168);
    });

    test('the source line is the folder, or repo @ ref (short sha) for git', () => {
        expect(sourceLine(ITEM, t)).toBe('/x');
        const git = { url: 'git@github.com:me/clock.git', ref: 'main', subdir: 'plugin', commit: '1a2b3c4d5e6f', synced_at: 1 };
        expect(sourceLine({ ...ITEM, git }, t)).toBe('github.com:me/clock/plugin @ main (1a2b3c4)');
        expect(sourceLine({ ...ITEM, git: { ...git, url: 'https://github.com/me/clock', ref: null, subdir: '' } }, t))
            .toBe('github.com/me/clock @ plugins.page.sideload.default_branch (1a2b3c4)');
    });
});
