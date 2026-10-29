/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import SideloadSwitch from './SideloadSwitch.svelte';
import type { SideloadStatus } from './sideload-switch';

const t = (key: string, params?: Record<string, unknown> | null): string => (params && 'count' in params ? `${key}|${params.count}` : key);
const OFF: SideloadStatus = { enabled: false, expires_at: null, items: [] };
let mounted: Record<string, unknown> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; });

async function draw(props: Record<string, unknown>) {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(SideloadSwitch, { target, props: { t, ...props } });
    await tick(); await tick();
    flushSync();
    return target;
}

describe('SideloadSwitch', () => {
    test('off draws no count; turning it on writes true once and shows the count the server answered', async () => {
        const save = vi.fn(async () => ({ enabled: true, expires_at: 99, items: [{ id: 'a', item_id: 'local/a', source: '/x', synced_at: 1, changed: [] }] }));
        const root = await draw({ load: async () => OFF, save });
        expect(root.querySelector('[data-sideload-count]')).toBeNull();
        root.querySelector<HTMLElement>('[data-sideload-toggle]')!.click();
        await tick(); await tick();
        flushSync();
        expect(save).toHaveBeenCalledExactlyOnceWith(true);
        expect(root.querySelector('[data-sideload-count]')?.textContent).toBe('plugins.page.sideload.count|1');
    });

    test('a refused write says so and the switch stays off', async () => {
        const root = await draw({ load: async () => OFF, save: vi.fn(async () => { throw new Error('403'); }) });
        root.querySelector<HTMLElement>('[data-sideload-toggle]')!.click();
        await tick(); await tick();
        flushSync();
        expect(root.querySelector('[data-sideload-failed]')).not.toBeNull();
        expect(root.querySelector('[data-sideload-toggle]')?.getAttribute('aria-checked')).toBe('false');
    });
});
