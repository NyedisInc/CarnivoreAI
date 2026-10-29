/** @vitest-environment jsdom */
import { flushSync, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, test, vi } from 'vitest';

const machines = vi.hoisted(() => ({ holder: { data: { machines: [{ is_self: true, paired: false }] } as { machines: { is_self: boolean; paired: boolean }[] } } }));
const stub = vi.hoisted(() => ({ getPackSkills: vi.fn() }));

vi.mock('../../../opscenter/api/events.svelte', () => ({ subscribe: () => () => {} }));
vi.mock('../../../opscenter/api/auth.svelte', async (importActual) => {
    const { fakeServer } = await import('../../skills-page/skills-fixtures');
    return { ...(await importActual<Record<string, unknown>>()), authFetch: fakeServer().fetcher };
});
vi.mock('../../pack-machines/pack-machines-store.svelte', async (importActual) => ({ ...(await importActual<Record<string, unknown>>()), packMachines: machines.holder }));
vi.mock('../../skills-hub/pack/pack-skills-api', async (importActual) => ({ ...(await importActual<Record<string, unknown>>()), ...stub }));

import InstalledPage from './InstalledPage.svelte';
import PackPanels from '../../pack-page/PackPanels.svelte';
import { nodeHash, parseNodeHash, nodeKey, type MenuNode } from './route';
import { skillsNode } from '../../skills-hub/tabs';
import type { MenuSources } from './model';

const SOURCES: MenuSources = {
    storeTotal: 0, storeNewest: 0, storeUpdates: 0, storeByKind: { skill: 0, theme: 0, mod: 0, plugin: 0 }, storeItems: [],
    installed: { skill: [], theme: [], mod: [], plugin: [] }, flagged: [], needs: [],
};
const t = (key: string) => key;
const PACK_OF_TWO = [{ is_self: true, paired: false }, { is_self: false, paired: true }];

let app: Record<string, unknown> | null = null;

async function settle(): Promise<void> {
    for (let i = 0; i < 8; i++) await tick();
    flushSync();
}

async function show(node: MenuNode, onNavigate = vi.fn()): Promise<HTMLElement> {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(InstalledPage, { target: host, props: { node: node as never, sources: SOURCES, t: t as never, onNavigate } });
    await settle();
    return host;
}

const tabIds = (host: HTMLElement): string[] => [...host.querySelectorAll('[role="tab"]')].map((el) => el.getAttribute('data-tab') ?? '');
const selected = (host: HTMLElement): string | null => host.querySelector('[role="tab"][aria-selected="true"]')?.getAttribute('data-tab') ?? null;

afterEach(() => {
    if (app) unmount(app);
    app = null;
    machines.holder.data = { machines: [{ is_self: true, paired: false }] };
    document.body.innerHTML = '';
});

describe('INSTALLED > skills tabs', () => {
    test('installed and stats only with one computer; installed is selected and lists skills', async () => {
        const host = await show(skillsNode());
        expect(tabIds(host)).toEqual(['installed', 'stats']);
        expect(selected(host)).toBe('installed');
        expect(host.querySelectorAll('[data-item-id]').length).toBeGreaterThan(0);
    });

    test('an address naming pack with one computer reads as installed', async () => {
        const host = await show(skillsNode('pack'));
        expect(selected(host)).toBe('installed');
    });

    test('with two computers the pack tab shows and draws the Pack skills table', async () => {
        machines.holder.data = { machines: PACK_OF_TWO };
        stub.getPackSkills.mockResolvedValue({ role: 'receiver', read_only: true, alpha: { id: 'a', label: 'nostromo' }, applied_gen: 1, rows: [] });
        const host = await show(skillsNode('pack'));
        expect(tabIds(host)).toEqual(['installed', 'stats', 'pack']);
        expect(selected(host)).toBe('pack');
        expect(host.querySelector('[data-pks-readonly]')?.textContent).toContain('nostromo');
    });

    test('a tab click reports the node; stats draws the census, not the list', async () => {
        const onNavigate = vi.fn();
        const host = await show(skillsNode(), onNavigate);
        host.querySelector<HTMLButtonElement>('[data-tab="stats"]')!.click();
        expect(onNavigate).toHaveBeenCalledWith({ scope: 'installed', page: 'kind', kind: 'skill', tab: 'stats' });
        unmount(app!);
        document.body.innerHTML = '';
        const stats = await show(skillsNode('census'));
        expect(selected(stats)).toBe('stats');
        expect(stats.querySelector('[data-item-id]')).toBeNull();
    });

    test('the tab is in the address and the menu row stays the list row; old names map', () => {
        expect(nodeHash(skillsNode('census'))).toBe('#warez/installed/skills/stats');
        expect(parseNodeHash('#warez/installed/skills/pack')).toEqual(skillsNode('pack'));
        expect(parseNodeHash('#warez/installed/skill/pack')).toEqual({ scope: 'installed', page: 'item', kind: 'skill', key: 'pack' });
        expect(nodeKey(skillsNode('census'))).toBe(nodeKey(skillsNode()));
    });
});

describe('the Pack page skills tab', () => {
    test('renders PackSkillsTab, the same table', async () => {
        stub.getPackSkills.mockResolvedValue({ role: 'receiver', read_only: true, alpha: { id: 'a', label: 'nostromo' }, applied_gen: 1, rows: [] });
        app = mount(PackPanels, { target: document.body, props: { tab: 'skills' } });
        await settle();
        expect(document.querySelector('[data-pks-readonly]')?.textContent).toContain('nostromo');
    });
});
