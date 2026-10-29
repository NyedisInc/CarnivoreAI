/** @vitest-environment jsdom */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { entryNodes } from '../item-menu/entries';

const calls: string[] = [];
let failWith: Error | null = null;
let menuOpenAtWrite: boolean | null = null;

vi.mock('../add-to-menu/host', () => ({ addToMenuBridge: { openForProject: () => {}, close: () => {} }, addToNodes: { forProject: () => [], forGroup: () => [] }, ADD_TO_CASCADE_CONTAINER_ID: 'x' }));
vi.mock('./company-source.svelte', () => ({ companySource: () => ({ companies: [], companyOf: () => null }) }));
vi.mock('../project-colors/store.svelte', () => ({ projectColorOf: (id: number | null) => (id === 5 ? '#4e69ba' : null) }));
vi.mock('./interaction-globals', () => ({
    announce: () => {},
    announceFailure: (text: string) => { calls.push(`fail ${text}`); },
    hg: () => ({
        SessionSidebar: { _rows: [{ name: 'a', kind: 'agent', project_id: 5, project_name: 'proj' }] },
        API: { updateProject: vi.fn(async (name: string, body: { color?: string }) => {
            menuOpenAtWrite = (await import('../item-menu/open.svelte')).itemMenuState.open !== null;
            if (failWith) throw failWith;
            calls.push(`patch ${name} ${body.color}`);
        }) },
    }),
    reasonOf: (e: unknown) => String((e as Error).message),
    refetchDrawer: async () => {},
    usableGroups: () => null,
    repaintDrawerRows: () => {},
}));

async function projectNodes(key: string): Promise<MenuNode[]> {
    await import('../item-menu/menus/all');
    const { itemMenu } = await import('../item-menu/registry');
    return itemMenu('project', { key, anchor: document.body }, { close: () => {}, glyph: () => '' })!.nodes;
}

beforeAll(async () => {
    await import('../item-menu/menus/all');
    await import('../item-menu/registry');
}, 60_000);

beforeEach(() => {
    calls.length = 0;
    failWith = null;
    menuOpenAtWrite = null;
});

describe('the project kebab color row', () => {
    it('offers one colors entry with the current key, after rename', async () => {
        const nodes = await projectNodes('p:5');
        const at = nodes.findIndex((e) => e.swatches);
        expect(at).toBeGreaterThan(nodes.findIndex((e) => e.id === 'rename-project'));
        expect(nodes[at]!.swatches!.value).toBe('#4e69ba');
    });

    it('carries no crosstalk and no schedule this entry', async () => {
        const ids = (await projectNodes('p:5')).map((e) => e.id);
        expect(ids).toContain('show-path');
        expect(ids).not.toContain('crosstalk');
        expect(ids).not.toContain('schedule');
    });

    it('a swatch writes the color through updateProject and closes the menu', async () => {
        const { itemMenuState } = await import('../item-menu/open.svelte');
        itemMenuState.open = { type: 'project', nodes: [], ariaLabel: 'menu', at: null, anchor: document.body, nestedIn: null, seq: 0 };
        (await projectNodes('p:5')).find((e) => e.swatches)!.swatches!.onPick('#966356');
        await vi.waitFor(() => expect(calls).toContain('patch proj #966356'));
        expect(menuOpenAtWrite, 'the menu was closed before the write').toBe(false);
        expect(itemMenuState.open).toBeNull();
    });

    it('a failed write is announced', async () => {
        failWith = new Error('422');
        (await projectNodes('p:5')).find((e) => e.swatches)!.swatches!.onPick('nope');
        await vi.waitFor(() => expect(calls.some((c) => c.startsWith('fail') && c.includes('422'))).toBe(true));
    });
});

const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto.showPopover ??= function () {};
proto.hidePopover ??= function () {};

describe('the item menu draws the colors entry as the swatch row', () => {
    it('renders the palette, marks the current key and reports a press', async () => {
        const real = await import('../item-menu/open.svelte');
        const picks: string[] = [];
        real.itemMenuState.open = {
            type: 'project',
            nodes: entryNodes([{ label: '', id: 'project-color', onPick: () => undefined, colors: { value: '#4e69ba', onPick: (k) => picks.push(k) } }], () => '', () => {}),
            ariaLabel: 'menu', at: null, anchor: document.body, nestedIn: null, seq: 0,
        };
        const { default: ItemMenuHost } = await import('../item-menu/ItemMenuHost.svelte');
        const host = document.createElement('div');
        document.body.appendChild(host);
        const app = mount(ItemMenuHost, { target: host });
        flushSync();
        const row = host.querySelector('[data-heading-menu-colors] [data-project-color-picker]');
        expect(row).not.toBeNull();
        expect(host.querySelector('[data-project-color="#4e69ba"]')!.getAttribute('aria-checked')).toBe('true');
        host.querySelector<HTMLElement>('[data-project-color="#966356"]')!.click();
        expect(picks).toEqual(['#966356']);
        unmount(app);
        real.itemMenuState.open = null;
        host.remove();
    });

    it('a project\'s entry (allowNone) draws the no color swatch and a press reports an empty pick; other entries do not', async () => {
        const real = await import('../item-menu/open.svelte');
        const { default: ItemMenuHost } = await import('../item-menu/ItemMenuHost.svelte');
        const picks: string[] = [];
        const draw = (allowNone: boolean) => {
            real.itemMenuState.open = {
                type: 'project',
                nodes: entryNodes([{ label: '', id: 'project-color', onPick: () => undefined, colors: { value: '', allowNone, onPick: (k) => picks.push(k) } }], () => '', () => {}),
                ariaLabel: 'menu', at: null, anchor: document.body, nestedIn: null, seq: 0,
            };
            const host = document.createElement('div');
            document.body.appendChild(host);
            const app = mount(ItemMenuHost, { target: host });
            flushSync();
            return { host, app };
        };
        const without = draw(false);
        expect(without.host.querySelector('[data-project-color-none]')).toBeNull();
        unmount(without.app);
        without.host.remove();
        const withNone = draw(true);
        const none = withNone.host.querySelector<HTMLElement>('[data-project-color-none]');
        expect(none).not.toBeNull();
        none!.click();
        expect(picks).toEqual(['']);
        unmount(withNone.app);
        real.itemMenuState.open = null;
        withNone.host.remove();
    });
});
