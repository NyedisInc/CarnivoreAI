/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, tick, unmount } from 'svelte';
import type { CplugRow } from '../../lib/plugins-page/cplugs-adapter';

vi.mock('../../lib/cplug-ui/api', () => ({
    fetchViewTicket: vi.fn(async () => ({ path: '/cplugs/bubblepop/view/game/t/index.html' })),
    callViewRoute: vi.fn(),
}));

const SLOT = 'bubblepop.game:panel-abcd1234';
let mounted: ReturnType<typeof mount> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; localStorage.clear(); });

test('metaFor answers a placeholder for an unregistered plugin slot and still throws for an unknown singleton', async () => {
    const { metaFor, META } = await import('./meta');
    expect(metaFor(SLOT as never, META).titleKey).toBe('opscenter.cell.plugin_pending.title');
    expect(() => metaFor('nosuchcell' as never, META)).toThrow(/no meta for cell/);
});

test('the grid mounted from a stored layout with an unregistered panel slot draws it, then the cell swaps to the panel when the kind registers', async () => {
    (globalThis as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
    const { setPanels } = await import('../../lib/cplug-ui/panel-views.svelte');
    const { resetLayout } = await import('./model');
    const { META } = await import('./meta');
    const { STORAGE_KEYS, SCHEMA_VERSION } = await import('./persist');
    const base = resetLayout(META, 'home') as any;
    base.rows[0].slots.push({ id: SLOT, fr: 1 });
    localStorage.setItem(STORAGE_KEYS.home, JSON.stringify({ ...base, v: SCHEMA_VERSION }));
    const { createLayoutStore } = await import('./layout.svelte');
    const store = createLayoutStore('home');
    const { default: GridSurface } = await import('./GridSurface.svelte');
    const { default: CellHost } = await import('../CellHost.svelte');
    const target = document.createElement('div');
    document.body.appendChild(target);
    const renderCell = createRawSnippet((id: () => string) => ({ render: () => `<div data-slot="${id()}"></div>` })) as any;
    mounted = mount(GridSurface, { target, props: { store, renderCell } });
    flushSync();
    expect(target.querySelectorAll('.oc-cellslot').length).toBeGreaterThan(1);

    const host = document.createElement('div');
    document.body.appendChild(host);
    const cell = mount(CellHost, { target: host, props: { id: SLOT, store } });
    await tick();
    expect(host.textContent).toContain('remove this cell');
    setPanels([{ id: 'bubblepop', runtime: 'sidecar', enabled: true, state: 'active', name: 'Bubble Pop', install_key: 'abcd1234xx',
        views: [{ name: 'game', surfaces: ['panel'] }] } as unknown as CplugRow]);
    flushSync(); await tick(); await tick();
    expect(host.textContent).not.toContain('remove this cell');
    expect(host.querySelector('[data-panel-cell]')).not.toBeNull();
    unmount(cell);
    setPanels([]);
});
