/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import SideloadKinds from './SideloadKinds.svelte';
import SideloadLoadForm from './SideloadLoadForm.svelte';
import SideloadRowActions from './SideloadRowActions.svelte';
import { createSideloadStore, type SideloadApi } from './sideload-store.svelte';
import { removeSideload, sideloadFolder, type SideloadStatus } from './sideload-switch';

const t = (key: string, vars?: Record<string, unknown> | null): string => (vars ? `${key} ${JSON.stringify(vars)}` : key);
const SHEET = {
    code: 'consent_required', kind: 'plugin', name: 'hooked', digest: 'd'.repeat(64), digest_prefix: 'dddddddddddd', body_sha: 'b'.repeat(64),
    body: '{"name":"hooked"}', publisher: 'local', requires_consent: true, total_bytes: 10, mcp_servers: [],
    files: [{ path: 'hooks/hooks.json', size: 5, exec: true }, { path: 'commands/hi.md', size: 5, exec: false }],
};
const CONSENT = { digest: SHEET.digest, body_sha: SHEET.body_sha, scripts: true as const };
const STATUS: SideloadStatus = {
    enabled: true, expires_at: null, hours: null,
    items: [
        { id: 'clock', kind: 'cplug', item_id: 'local/clock', source: '/dev/clock', synced_at: 1, changed: [] },
        { id: 'neon', kind: 'theme', item_id: 'local/neon', source: '/dev/neon', synced_at: 1, changed: [] },
        { id: 'neon', kind: 'skill', item_id: 'local/neon', source: '/dev/neon-skill', synced_at: 1, changed: [] },
    ],
};
let mounted: Record<string, unknown>[] = [];
afterEach(() => { mounted.forEach((m) => unmount(m)); mounted = []; document.body.innerHTML = ''; });

async function settle(): Promise<void> {
    for (let i = 0; i < 12; i += 1) await tick();
    flushSync();
}

const needsConsent = () => new ApiError('consent', 409, null, { detail: SHEET });

function calls(overrides: Partial<SideloadApi> = {}): SideloadApi {
    return { load: async () => STATUS, save: vi.fn(), folder: vi.fn(async () => ({})), git: vi.fn(async () => ({})),
             resync: vi.fn(async () => ({})), remove: vi.fn(async () => ({})), ...overrides };
}

function put(root: HTMLElement, selector: string, value: string): void {
    const input = root.querySelector<HTMLInputElement>(selector)!;
    input.value = value;
    input.dispatchEvent(new Event('input'));
}

async function loadForm(onFolder: (path: string, name: string | null, consent?: unknown) => Promise<void>, onDone = vi.fn()) {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(SideloadLoadForm, { target, props: { mode: 'folder', t, onFolder, onGit: vi.fn(), onDone } }));
    await settle();
    put(target, '[data-sideload-path]', '/dev/hooked');
    await settle();
    target.querySelector<HTMLFormElement>('form')!.requestSubmit();
    await settle();
    return { target, onDone };
}

