/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import { ApiError, resourcePush } from '../sdk';
import { setLocale, t } from '../../lib/i18n/index.svelte';
import type { Fetcher } from './crate-api';
import CratePanel from './CratePanel.svelte';
import ProjectCrates from './ProjectCrates.svelte';
import RestoredList from './RestoredList.svelte';
import UndoDialog from './UndoDialog.svelte';
import { downloadCrate, parseRestored, undoBlockers } from './undo-api';

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

const IMP = 'imp-20261019T120000Z-1a2b3c4d';
const OLD = 'imp-20261018T120000Z-5e6f7a8b';
const NOTHING = 'imp-20261017T120000Z-9f8e7d6c';
const LIVE = 'crate-20261017T000000Z-project-1a2b3c4d';
const GONE = 'crate-20261018T000000Z-project-5e6f7a8b';
const FOUND = 'crate-20261019T000000Z-project-9f8e7d6c.crate';
const SHARE = 'share-20261019T000000Z-session-11223344.crate';
const SUMMARY = {
    folders: { primary: { path: '/state/crates', state: 'ok', reason: null, free_bytes: 5 * 1024 ** 3 }, second: null },
    encrypt_default: false, recipients: [], running_job: null, bundles: 2,
};

function receipt(id: string, state: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
    return { import_id: id, state, project: { name: 'Proj One' }, finished_at: '2026-10-19T12:00:00Z', sessions: [{ session_uuid: 'u1' }, { session_uuid: 'u2' }],
        files: { written: 5 }, ...extra };
}
const RECEIPTS = [receipt(IMP, 'done'), receipt(OLD, 'undone', { undone_at: '2026-10-19T13:00:00Z' }), receipt(NOTHING, 'noop')];

function bundle(id: string, removed: boolean, where: string, state: string): Record<string, unknown> {
    return { bundle_id: id, sha256: 'ab'.repeat(32), scope: 'project', label: null, created_at: '2026-10-17T00:00:00Z', verified_at: null,
        local_removed: removed, conversations: 1, locations: [{ where, verified_at: null, state }] };
}

