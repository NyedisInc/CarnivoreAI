/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('./third-party-switch', async (original) => ({
    ...(await original<typeof import('./third-party-switch')>()),
    loadThirdParty: async () => ({ enabled: true, safe_mode: { env: false, owner: false, active: false }, sandbox: { ok: true, detail: '' } }),
}));

import DeveloperZone from './DeveloperZone.svelte';
import { createSideloadStore, type SideloadApi } from './sideload-store.svelte';
import type { SideloadStatus } from './sideload-switch';

const t = (key: string): string => key;
const OFF: SideloadStatus = { enabled: false, expires_at: null, hours: 12, items: [] };
const ON: SideloadStatus = { enabled: true, expires_at: 1_900_000_000, hours: 12, items: [] };
let mounted: Record<string, unknown> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; });

async function draw(status: SideloadStatus): Promise<HTMLElement> {
    const api: SideloadApi = { load: async () => status, save: async () => status, folder: async () => ({}), git: async () => ({}), resync: async () => ({}), remove: async () => ({}) };
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(DeveloperZone, { target, props: { t, sideloads: createSideloadStore(api) } });
    for (let i = 0; i < 12; i += 1) await tick();
    flushSync();
    return target;
}

const KEY = 'plugins.developerZone.open';
const q = (root: HTMLElement, sel: string): Element | null => root.querySelector(sel);

describe('DeveloperZone, folded by default', () => {
    afterEach(() => localStorage.clear());

    test('folded shows the summary line with the red sideload text when on, and the controls stay hidden', async () => {
        const root = await draw(ON);
        expect(q(root, '.dev-zone__label')?.textContent).toBe('plugins.page.developer.label');
        expect(q(root, '[data-sideload-summary]')?.textContent).toContain('plugins.page.developer.sideload_on');
        expect(q(root, '[data-third-party-summary]')?.textContent).toBe('plugins.page.developer.third_party_on');
        expect((q(root, '[data-developer-controls]') as HTMLElement).hidden).toBe(true);
        expect(q(root, '[data-developer-manage]')?.getAttribute('aria-expanded')).toBe('false');
        expect(q(root, '[data-sideload-strip]')).toBeNull();
    });

    test('sideload off shows no red text', async () => {
        const root = await draw(OFF);
        expect(q(root, '[data-sideload-summary]')).toBeNull();
        expect(q(root, '[data-third-party-summary]')).not.toBeNull();
    });

    test('manage unfolds every control, flips aria-expanded, remembers the choice, and a sound sandbox says nothing', async () => {
        const root = await draw(ON);
        (q(root, '[data-developer-manage]') as HTMLElement).click();
        flushSync();
        expect(q(root, '[data-developer-manage]')?.getAttribute('aria-expanded')).toBe('true');
        expect((q(root, '[data-developer-controls]') as HTMLElement).hidden).toBe(false);
        for (const sel of ['[data-third-party-toggle]', '[data-sideload-toggle]', '[data-facet="sideload-duration"]', '[data-sideload-count]', '[data-sideload-open="folder"]', '[data-sideload-open="git"]']) {
            expect(q(root, sel), sel).not.toBeNull();
        }
        expect(q(root, '[data-third-party-sandbox]')).toBeNull();
        expect(localStorage.getItem(KEY)).toBe('1');
        (q(root, '[data-developer-manage]') as HTMLElement).click();
        flushSync();
        expect(q(root, '[data-developer-manage]')?.getAttribute('aria-expanded')).toBe('false');
    });

    test('a saved open fold starts unfolded', async () => {
        localStorage.setItem(KEY, '1');
        const root = await draw(OFF);
        expect((q(root, '[data-developer-controls]') as HTMLElement).hidden).toBe(false);
    });
});