describe('the consent sheet for a folder that runs code', () => {
    test('the load form shows the catalog sheet, gates on the tick, and sends the server-named digest and sha', async () => {
        const onFolder = vi.fn(async (_p: string, _n: string | null, consent?: unknown) => { if (!consent) throw needsConsent(); });
        const { target, onDone } = await loadForm(onFolder);
        expect(target.querySelector('[data-sideload-consent]')).not.toBeNull();
        expect(target.textContent).toContain('hooks/hooks.json');
        const confirm = target.querySelector<HTMLButtonElement>('[data-sideload-consent-confirm]')!;
        expect(confirm.disabled).toBe(true);
        expect(onDone).not.toHaveBeenCalled();
        target.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
        await settle();
        expect(confirm.disabled).toBe(false);
        confirm.click();
        await settle();
        expect(onFolder).toHaveBeenLastCalledWith('/dev/hooked', null, CONSENT);
        expect(onDone).toHaveBeenCalledOnce();
    });

    test('cancel sends nothing; a sheet with no digest cannot be confirmed at all', async () => {
        const onFolder = vi.fn(async () => { throw new ApiError('consent', 409, null, { detail: { ...SHEET, digest: '' } }); });
        const { target } = await loadForm(onFolder);
        target.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
        await settle();
        expect(target.querySelector<HTMLButtonElement>('[data-sideload-consent-confirm]')!.disabled).toBe(true);
        target.querySelector<HTMLButtonElement>('[data-sideload-consent-cancel]')!.click();
        await settle();
        expect(onFolder).toHaveBeenCalledOnce();
        expect(target.querySelector('[data-sideload-consent]')).toBeNull();
    });

    test('a re-sync that brings new code asks on the row and resends with the consent', async () => {
        const resync = vi.fn(async (_item: unknown, consent?: unknown) => { if (!consent) throw needsConsent(); return {}; });
        const store = createSideloadStore(calls({ resync }), vi.fn());
        await store.refresh();
        const target = document.createElement('div');
        document.body.append(target);
        mounted.push(mount(SideloadRowActions, { target, props: { store, name: 'neon', kind: 'theme', t } }));
        await settle();
        target.querySelector<HTMLButtonElement>('[data-sideload-resync="neon"]')!.click();
        await settle();
        target.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
        await settle();
        target.querySelector<HTMLButtonElement>('[data-sideload-consent-confirm]')!.click();
        await settle();
        expect(resync).toHaveBeenLastCalledWith(STATUS.items[1], CONSENT);
        expect(target.querySelector('[data-sideload-consent]')).toBeNull();
    });
});

describe('refusals the page words itself', () => {
    test('an edited installed copy and a mod each get their own sentence, said on the row', async () => {
        for (const code of ['target_changed', 'kind_unsupported_mod']) {
            const resync = vi.fn(async () => { throw new ApiError('x', 409, null, { detail: { code, detail: 'server words' } }); });
            const store = createSideloadStore(calls({ resync }), vi.fn());
            await store.refresh();
            const target = document.createElement('div');
            document.body.append(target);
            mounted.push(mount(SideloadRowActions, { target, props: { store, name: 'neon', kind: 'theme', t } }));
            await settle();
            target.querySelector<HTMLButtonElement>('[data-sideload-resync="neon"]')!.click();
            await settle();
            expect(target.querySelector('[data-sideload-row-error]')?.textContent).toBe(`plugins.page.sideload.refused.${code}`);
        }
    });
});

describe('the kind on the sideload list', () => {
    test('each row names its kind; a plugin and a sidecar plugin are one word; actions only for what the page has no card for', async () => {
        const api = calls();
        const store = createSideloadStore(api, vi.fn());
        await store.refresh();
        const target = document.createElement('div');
        document.body.append(target);
        mounted.push(mount(SideloadKinds, { target, props: { store, t } }));
        await settle();
        const rows = [...target.querySelectorAll('[data-sideload-kind-row]')];
        expect(rows.map((r) => r.querySelector('[data-sideload-kind]')!.textContent)).toEqual([
            'plugins.page.sideload.kind.plugin', 'plugins.page.sideload.kind.theme', 'plugins.page.sideload.kind.skill',
        ]);
        expect(target.querySelector('[data-sideload-remove="clock"]')).toBeNull();
        target.querySelectorAll<HTMLButtonElement>('[data-sideload-remove="neon"]')[1]!.click();
        await settle();
        expect(api.remove).toHaveBeenCalledExactlyOnceWith('neon', 'skill');
    });

    test('the calls carry the kind and the consent', async () => {
        const fetcher = vi.fn(async (_path: string, _init?: RequestInit) => ({}));
        await removeSideload('neon', 'theme', fetcher as never);
        await sideloadFolder('/dev/x', null, fetcher as never, CONSENT);
        expect(fetcher.mock.calls[0]![0]).toBe('/cplug-owner/sideload?name=neon&kind=theme');
        expect(JSON.parse(fetcher.mock.calls[1]![1]!.body as string)).toEqual({ path: '/dev/x', consent: CONSENT });
    });
});
