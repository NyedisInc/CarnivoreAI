/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import SideloadRowActions from './SideloadRowActions.svelte';
import SideloadLoadForm from './SideloadLoadForm.svelte';
import { createSideloadStore, type SideloadApi } from './sideload-store.svelte';
import { resyncSideload, type SideloadStatus } from './sideload-switch';

const t = (key: string): string => key;
const GIT = { url: 'git@github.com:me/clock.git', ref: 'main', subdir: 'plugin', commit: 'abcdef1234', synced_at: 1 };
const STATUS: SideloadStatus = {
    enabled: true, expires_at: null, hours: null,
    items: [
        { id: 'clock', item_id: 'local/clock', source: '/state/cplugs/sideload-git/clock/plugin', synced_at: 1, changed: [], git: GIT },
        { id: 'dev', item_id: 'local/dev', source: '/Users/me/dev', synced_at: 1, changed: [], git: null },
    ],
};
let mounted: Record<string, unknown>[] = [];
afterEach(() => { mounted.forEach((m) => unmount(m)); mounted = []; document.body.innerHTML = ''; });

async function settle(): Promise<void> {
    for (let i = 0; i < 12; i += 1) await tick();
    flushSync();
}

function calls(overrides: Partial<SideloadApi> = {}): SideloadApi {
    return { load: async () => STATUS, save: vi.fn(), folder: vi.fn(async () => ({})), git: vi.fn(async () => ({})),
             resync: vi.fn(async () => ({})), remove: vi.fn(async () => ({})), ...overrides };
}

async function row(api: SideloadApi, name: string, onChanged = vi.fn()) {
    const store = createSideloadStore(api, onChanged);
    await store.refresh();
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(SideloadRowActions, { target, props: { store, name, t } }));
    await settle();
    return target;
}

const refusal = (code: string, said: string) => new ApiError(said, 422, null, { detail: { code, detail: said } });

describe('SideloadRowActions', () => {
    test('a git row shows repo @ ref (short sha) and both buttons; re-sync passes the recorded item, remove the name', async () => {
        const api = calls();
        const changed = vi.fn();
        const root = await row(api, 'clock', changed);
        expect(root.querySelector('[data-sideload-source]')?.textContent).toBe('github.com:me/clock/plugin @ main (abcdef1)');
        root.querySelector<HTMLButtonElement>('[data-sideload-resync="clock"]')!.click();
        await settle();
        expect(api.resync).toHaveBeenCalledExactlyOnceWith(STATUS.items[0]);
        root.querySelector<HTMLButtonElement>('[data-sideload-remove="clock"]')!.click();
        await settle();
        expect(api.remove).toHaveBeenCalledExactlyOnceWith('clock');
        expect(changed).toHaveBeenCalledTimes(2);
    });

    test('a folder row shows the folder; a refusal is in plain words; an unknown name draws nothing', async () => {
        const api = calls({ resync: vi.fn(async () => { throw refusal('source_missing', 'give the absolute path'); }) });
        const root = await row(api, 'dev');
        expect(root.querySelector('[data-sideload-source]')?.textContent).toBe('/Users/me/dev');
        root.querySelector<HTMLButtonElement>('[data-sideload-resync="dev"]')!.click();
        await settle();
        expect(root.querySelector('[data-sideload-row-error]')?.textContent).toBe('plugins.page.sideload.refused.source_missing');
        expect((await row(calls(), 'other')).querySelector('[data-sideload-row]')).toBeNull();
    });

    test('re-sync goes to the git route with the record, or the folder route with the same path', async () => {
        const fetcher = vi.fn(async (_path: string, _init?: RequestInit) => ({}));
        await resyncSideload(STATUS.items[0]!, fetcher as never);
        await resyncSideload(STATUS.items[1]!, fetcher as never);
        expect(fetcher.mock.calls.map((c) => [c[0], JSON.parse(c[1]?.body as string)])).toEqual([
            ['/cplug-owner/sideload/git', { url: GIT.url, ref: 'main', subdir: 'plugin', name: 'clock' }],
            ['/cplug-owner/sideload', { path: '/Users/me/dev', name: 'dev' }],
        ]);
    });
});

describe('SideloadLoadForm', () => {
    async function form(mode: 'folder' | 'git', props: Record<string, unknown>) {
        const target = document.createElement('div');
        document.body.append(target);
        mounted.push(mount(SideloadLoadForm, { target, props: { mode, t, onFolder: vi.fn(), onGit: vi.fn(), onDone: vi.fn(), ...props } }));
        await settle();
        return target;
    }

    function type(root: HTMLElement, selector: string, value: string): void {
        const input = root.querySelector<HTMLInputElement>(selector)!;
        input.value = value;
        input.dispatchEvent(new Event('input'));
    }

    test('git posts the url, ref and subfolder, then closes', async () => {
        const onGit = vi.fn(async () => {});
        const onDone = vi.fn();
        const root = await form('git', { onGit, onDone });
        expect(root.querySelector<HTMLButtonElement>('[data-sideload-submit]')!.disabled).toBe(true);
        type(root, '[data-sideload-url]', 'git@github.com:me/clock.git');
        type(root, '[data-sideload-ref]', 'v1');
        type(root, '[data-sideload-subdir]', 'plugin');
        await settle();
        root.querySelector<HTMLFormElement>('form')!.requestSubmit();
        await settle();
        expect(onGit).toHaveBeenCalledExactlyOnceWith({ url: 'git@github.com:me/clock.git', ref: 'v1', subdir: 'plugin', name: '' });
        expect(onDone).toHaveBeenCalledOnce();
    });

    test('a refused folder stays open and says why', async () => {
        const onFolder = vi.fn(async () => { throw refusal('git_url_refused', 'x'); });
        const onDone = vi.fn();
        const root = await form('folder', { onFolder, onDone });
        type(root, '[data-sideload-path]', '/tmp/p');
        await settle();
        root.querySelector<HTMLFormElement>('form')!.requestSubmit();
        await settle();
        expect(onFolder).toHaveBeenCalledExactlyOnceWith('/tmp/p', null);
        expect(onDone).not.toHaveBeenCalled();
        expect(root.querySelector('[data-sideload-error]')?.textContent).toBe('plugins.page.sideload.refused.git_url_refused');
    });
});