function world(): Fetcher {
    return (async (path: string) => {
        if (path === '/cplugs/crate/summary') return SUMMARY;
        if (path === '/cplugs/crate/bundles') return { bundles: [bundle(LIVE, false, `/state/crates/${LIVE}.crate`, 'present'), bundle(GONE, true, `/state/crates/${GONE}.crate`, 'missing')] };
        if (path === '/cplugs/crate/imports') return { imports: RECEIPTS };
        if (path === '/cplugs/crate/folders/primary/crates') {
            return { crates: [
                { name: FOUND, size: 4096, mtime: 1792100000, share: false, encrypted: false, sha256_sidecar: null, bundle_id: null },
                { name: SHARE, size: 512, mtime: 1792100100, share: true, encrypted: false, sha256_sidecar: null, bundle_id: null },
            ] };
        }
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

describe('the download buttons', () => {
    test('the helper asks the streamed route (relative to /api/v1) with the name encoded, and falls back to the crate name', async () => {
        const paths: string[] = [];
        const bytes = vi.fn(async (path: string) => {
            paths.push(path);
            return new Blob(['x']);
        }) as unknown as Fetcher;
        const urls = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:x');
        expect(await downloadCrate({ bundleId: LIVE }, 'my crate', 'crate', bytes)).toBe('my crate');
        await downloadCrate({ folder: 'second', name: FOUND }, FOUND, 'crate', bytes);
        await downloadCrate({ folder: 'primary', name: 'a b/../c.crate' }, 'c', 'crate', bytes);
        await downloadCrate({ bundleId: LIVE }, 'c', 'sha256', bytes);
        urls.mockRestore();
        expect(paths).toEqual([
            `/cplugs/crate/bundles/${LIVE}/download`,
            `/cplugs/crate/folders/second/crates/${FOUND}/download`,
            '/cplugs/crate/folders/primary/crates/a%20b%2F..%2Fc.crate/download',
            `/cplugs/crate/bundles/${LIVE}/download?part=sha256`,
        ]);
    });

    test('every crate row has a download button; a removed crate has none', async () => {
        const target = place(CratePanel, { fetcher: world() });
        await settle();
        expect(target.querySelector(`button[data-crt-download="${LIVE}"]`)).not.toBeNull();
        for (const name of [FOUND, SHARE]) expect(target.querySelector(`button[data-crt-download-found="${name}"]`)).not.toBeNull();
        expect(target.querySelector(`[data-crt-bundle="${GONE}"] [data-crt-download]`)).toBeNull();
        expect(target.querySelector('a[download]')).toBeNull();
    });

    test('the project page row has one too', async () => {
        projectFetch.bundles = [bundle(LIVE, false, `/state/crates/${LIVE}.crate`, 'present'), bundle(GONE, true, `/state/crates/${GONE}.crate`, 'missing')];
        const header = createRawSnippet(() => ({ render: () => '<div data-header></div>' }));
        const target = place(ProjectCrates, { projectId: 7, header, isFolded: () => false, age: () => 'now', previewOf: (count: number) => count });
        await settle();
        expect(target.querySelector(`button[data-crt-download="${LIVE}"]`)).not.toBeNull();
        expect(target.querySelector(`[data-crt-crate="${GONE}"] [data-crt-download]`)).toBeNull();
    });
});

describe('the restored list', () => {
    test('only a finished restore offers undo, and it opens the confirm on that import', async () => {
        const target = place(CratePanel, { fetcher: world() });
        await settle();
        expect(target.querySelector(`[data-crt-restored-row="${IMP}"] [data-crt-undo]`)).not.toBeNull();
        for (const id of [OLD, NOTHING]) expect(target.querySelector(`[data-crt-restored-row="${id}"] [data-crt-undo]`)).toBeNull();
        expect(target.querySelector(`[data-crt-restored-row="${OLD}"]`)!.textContent).toContain('undone');
        target.querySelector<HTMLElement>(`[data-crt-undo="${IMP}"]`)!.click();
        await settle();
        expect(opened.at(-1)!.props).toMatchObject({ importId: IMP, name: 'Proj One' });
    });

    test('a running job holds the undo button, and a row with no import id is not a row', async () => {
        const onChange = vi.fn();
        const target = place(RestoredList, { restored: [parseRestored(RECEIPTS[0])!], busy: true, onChange });
        expect(target.querySelector<HTMLButtonElement>('[data-crt-undo]')!.disabled).toBe(true);
        expect(parseRestored({ state: 'done' })).toBeNull();
    });
});

describe('the confirm dialog', () => {
    const PREVIEW = { import_id: IMP, ok: true, blockers: [], rows_to_remove: 9, rows_to_put_back: 1, files: 4, folders: 3,
        kept: [{ what: 'sessions row 3', why: 'changed since the import' }] };

    function dialog(fetcher: Fetcher): { target: HTMLElement; closed: unknown[] } {
        const closed: unknown[] = [];
        return { target: place(UndoDialog, { importId: IMP, name: 'Proj One', close: (v: unknown) => closed.push(v), fetcher }), closed };
    }

    test('it reads the preview, says what stays, undoes on the button and shows the outcome', async () => {
        const calls: Array<{ method: string; path: string }> = [];
        const fetcher = (async (path: string, init?: RequestInit) => {
            calls.push({ method: init?.method ?? 'GET', path });
            if (init?.method === 'POST') return { import_id: IMP, state: 'undone', undo: { rows: { deleted: 9, restored: 1, reverted: 0 }, files_removed: 4, folders_removed: 3, kept: PREVIEW.kept, errors: [], file_errors: [] } };
            return PREVIEW;
        }) as unknown as Fetcher;
        const { target, closed } = dialog(fetcher);
        await settle();
        expect(target.querySelector('[data-crt-undo-body]')!.textContent).toContain('9 database rows');
        expect(target.querySelector('[data-crt-undo-body]')!.textContent).toContain('4 files and 3 folders');
        expect(target.querySelector('[data-crt-undo-stays]')!.textContent).toBe(t('cplug.crate.undo.stays'));
        expect(target.querySelector('[data-crt-undo-kept]')!.textContent).toContain('sessions row 3');
        expect(target.querySelector('[data-crt-undo-kept]')!.textContent).toContain(t('cplug.crate.undo.why.changed_since_the_import'));
        expect(target.querySelector('[data-btn="secondary"]')).not.toBeNull();
        target.querySelector<HTMLElement>('[data-crt-undo-go]')!.click();
        await settle();
        expect(calls).toEqual([{ method: 'GET', path: `/cplugs/crate/imports/${IMP}/undo` }, { method: 'POST', path: `/cplugs/crate/imports/${IMP}/undo` }]);
        expect(target.querySelector('[data-crt-undo-done]')!.textContent).toContain('9 database rows, 4 files and 3 empty folders');
        expect(closed).toEqual([]);
        target.querySelector<HTMLElement>('[data-crt-undo-close]')!.click();
        expect(closed).toEqual([true]);
    });

    test('a blocker keeps the undo off and says why; cancel closes null', async () => {
        const fetcher = (async () => ({ ...PREVIEW, ok: false, blockers: [{ code: 'later_import', detail: 'x' }] })) as unknown as Fetcher;
        const { target, closed } = dialog(fetcher);
        await settle();
        expect(target.querySelector<HTMLButtonElement>('[data-crt-undo-go]')!.disabled).toBe(true);
        expect(target.querySelector('[data-crt-undo-blocker]')!.textContent).toBe(t('cplug.crate.undo.blocked.later_import'));
        [...target.querySelectorAll<HTMLElement>('[data-btn="secondary"]')].at(-1)!.click();
        expect(closed).toEqual([null]);
    });

    test('a refusal stays on screen with its blockers', async () => {
        const refusal = new ApiError('refused', 409, null, { detail: { code: 'undo_blocked', detail: [{ code: 'job_busy', detail: 'x' }] } });
        expect(undoBlockers(refusal).map((b) => b.code)).toEqual(['job_busy']);
        const fetcher = (async (_path: string, init?: RequestInit) => {
            if (init?.method === 'POST') throw refusal;
            return PREVIEW;
        }) as unknown as Fetcher;
        const { target, closed } = dialog(fetcher);
        await settle();
        target.querySelector<HTMLElement>('[data-crt-undo-go]')!.click();
        await settle();
        expect(closed).toEqual([]);
        expect(target.querySelector('[data-crt-undo-blocker]')!.textContent).toBe(t('cplug.crate.undo.blocked.job_busy'));
        expect(target.querySelector('[data-crt-undo-go]')).not.toBeNull();
    });
});
