/** @vitest-environment jsdom */
import { describe, expect, it, vi } from 'vitest';

const uninstall = vi.hoisted(() => ({ uninstallPlugin: vi.fn(), uninstallableRow: vi.fn() }));
vi.mock('./plugin-uninstall', () => uninstall);
import { createPluginsPageController } from './plugins-page-controller.svelte';
import type { CplugItem, CplugSheet } from './cplugs-adapter';

function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void; reject: (e: unknown) => void } {
    let resolve!: (v: T) => void;
    let reject!: (e: unknown) => void;
    const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
    return { promise, resolve, reject };
}

const fakeCatalog = (over: Record<string, unknown> = {}) => ({
    setEnabled: vi.fn(async () => {}), items: () => [{ id: 'catalog:x' }], ledger: () => [], load: vi.fn(async () => {}), ...over,
}) as never;

const sheet = (stamp: string): CplugSheet => ({ stamp }) as unknown as CplugSheet;

function make(over: { catalog?: never | null; loadSheet?: (id: string) => Promise<CplugSheet> } = {}) {
    const reloadBuiltins = vi.fn(async () => {});
    const page = createPluginsPageController({
        catalog: over.catalog === undefined ? fakeCatalog() : over.catalog,
        catalogItems: () => [{ id: 'catalog:x', itemId: 'x' }] as never,
        reloadBuiltins,
        loadSheet: over.loadSheet ?? (async () => sheet('s')),
        t: (key: string) => key,
    });
    return { page, reloadBuiltins };
}

describe('card actions', () => {
    it('a second press while one is in flight is ignored, and a refusal lands on the card as the error message', async () => {
        const gate = deferred<void>();
        const { page } = make({ catalog: fakeCatalog({ setEnabled: vi.fn(() => gate.promise) }) });
        const first = page.toggleCatalog('catalog:x', true);
        expect(page.toggles['catalog:x']?.busy).toBe(true);
        await page.toggleCatalog('catalog:x', true);
        gate.reject(new Error('nope'));
        await first;
        expect(page.toggles['catalog:x']).toEqual({ busy: false, error: 'nope' });
    });

    it('an empty error message falls back to the catalog sentence', async () => {
        const { page } = make();
        await page.runAct('catalog:x', async () => { throw new Error(''); });
        expect(page.toggles['catalog:x']?.error).toBe('plugins.page.catalog.failed');
    });
});

describe('permission sheet reads', () => {
    it('the newest read wins even when an older one lands last', async () => {
        const slow = deferred<CplugSheet>();
        const reads = [slow.promise, Promise.resolve(sheet('new'))];
        const { page } = make({ loadSheet: () => reads.shift()! });
        page.readSheetFor('p');
        page.readSheetFor('p');
        await Promise.resolve();
        await Promise.resolve();
        slow.resolve(sheet('old'));
        await slow.promise;
        await Promise.resolve();
        expect(page.seenSheets['p']).toEqual(sheet('new'));
    });
});

describe('uninstall from the pane', () => {
    const plugin = { id: 'cplug:p', cplugId: 'p', name: 'P', thirdParty: true, publisher: 'acme' } as unknown as CplugItem;

    it('shows the refusal and re-reads nothing when the uninstall did not finish', async () => {
        uninstall.uninstallableRow.mockReturnValue({ id: 'acme/p' });
        uninstall.uninstallPlugin.mockResolvedValue({ done: false, error: 'busy' });
        const { page, reloadBuiltins } = make();
        await page.uninstallFromPane(plugin);
        expect(page.uninstallErrors['cplug:p']).toBe('busy');
        expect(page.uninstallingId).toBeNull();
        expect(reloadBuiltins).not.toHaveBeenCalled();
    });

    it('re-reads both lists when it finished', async () => {
        uninstall.uninstallableRow.mockReturnValue({ id: 'acme/p' });
        uninstall.uninstallPlugin.mockResolvedValue({ done: true, error: null });
        const catalog = fakeCatalog();
        const { page, reloadBuiltins } = make({ catalog });
        await page.uninstallFromPane(plugin);
        expect(reloadBuiltins).toHaveBeenCalledTimes(1);
        expect((catalog as unknown as { load: ReturnType<typeof vi.fn> }).load).toHaveBeenCalledTimes(1);
    });

    it('does nothing for a plugin with no ledger row', async () => {
        uninstall.uninstallableRow.mockReturnValue(undefined);
        const { page } = make();
        await page.uninstallFromPane(plugin);
        expect(uninstall.uninstallPlugin).not.toHaveBeenCalled();
    });
});
