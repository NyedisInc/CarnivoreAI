/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import { ApiError, resourcePush } from '../sdk';
import { setLocale, t } from '../../lib/i18n/index.svelte';
import type { Fetcher } from './crate-api';
import CratePanel from './CratePanel.svelte';
import ProjectCrates from './ProjectCrates.svelte';
import RemoveDialog from './RemoveDialog.svelte';

const opened = vi.hoisted(() => [] as Array<{ component: string; props: Record<string, unknown> }>);
const projectFetch = vi.hoisted(() => ({ bundles: [] as Array<Record<string, unknown>> }));
vi.mock('../sdk', async (original) => ({
    ...(await original<Record<string, unknown>>()),
    openModal: vi.fn(async (component: { name?: string }, props: Record<string, unknown>) => {
        opened.push({ component: String(component?.name ?? ''), props });
        return null;
    }),
    authFetch: vi.fn(async () => ({ bundles: projectFetch.bundles })),
}));

setLocale('en');

const SUMMARY = {
    folders: { primary: { path: '/state/crates', state: 'ok', reason: null, free_bytes: 5 * 1024 ** 3 }, second: { path: '/second', state: 'ok', reason: null, free_bytes: 5 * 1024 ** 3 } },
    encrypt_default: false, recipients: [], running_job: null, bundles: 2,
};
const LIVE = 'crate-20261017T000000Z-project-1a2b3c4d';
const GONE = 'crate-20261018T000000Z-project-5e6f7a8b';
const FOUND = 'crate-20261019T000000Z-project-9f8e7d6c.crate';
const SHARE = 'share-20261019T000000Z-session-11223344.crate.age';

function bundle(id: string, removed: boolean, copies: Array<[string, string]>): Record<string, unknown> {
    return {
        bundle_id: id, sha256: 'ab'.repeat(32), scope: 'project', label: null, created_at: '2026-10-17T00:00:00Z', verified_at: null,
        local_removed: removed, conversations: 1, locations: copies.map(([where, state]) => ({ where, verified_at: null, state })),
    };
}

function world(): Fetcher {
    return (async (path: string) => {
        if (path === '/cplugs/crate/summary') return SUMMARY;
        if (path === '/cplugs/crate/bundles') {
            return { bundles: [bundle(LIVE, false, [[`/state/crates/${LIVE}.crate`, 'present'], [`/second/${LIVE}.crate`, 'present']]),
                bundle(GONE, true, [[`/state/crates/${GONE}.crate`, 'missing']])] };
        }
        if (path === '/cplugs/crate/folders/primary/crates') {
            return { crates: [
                { name: FOUND, size: 4096, mtime: 1792100000, share: false, encrypted: false, sha256_sidecar: null, bundle_id: null },
                { name: SHARE, size: 512, mtime: 1792100100, share: true, encrypted: true, sha256_sidecar: null, bundle_id: null },
            ] };
        }
        if (path === '/cplugs/crate/folders/second/crates') return { crates: [] };
        throw new Error(`no route for ${path}`);
    }) as unknown as Fetcher;
}

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) {
        await new Promise((done) => setTimeout(done, 5));
        await Promise.resolve();
        flushSync();
    }
}

const mounted: Array<Record<string, unknown>> = [];

function place(component: unknown, props: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(component as never, { target, props }) as Record<string, unknown>);
    return target;
}

afterEach(() => {
    for (const instance of mounted.splice(0)) unmount(instance);
    document.body.innerHTML = '';
    opened.length = 0;
    projectFetch.bundles = [];
    resourcePush().store.closed();
});

