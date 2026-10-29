/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import SideloadSwitch from './SideloadSwitch.svelte';
import SideloadLoadForm from './SideloadLoadForm.svelte';
import SideloadRowActions from './SideloadRowActions.svelte';
import { createSideloadStore, type SideloadApi } from './sideload-store.svelte';
import type { SideloadStatus } from './sideload-switch';

const t = (key: string, params?: Record<string, unknown> | null): string => (params && 'source' in params ? `${key}|${params.source}` : key);
const OFF: SideloadStatus = { enabled: false, expires_at: null, hours: 12, items: [] };
const ON: SideloadStatus = { enabled: true, expires_at: null, hours: null, items: [{ id: 'dev', item_id: 'local/dev', source: '/Users/me/dev', synced_at: 1, changed: [], git: null }] };
let mounted: Record<string, unknown>[] = [];
afterEach(() => { mounted.forEach((m) => unmount(m)); mounted = []; document.body.innerHTML = ''; });

async function settle(): Promise<void> {
    for (let i = 0; i < 12; i += 1) await tick();
    flushSync();
}

function api(overrides: Partial<SideloadApi> = {}): SideloadApi {
    return { load: async () => OFF, save: vi.fn(async () => ON), folder: vi.fn(async () => ({})), git: vi.fn(async () => ({})),
             resync: vi.fn(async () => ({})), remove: vi.fn(async () => ({})), ...overrides };
}

async function drawSwitch(calls: SideloadApi): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(SideloadSwitch, { target, props: { t, store: createSideloadStore(calls) } }));
    await settle();
    return target;
}

describe('the turn-on confirm', () => {
    test('turning on opens the danger confirm with the risk line and writes nothing until confirmed', async () => {
        const calls = api();
        const root = await drawSwitch(calls);
        root.querySelector<HTMLElement>('[data-sideload-toggle]')!.click();
        await settle();
        expect(calls.save).not.toHaveBeenCalled();
        expect(document.querySelector('[data-sideload-risk]')?.textContent).toBe('plugins.page.sideload.warning.risk');
        const go = document.querySelector<HTMLButtonElement>('[data-sideload-confirm-go]')!;
        expect(go.getAttribute('data-btn')).toBe('danger');
        expect(document.querySelector('[data-sideload-confirm-cancel]')?.getAttribute('data-btn')).toBe('secondary');
        go.click();
        await settle();
        expect(calls.save).toHaveBeenCalledExactlyOnceWith(true, 12);
        expect(document.querySelector('[data-sideload-risk]')).toBeNull();
    });

    test('cancel leaves the switch off and writes nothing', async () => {
        const calls = api();
        const root = await drawSwitch(calls);
        root.querySelector<HTMLElement>('[data-sideload-toggle]')!.click();
        await settle();
        document.querySelector<HTMLButtonElement>('[data-sideload-confirm-cancel]')!.click();
        await settle();
        expect(calls.save).not.toHaveBeenCalled();
        expect(document.querySelector('[data-sideload-risk]')).toBeNull();
        expect(root.querySelector('[data-sideload-toggle]')?.getAttribute('aria-checked')).toBe('false');
    });

    test('it asks every time the switch goes on, and never to turn it off', async () => {
        let state = OFF;
        const save = vi.fn(async (enabled: boolean) => (state = enabled ? ON : OFF));
        const root = await drawSwitch(api({ load: async () => state, save }));
        for (let round = 0; round < 2; round += 1) {
            root.querySelector<HTMLElement>('[data-sideload-toggle]')!.click();
            await settle();
            document.querySelector<HTMLButtonElement>('[data-sideload-confirm-go]')!.click();
            await settle();
            root.querySelector<HTMLElement>('[data-sideload-toggle]')!.click();
            await settle();
            expect(document.querySelector('[data-sideload-risk]'), 'turning off asks nothing').toBeNull();
        }
        expect(save.mock.calls).toEqual([[true, 12], [false, undefined], [true, 12], [false, undefined]]);
    });
});

describe('the on strip', () => {
    test('while on, the danger strip says unreviewed code can run and when it turns off', async () => {
        const root = await drawSwitch(api({ load: async () => ON }));
        const strip = root.querySelector('[data-sideload-strip]');
        expect(strip?.classList.contains('plp-warn')).toBe(true);
        expect(strip?.classList.contains('plp-danger')).toBe(true);
        expect(strip?.textContent).toContain('plugins.page.sideload.warning.strip');
        expect(strip?.querySelector('[data-sideload-until]')?.textContent).toBe('plugins.page.sideload.until_off');
    });

    test('while off, no strip', async () => {
        const root = await drawSwitch(api());
        expect(root.querySelector('[data-sideload-strip]')).toBeNull();
    });
});

describe('the load form warning', () => {
    function form(mode: 'folder' | 'git'): HTMLElement {
        const target = document.createElement('div');
        document.body.append(target);
        mounted.push(mount(SideloadLoadForm, { target, props: { mode, t, onFolder: vi.fn(async () => {}), onGit: vi.fn(async () => {}), onDone: vi.fn() } }));
        flushSync();
        return target;
    }

    function type(root: HTMLElement, selector: string, value: string): void {
        const input = root.querySelector<HTMLInputElement>(`${selector} input, input${selector}`)!;
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();
    }

    test('the folder form shows the danger line above the load button, naming the folder typed', () => {
        const root = form('folder');
        const line = () => root.querySelector('[data-sideload-warning]');
        expect(line()?.textContent).toBe('plugins.page.sideload.warning.load|plugins.page.sideload.warning.load_source');
        expect(line()?.classList.contains('plp-danger')).toBe(true);
        type(root, '[data-sideload-path]', '/Users/me/dev/clock');
        expect(line()?.textContent).toBe('plugins.page.sideload.warning.load|/Users/me/dev/clock');
        const order = line()!.compareDocumentPosition(root.querySelector('[data-sideload-submit]')!);
        expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    test('the git form names the repository', () => {
        const root = form('git');
        type(root, '[data-sideload-url]', 'git@github.com:me/clock.git');
        expect(root.querySelector('[data-sideload-warning]')?.textContent).toBe('plugins.page.sideload.warning.load|git@github.com:me/clock.git');
    });
});

describe('a re-sync that changed files', () => {
    async function row(resync: SideloadApi['resync']): Promise<HTMLElement> {
        const store = createSideloadStore(api({ load: async () => ON, resync }));
        await store.refresh();
        const target = document.createElement('div');
        document.body.append(target);
        mounted.push(mount(SideloadRowActions, { target, props: { store, name: 'dev', t } }));
        await settle();
        target.querySelector<HTMLButtonElement>('[data-sideload-resync="dev"]')!.click();
        await settle();
        return target;
    }

    test('names the source in the danger color', async () => {
        const root = await row(vi.fn(async () => ({ unchanged: false, changed: ['main.py'] })));
        const line = root.querySelector('[data-sideload-resynced]');
        expect(line?.textContent).toBe('plugins.page.sideload.warning.resynced|/Users/me/dev');
        expect(line?.classList.contains('plp-danger')).toBe(true);
    });

    test('an unchanged re-sync says nothing', async () => {
        const root = await row(vi.fn(async () => ({ unchanged: true, changed: [] })));
        expect(root.querySelector('[data-sideload-resynced]')).toBeNull();
    });
});