describe('the rows', () => {
    test('the rows open the confirm on the bundle id, or on the folder and name of a found crate', async () => {
        const target = place(CratePanel, { fetcher: world() });
        await settle();
        target.querySelector<HTMLElement>(`[data-crt-remove="${LIVE}"]`)!.click();
        await settle();
        expect(opened.at(-1)!.props).toMatchObject({ target: { bundleId: LIVE }, name: LIVE, recorded: true, otherCopy: true });
        target.querySelector<HTMLElement>(`[data-crt-remove-found="${FOUND}"]`)!.click();
        await settle();
        expect(opened.at(-1)!.props).toMatchObject({ target: { folder: 'primary', name: FOUND }, name: FOUND });
        expect(opened.at(-1)!.props.recorded).toBeUndefined();
        expect(target.querySelector(`[data-crt-remove-found="${SHARE}"]`)).toBeNull();
    });

    test('a removed crate offers nothing and says it is in the trash', async () => {
        const target = place(CratePanel, { fetcher: world() });
        await settle();
        const row = target.querySelector(`[data-crt-bundle="${GONE}"]`)!;
        expect(row.textContent).toContain(t('cplug.crate.panel.removed'));
        for (const attr of ['data-crt-restore', 'data-crt-verify', 'data-crt-copy', 'data-crt-remove']) expect(row.querySelector(`[${attr}]`)).toBeNull();
        expect(target.querySelector(`[data-crt-bundle="${LIVE}"] [data-crt-restore]`)).not.toBeNull();
    });

    test('the project page row opens the confirm too, and shows a removed crate as removed', async () => {
        projectFetch.bundles = [bundle(LIVE, false, [[`/state/crates/${LIVE}.crate`, 'present']]), bundle(GONE, true, [[`/state/crates/${GONE}.crate`, 'missing']])];
        const header = createRawSnippet(() => ({ render: () => '<div data-header></div>' }));
        const target = place(ProjectCrates, { projectId: 7, header, isFolded: () => false, age: () => 'now', previewOf: (count: number) => count });
        await settle();
        target.querySelector<HTMLElement>(`[data-crt-remove="${LIVE}"]`)!.click();
        await settle();
        expect(opened.at(-1)!.props).toMatchObject({ target: { bundleId: LIVE }, recorded: true, otherCopy: false });
        const row = target.querySelector(`[data-crt-crate="${GONE}"]`)!;
        expect(row.querySelector('[data-crt-copies]')!.getAttribute('data-crt-copies')).toBe('removed');
        expect(row.querySelector('button')).toBeNull();
    });
});

describe('the confirm dialog', () => {
    function dialog(fetcher: Fetcher, props: Record<string, unknown> = {}): { target: HTMLElement; closed: unknown[] } {
        const closed: unknown[] = [];
        const target = place(RemoveDialog, { target: { bundleId: LIVE }, name: 'before the move', recorded: true, otherCopy: true, close: (v: unknown) => closed.push(v), fetcher, ...props });
        return { target, closed };
    }

    test('remove calls the route with the tick, then closes true; cancel closes null', async () => {
        const calls: Array<{ path: string; body: unknown }> = [];
        const fetcher = (async (path: string, init?: RequestInit) => {
            calls.push({ path, body: JSON.parse(String(init?.body)) });
            return { removed: [{ folder: 'primary', name: `${LIVE}.crate` }], bundle_id: LIVE, local_removed: false, skipped: [] };
        }) as unknown as Fetcher;
        const { target, closed } = dialog(fetcher);
        expect(target.textContent).toContain(t('cplug.crate.remove.recorded'));
        target.querySelector<HTMLElement>('[data-crt-remove-second] , [data-crt-remove-second] input')?.click();
        await settle();
        target.querySelector<HTMLElement>('[data-crt-remove-go]')!.click();
        await settle();
        expect(calls).toEqual([{ path: '/cplugs/crate/crates/remove', body: { bundle_id: LIVE, also_second: true } }]);
        expect(closed).toEqual([true]);
        const second = dialog(fetcher);
        [...second.target.querySelectorAll<HTMLElement>('[data-btn="secondary"]')].at(-1)!.click();
        expect(second.closed).toEqual([null]);
        expect(calls).toHaveLength(1);
    });

    test('a found crate is named by folder and name and has no second-folder tick; a refusal stays on screen', async () => {
        const calls: unknown[] = [];
        const fetcher = (async (_path: string, init?: RequestInit) => {
            calls.push(JSON.parse(String(init?.body)));
            throw new ApiError('refused', 409, null, { detail: { code: 'crate_in_use', detail: 'x' } });
        }) as unknown as Fetcher;
        const { target, closed } = dialog(fetcher, { target: { folder: 'primary', name: FOUND }, name: FOUND, recorded: false, otherCopy: false });
        expect(target.querySelector('[data-crt-remove-second]')).toBeNull();
        expect(target.querySelector('[data-btn="danger"]')).not.toBeNull();
        target.querySelector<HTMLElement>('[data-crt-remove-go]')!.click();
        await settle();
        expect(calls).toEqual([{ folder: 'primary', name: FOUND, also_second: false }]);
        expect(closed).toEqual([]);
        expect(target.querySelector('[data-crt-problem]')!.textContent).toBe(t('cplug.crate.error.crate_in_use'));
    });
});
