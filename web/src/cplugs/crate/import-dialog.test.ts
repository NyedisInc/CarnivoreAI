/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { flushSync, mount, unmount } from 'svelte';

import { resourcePush } from '../sdk';
import { ApiError } from '../sdk';
import { setLocale, t } from '../../lib/i18n/index.svelte';
import type { Fetcher } from './crate-api';
import { importBody, parseImportPlan } from './import-api';
import ImportDialog from './ImportDialog.svelte';
import plans from './import-plans.fixture.json';

setLocale('en');

interface Call {
    path: string;
    method: string;
    body: Record<string, unknown> | null;
}

function server(routes: Record<string, (call: Call) => unknown>): { fetcher: Fetcher; calls: Call[] } {
    const calls: Call[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        const call = { path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null };
        calls.push(call);
        const key = Object.keys(routes).find((prefix) => `${call.method} ${path}`.startsWith(prefix));
        if (!key) throw new Error(`no route for ${call.method} ${path}`);
        return routes[key]!(call);
    }) as unknown as Fetcher;
    return { fetcher, calls };
}

async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) {
        await Promise.resolve();
        flushSync();
    }
}

const mounted: Array<Record<string, unknown>> = [];

async function open(props: Record<string, unknown>): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(ImportDialog as never, { target, props: { source: { bundleId: 'crate-1' }, subject: 'before the move', close: () => {}, ...props } }) as Record<string, unknown>);
    await settle();
    return target;
}

const PREVIEW_BUTTON = '[data-crt-preview]';

async function click(target: HTMLElement, selector: string): Promise<void> {
    const el = target.querySelector<HTMLElement>(selector);
    if (selector === PREVIEW_BUTTON && el === null) {
        await settle();
        return;
    }
    expect(el, selector).not.toBeNull();
    el!.click();
    await settle();
}

afterEach(() => {
    for (const instance of mounted.splice(0)) unmount(instance);
    document.body.innerHTML = '';
    document.documentElement.removeAttribute('data-theme');
    resourcePush().store.closed();
});

const OWN = { ...plans.own, start_available: true };
const BLOCKED = plans.blocked;
const PLAN = 'POST /cplugs/crate/imports/plan';

describe('import dialog', () => {
    test.each(['dark', 'light'])('renders a real plan under the %s theme', async (theme) => {
        document.documentElement.setAttribute('data-theme', theme);
        const { fetcher, calls } = server({ [PLAN]: () => OWN });
        const target = await open({ fetcher });
        await click(target, '[data-crt-preview]');
        expect(calls[0]!.body).toEqual({ source: { bundle_id: 'crate-1' }, mode: 'same_paths', include_project_files: true, include_plugin_data: true, keep_conversations: true, file_backups: true });
        expect(target.querySelector('[data-crt-import-plan="ok"]')).not.toBeNull();
        expect(target.querySelector('[data-crt-import-provenance="own_verified"]')!.textContent).toContain(t('cplug.crate.import.provenance.written_here'));
        expect(target.querySelector('[data-crt-import-project]')!.textContent).toContain(t('cplug.crate.import.preview.action.create', { name: 'Proj One' }));
        expect(target.querySelector('[data-crt-import-root]')!.textContent).toContain('/Users/me/tmp/w/proj1');
        const conversations = target.querySelectorAll('[data-crt-import-conversation]');
        expect(conversations.length).toBe(OWN.conversations.length);
        expect(conversations[0]!.textContent).toContain(t('cplug.crate.import.preview.class.write'));
        expect(conversations[0]!.textContent).toContain(t('cplug.crate.import.preview.resume.native'));
        expect(target.querySelector('[data-crt-import-table="cloude.db.sessions"]')!.textContent).toContain(t('cplug.crate.import.preview.row_counts', { insert: 2, present: 0, kept: 0 }));
        expect(target.querySelector('[data-crt-go]')).not.toBeNull();
    });

    test('a good plan from a server with no start route disables restore and says so (no button points at a missing route)', async () => {
        const { fetcher } = server({ [PLAN]: () => ({ ...OWN, start_available: false }) });
        const target = await open({ fetcher });
        await click(target, '[data-crt-preview]');
        expect((target.querySelector('[data-crt-go]') as HTMLButtonElement).disabled).toBe(true);
        expect(target.querySelector('[data-crt-start-unavailable]')!.textContent).toBe(t('cplug.crate.import.start_unavailable'));
    });

    test('a blocked plan shows each blocker as a sentence and offers no restore', async () => {
        const { fetcher } = server({ [PLAN]: () => ({ ...BLOCKED, project: { ...BLOCKED.project, suggested_root: null } }) });
        const target = await open({ fetcher });
        await click(target, '[data-crt-preview]');
        expect(target.querySelector('[data-crt-import-provenance="foreign"]')).not.toBeNull();
        expect(target.querySelector('[data-crt-root-unusable]')).not.toBeNull();
        expect(target.querySelector('[data-crt-import-blocker="relocate_required"]')).toBeNull();
        expect(target.querySelector('[data-crt-go]')).toBeNull();
    });

    test('the dialog previews by itself at open: lands in, totals and the backup ticks show with no press, and a blocked field says it once', async () => {
        const plan = { ...BLOCKED, conversations: OWN.conversations, project: { ...BLOCKED.project, root_to: '/Users/me/dest' }, backups: { carried: true, restores: true, provider_enabled: true, conversations: [], folders: [
            { unit: 'reviewboard.boards', plugin: 'reviewboard', points: 2, files: 6, bytes: 100, already: 0, status: 'restore', reason: null }] } };
        const { fetcher, calls } = server({ [PLAN]: () => plan });
        const target = await open({ fetcher, originalRoot: BLOCKED.project.root_from });
        expect(calls[0]!.body).toMatchObject({ mode: 'same_paths' });
        expect(target.querySelector('[data-crt-import-counts]')!.textContent).not.toBe(t('cplug.crate.import.sum.unread'));
        expect(target.querySelector('[data-crt-import-backup-family]')).not.toBeNull();
        expect(target.querySelector('[data-crt-import-summary]')!.textContent).toContain('/Users/me/dest');
        expect(target.querySelectorAll('[data-crt-root-unusable]')).toHaveLength(1);
        expect(target.querySelectorAll('[data-crt-import-blocker="relocate_required"]')).toHaveLength(0);
        expect((target.querySelector('[data-crt-import-new-root]') as HTMLInputElement).value).toBe(BLOCKED.project.root_from);
    });

    test('typing in the field asks for a fresh preview once the typing stops (debounced), never changing a tick', async () => {
        const { fetcher, calls } = server({ [PLAN]: () => OWN });
        const target = await open({ fetcher, originalRoot: OWN.project.root_from });
        const field = target.querySelector('[data-crt-import-new-root]') as HTMLInputElement;
        for (const text of ['/Users/me/a', '/Users/me/ab']) {
            field.value = text;
            field.dispatchEvent(new Event('input', { bubbles: true }));
            await settle();
        }
        const asks = () => calls.filter((c) => c.path.endsWith('/imports/plan'));
        expect(asks()).toHaveLength(1);
        await new Promise((r) => setTimeout(r, 600));
        await settle();
        expect(asks()).toHaveLength(2);
        expect(asks()[1]!.body).toMatchObject({ mode: 'relocate', new_root: '/Users/me/ab' });
    });

    test('the restore into field holds the crate\'s original folder the moment the dialog opens, and the open-time preview leaves it alone', async () => {
        const { fetcher, calls } = server({ [PLAN]: () => OWN });
        const target = await open({ fetcher, originalRoot: OWN.project.root_from });
        expect(target.querySelector('[data-crt-import-mode]')).toBeNull();
        expect((target.querySelector('[data-crt-import-new-root]') as HTMLInputElement).value).toBe(OWN.project.root_from);
        expect((target.querySelector('[data-crt-import-new-root]') as HTMLInputElement).value).toBe(OWN.project.root_from);
        expect(calls).toHaveLength(1);
        expect(calls[0]!.body).toMatchObject({ mode: 'same_paths' });
    });

    test('a project already here by uid says plainly the restore adds to it at its own folder, under the field (the field is not changed)', async () => {
        const followed = { ...OWN, project: { ...OWN.project, action: 'follow_uid', root_to: '/Users/me/carnivore-projects/Existing' } };
        const { fetcher } = server({ [PLAN]: () => followed });
        const target = await open({ fetcher, originalRoot: OWN.project.root_from });
        const note = target.querySelector('[data-crt-import-existing-folder]');
        expect(note!.textContent).toBe(t('cplug.crate.import.existing_folder', { folder: '/Users/me/carnivore-projects/Existing' }));
        expect(target.querySelector('[data-crt-import-summary]')!.textContent).toContain('/Users/me/carnivore-projects/Existing');
        expect((target.querySelector('[data-crt-import-new-root]') as HTMLInputElement).value).toBe(OWN.project.root_from);
    });

    test('no existing-folder note when the project lands in the folder the field names', async () => {
        const { fetcher } = server({ [PLAN]: () => ({ ...OWN, project: { ...OWN.project, action: 'attach', root_to: OWN.project.root_from } }) });
        const target = await open({ fetcher, originalRoot: OWN.project.root_from });
        expect(target.querySelector('[data-crt-import-existing-folder]')).toBeNull();
    });

    test('a conversation kept in the crate says why in the preview', async () => {
        const kept = { ...OWN, conversations: [{ id: 'orph', title: null, class: 'not_restored', resume: 'native', reason: 'copy_role' }] };
        const { fetcher } = server({ [PLAN]: () => kept });
        const target = await open({ fetcher, originalRoot: OWN.project.root_from });
        expect(target.querySelector('[data-crt-import-conversation-reason="copy_role"]')!.textContent).toBe(t('cplug.crate.import.skip.copy_role'));
    });

    test('a crate whose listing named no folder (an encrypted one) is filled once by the first plan that names it', async () => {
        const { fetcher } = server({ [PLAN]: () => OWN });
        const target = await open({ fetcher, originalRoot: null });
        expect((target.querySelector('[data-crt-import-new-root]') as HTMLInputElement).value).toBe(OWN.project.root_from);
    });

    test('a preview that says relocate_required never changes the field or any tick (Joe, 2026-10-19)', async () => {
        const plan = { ...BLOCKED, carries: { project_files: true, work_in_restored_copy: false, plugin_data: true } };
        const { fetcher, calls } = server({ [PLAN]: () => plan });
        const target = await open({ fetcher, originalRoot: BLOCKED.project.root_from });
        expect((target.querySelector('[data-crt-import-new-root]') as HTMLInputElement).value).toBe(BLOCKED.project.root_from);
        await click(target, '[data-crt-preview]');
        const field = target.querySelector('[data-crt-import-new-root]') as HTMLInputElement;
        expect(field.value).toBe(BLOCKED.project.root_from);
        expect(target.querySelector('[data-crt-root-unusable]')).not.toBeNull();
        await click(target, '[data-crt-import-plugin-data] button, [data-crt-import-plugin-data]');
        await click(target, '[data-crt-preview]');
        await click(target, '[data-crt-preview]');
        const asks = calls.filter((c) => c.path.endsWith('/imports/plan'));
        expect(asks.at(-1)!.body).toMatchObject({ mode: 'same_paths', include_project_files: true });
        expect(asks.at(-1)!.body).not.toHaveProperty('include_plugin_data');
        expect(asks.every((c) => c.body?.mode === 'same_paths' && !('new_root' in (c.body ?? {})))).toBe(true);
        expect(field.value).toBe(BLOCKED.project.root_from);
    });

    test('typing another folder sends relocate with that folder; the suggestion is a click, never automatic', async () => {
        const suggested = BLOCKED.project.suggested_root;
        const { fetcher, calls } = server({ [PLAN]: (call) => (call.body?.mode === 'relocate' ? OWN : BLOCKED) });
        const target = await open({ fetcher });
        expect(calls.filter((c) => c.path.endsWith('/imports/plan')).length).toBe(1);
        await click(target, '[data-crt-import-suggested]');
        const asks = calls.filter((c) => c.path.endsWith('/imports/plan'));
        expect(asks.map((c) => c.body?.mode)).toEqual(['same_paths', 'relocate']);
        expect(asks[1]!.body).toMatchObject({ mode: 'relocate', new_root: suggested });
        expect((target.querySelector('[data-crt-import-new-root]') as HTMLInputElement).value).toBe(suggested);
        expect(target.querySelector('[data-crt-go]')).not.toBeNull();
    });

    test('a failed preview (a 500, or an answer that is not a plan) shows the error and leaves preview pressable', async () => {
        let answer: () => unknown = () => { throw new ApiError('boom: server error', 500, null, null); };
        const { fetcher } = server({ [PLAN]: () => answer() });
        const target = await open({ fetcher });
        await click(target, '[data-crt-preview]');
        expect(target.querySelector('[data-crt-problem]')!.textContent).toContain('boom');
        expect((target.querySelector('[data-crt-preview]') as HTMLButtonElement).disabled).toBe(false);
        expect(target.querySelector('[data-crt-measuring]')).toBeNull();
        answer = () => null;
        await click(target, '[data-crt-preview]');
        expect(target.querySelector('[data-crt-problem]')!.textContent).toContain('import plan');
        expect((target.querySelector('[data-crt-preview]') as HTMLButtonElement).disabled).toBe(false);
        answer = () => OWN;
        await click(target, '[data-crt-preview]');
        expect(target.querySelector('[data-crt-problem]')).toBeNull();
        expect(target.querySelector('[data-crt-go]')).not.toBeNull();
    });

    test('the three ticks show only for what the crate carries, are on by default, and go out on preview and on restore', async () => {
        const carrying = { ...OWN, carries: { project_files: true, work_in_restored_copy: true, plugin_data: true }, project_folder: {
            path: '/p/app', create: true, files: 'into_project_folder', side: null } };
        const { fetcher, calls } = server({
            [PLAN]: () => carrying,
            'POST /cplugs/crate/imports': () => ({ job_id: 'job-3' }),
            'GET /cplugs/crate/jobs/job-3': () => ({ job_id: 'job-3', kind: 'import', state: 'done' }),
        });
        const target = await open({ fetcher });
        const asks = () => calls.filter((c) => c.path.endsWith('/imports/plan')).map((c) => c.body);
        expect(asks()[0]).toMatchObject({ include_project_files: true, include_plugin_data: true, keep_conversations: true, file_backups: true });
        expect(asks()[0]).not.toHaveProperty('work_in_restored_copy');
        expect(asks()).toHaveLength(2);
        expect(asks()[1]).toMatchObject({ include_project_files: true, work_in_restored_copy: true, include_plugin_data: true });
        for (const tick of ['project-files', 'work-in-copy', 'plugin-data']) {
            expect(target.querySelector(`[data-crt-import-${tick}]`), tick).not.toBeNull();
        }
        expect(target.textContent).toContain(t('cplug.crate.import.project_files_into', { folder: '/p/app' }));
        await click(target, '[data-crt-import-plugin-data] button, [data-crt-import-plugin-data]');
        expect(target.querySelector('[data-crt-import-plan]')).toBeNull();
        await new Promise((done) => setTimeout(done, 500));
        await settle();
        expect(asks().at(-1)).not.toHaveProperty('include_plugin_data');
        await click(target, '[data-crt-go]');
        const start = calls.find((c) => c.method === 'POST' && c.path.endsWith('/imports'))!;
        expect(start.body).toMatchObject({ include_project_files: true, work_in_restored_copy: true, fingerprint: OWN.fingerprint });
        expect(start.body).not.toHaveProperty('include_plugin_data');
    });

    test('clicking a tick never wipes the form: every tick stays, the preview is asked again by itself, and restore enables again', async () => {
        const full = { ...OWN, provenance: 'foreign', provenance_reason: 'claims_this_computer_not_proven',
            instructions: { memory_files: 2, plans: 1, held_back: true }, conversations: [{ id: 'c1', title: 'one', class: 'conflict', resume: 'native' }],
            carries: { project_files: true, work_in_restored_copy: true, plugin_data: true } };
        const { fetcher, calls } = server({ [PLAN]: () => full });
        const target = await open({ fetcher });
        await click(target, '[data-crt-preview]');
        const ticks = ['work-in-copy', 'project-files', 'plugin-data', 'instructions', 'made-here', 'skip-conflicts'];
        const present = () => ticks.filter((tick) => target.querySelector(`[data-crt-import-${tick}]`) !== null);
        expect(present()).toEqual(ticks);
        const asks = () => calls.filter((c) => c.path.endsWith('/imports/plan')).length;
        for (const tick of ticks) {
            const before = asks();
            await click(target, `[data-crt-import-${tick}] button, [data-crt-import-${tick}]`);
            expect(present(), `after ${tick}`).toEqual(ticks);
            expect((target.querySelector('[data-crt-go]') as HTMLButtonElement).disabled).toBe(true);
            await new Promise((done) => setTimeout(done, 500));
            await settle();
            expect(asks(), tick).toBe(before + 1);
            expect(present(), `after the new plan of ${tick}`).toEqual(ticks);
            expect((target.querySelector('[data-crt-go]') as HTMLButtonElement).disabled).toBe(false);
        }
    });

    test('project files already on disk are shown as here, with no folder beside', async () => {
        const here = { ...OWN, project_folder: { path: '/p/app', create: false, files: 'already_here', side: null },
            files: { ...(OWN as { files?: object }).files, count: 0, bytes: 0, side_folder: { path: '/p/app', matching: 133, differing: 0, placement: 'already_here' } } };
        const { fetcher } = server({ [PLAN]: () => here });
        const target = await open({ fetcher });
        await click(target, '[data-crt-preview]');
        expect(target.querySelector('[data-crt-import-project-files="already_here"]')!.textContent).toContain(t('cplug.crate.import.preview.files_here', { count: 133 }));
        expect(target.textContent).not.toContain('beside it');
    });

    test('the keep-conversations tick shows only when a restored file is older than claude\'s period, is on by default, and goes out as ticked', async () => {
        const guard = { period_days: 30, files_older: 3, oldest_days: 400, needs_guard: true, keep_days: 36500, refused: null };
        const old = { ...OWN, cleanup: guard, files: { ...(OWN as { files?: object }).files, restamp: true },
            conversations: [{ id: 'c1', title: 'one', class: 'write', resume: 'native' }] };
        const { fetcher, calls } = server({
            [PLAN]: (call) => (call.body?.keep_conversations === undefined ? { ...OWN, cleanup: { ...guard, needs_guard: false } } : old),
            'POST /cplugs/crate/imports': () => ({ job_id: 'job-4' }),
            'GET /cplugs/crate/jobs/job-4': () => ({ job_id: 'job-4', kind: 'import', state: 'done' }),
        });
        const target = await open({ fetcher });
        await click(target, '[data-crt-preview]');
        const asks = () => calls.filter((c) => c.path.endsWith('/imports/plan')).map((c) => c.body);
        expect(asks()[0]).toMatchObject({ keep_conversations: true, file_backups: true });
        expect(target.querySelector('[data-crt-import-keep-conversations]')).not.toBeNull();
        expect(target.textContent).toContain(t('cplug.crate.import.keep_conversations'));
        expect(target.querySelector('[data-crt-import-cleanup-warning]')!.textContent).toContain('400');
        expect(target.querySelector('[data-crt-import-restamp]')!.textContent).toContain(t('cplug.crate.import.preview.restamp'));
        await click(target, '[data-crt-import-keep-conversations] button, [data-crt-import-keep-conversations]');
        await new Promise((done) => setTimeout(done, 500));
        await settle();
        expect(asks().at(-1)).not.toHaveProperty('keep_conversations');
    });

    test('the preview lists the backup points per conversation, with the reason when they are not restored', async () => {
        const rows = [{ id: 'c1', points: 3, files: 9, bytes: 2048, already: 0, status: 'restore', reason: null },
            { id: 'c2', points: 2, files: 4, bytes: 10, already: 2, status: 'present', reason: null },
            { id: 'c3', points: 1, files: 2, bytes: 5, already: 0, status: 'not_restored', reason: 'backup_plugin_off' }];
        const { fetcher } = server({ [PLAN]: () => ({ ...OWN, backups: { carried: true, restores: true, conversations: rows } }) });
        const target = await open({ fetcher });
        await click(target, '[data-crt-preview]');
        expect(target.querySelector('[data-crt-import-backups]')).not.toBeNull();
        expect(target.querySelector('[data-crt-import-backup="c1"]')!.textContent).toContain(t('cplug.crate.import.preview.backups_points', { count: 3, files: 9, size: '2.0 kb' }));
        expect(target.querySelector('[data-crt-import-backup="c2"]')!.textContent).toContain(t('cplug.crate.import.preview.backups_present', { count: 2 }));
        expect(target.querySelector('[data-crt-import-backup="c3"]')!.textContent).toContain(t('cplug.crate.import.skip.backup_plugin_off'));
    });

    test('the file-backups tick shows only for a crate from elsewhere that carries backups, is on by default, and goes out as ticked', async () => {
        const rows = [{ id: 'c1', points: 3, files: 9, bytes: 2048, already: 0, status: 'restore', reason: null }];
        const backups = { carried: true, restores: true, conversations: rows };
        const { fetcher, calls } = server({ [PLAN]: () => ({ ...OWN, provenance: 'foreign', backups }) });
        const target = await open({ fetcher });
        await click(target, '[data-crt-preview]');
        const asks = () => calls.filter((c) => c.path.endsWith('/imports/plan')).map((c) => c.body);
        expect(asks()[0]).toMatchObject({ file_backups: true });
        expect(target.querySelector('[data-crt-import-file-backups]')).not.toBeNull();
        await click(target, '[data-crt-import-file-backups]');
        await new Promise((done) => setTimeout(done, 500));
        await settle();
        expect(asks().at(-1)).not.toHaveProperty('file_backups');
        const own = server({ [PLAN]: () => ({ ...OWN, backups }) });
        const t2 = await open({ fetcher: own.fetcher });
        await click(t2, '[data-crt-preview]');
        expect(t2.querySelector('[data-crt-import-file-backups]')).toBeNull();
    });

    test('a crate from elsewhere gets one tick per plugin folder family, on by default, greyed when not restorable, and sends the ticked units', async () => {
        const folders = [{ unit: 'reviewboard.boards', plugin: 'reviewboard', points: 2, files: 6, bytes: 100, already: 0, status: 'restore', reason: null },
            { unit: 'tasks.items', plugin: 'tasks', points: 1, files: 1, bytes: 10, already: 0, status: 'not_restored', reason: 'plugin_store_plugin_off' }];
        const backups = { carried: true, restores: true, provider_enabled: true, conversations: [], folders };
        const { fetcher, calls } = server({ [PLAN]: () => ({ ...OWN, provenance: 'foreign', backups }) });
        const target = await open({ fetcher });
        await click(target, '[data-crt-preview]');
        const asks = () => calls.filter((c) => c.path.endsWith('/imports/plan')).map((c) => c.body);
        const boards = target.querySelector('[data-crt-import-backup-family="reviewboard.boards"]') as HTMLInputElement;
        const locked = target.querySelector('[data-crt-import-backup-family="tasks.items"]') as HTMLInputElement;
        const words = (box: HTMLInputElement) => box.closest('label')!.textContent!;
        expect(boards.checked).toBe(true);
        expect(words(boards)).toContain('file the review boards backups in my vault');
        expect(words(boards)).not.toContain('reviewboard.boards');
        expect(locked.disabled).toBe(true);
        expect(words(locked)).toContain(t('cplug.crate.import.skip.plugin_store_plugin_off'));
        expect(target.querySelector('[data-crt-import-backup="reviewboard.boards"]')).not.toBeNull();
        expect(asks().at(-1)).toMatchObject({ file_backup_units: ['reviewboard.boards'] });
        await click(target, '[data-crt-import-backup-family="reviewboard.boards"]');
        await new Promise((done) => setTimeout(done, 500));
        await settle();
        expect(asks().at(-1)).not.toHaveProperty('file_backup_units');
        const own = server({ [PLAN]: () => ({ ...OWN, backups }) });
        const t2 = await open({ fetcher: own.fetcher });
        await click(t2, '[data-crt-preview]');
        expect(t2.querySelector('[data-crt-import-backup-family]')).toBeNull();
    });

    test('the file-backups tick is greyed with its reason when this computer has no enabled backup provider (the plan says so)', async () => {
        const rows = [{ id: 'c1', points: 3, files: 9, bytes: 2048, already: 0, status: 'not_restored', reason: 'backup_plugin_off' }];
        const { fetcher } = server({ [PLAN]: () => ({ ...OWN, provenance: 'foreign', backups: { carried: true, restores: false, provider_enabled: false, conversations: rows } }) });
        const target = await open({ fetcher });
        await click(target, '[data-crt-preview]');
        const tick = target.querySelector('[data-crt-import-file-backups]') as HTMLInputElement;
        expect(tick.disabled).toBe(true);
        expect(tick.checked).toBe(false);
        expect(tick.closest('label')!.textContent).toContain(t('cplug.crate.import.file_backups_off'));
        const ready = server({ [PLAN]: () => ({ ...OWN, provenance: 'foreign', backups: { carried: true, restores: true, provider_enabled: true, conversations: rows } }) });
        const t2 = await open({ fetcher: ready.fetcher });
        await click(t2, '[data-crt-preview]');
        expect((t2.querySelector('[data-crt-import-file-backups]') as HTMLButtonElement).disabled).toBe(false);
    });

    test('a crate that carries nothing extra shows no tick, and one that is not own shows no work-in-copy tick', async () => {
        const { fetcher } = server({ [PLAN]: () => ({ ...OWN, carries: { project_files: true, work_in_restored_copy: false, plugin_data: false } }) });
        const target = await open({ fetcher });
        await click(target, '[data-crt-preview]');
        expect(target.querySelector('[data-crt-import-project-files]')).not.toBeNull();
        expect(target.querySelector('[data-crt-import-work-in-copy]')).toBeNull();
        expect(target.querySelector('[data-crt-import-plugin-data]')).toBeNull();
    });

    test('restore quotes the fingerprint of the plan that was shown, then follows the job', async () => {
        let closed: unknown = 'open';
        const { fetcher, calls } = server({
            [PLAN]: () => OWN,
            'POST /cplugs/crate/imports': () => ({ job_id: 'job-9' }),
            'GET /cplugs/crate/jobs/job-9': () => ({ job_id: 'job-9', kind: 'import', state: 'done' }),
        });
        const target = await open({ fetcher, close: (v: unknown) => (closed = v) });
        await click(target, '[data-crt-preview]');
        await click(target, '[data-crt-go]');
        const start = calls.find((c) => c.method === 'POST' && c.path.endsWith('/imports'))!;
        expect(start.body).toEqual({ source: { bundle_id: 'crate-1' }, mode: 'same_paths', include_project_files: true, include_plugin_data: true, keep_conversations: true, file_backups: true, fingerprint: OWN.fingerprint });
        expect(target.querySelector('[data-crt-done]')).not.toBeNull();
        await click(target, '[data-crt-close]');
        expect(closed).toBe('job-9');
    });

    test('a changed choice drops the plan', async () => {
        const { fetcher } = server({ [PLAN]: () => OWN });
        const target = await open({ fetcher });
        await click(target, '[data-crt-preview]');
        expect(target.querySelector('[data-crt-import-plan]')).not.toBeNull();
        const field = target.querySelector('[data-crt-import-new-root]') as HTMLInputElement;
        field.value = '/Users/me/elsewhere';
        field.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect(target.querySelector('[data-crt-import-plan]')).toBeNull();
        expect((target.querySelector('[data-crt-go]') as HTMLButtonElement).disabled).toBe(true);
    });

    test('a changed world shows the fresh plan in place of the old one and says so', async () => {
        const { fetcher } = server({
            [PLAN]: () => OWN,
            'POST /cplugs/crate/imports': () => { throw new ApiError('refused', 409, null, { detail: { code: 'plan_changed', detail: BLOCKED } }); },
        });
        const target = await open({ fetcher });
        await click(target, '[data-crt-preview]');
        await click(target, '[data-crt-go]');
        expect(target.querySelector('[data-crt-note]')!.textContent).toBe(t('cplug.crate.import.plan_changed'));
        expect(target.querySelector('[data-crt-import-plan="blocked"]')).not.toBeNull();
        expect(target.querySelector('[data-crt-root-unusable]')).not.toBeNull();
        expect(target.querySelector('[data-crt-go]')).toBeNull();
    });

    test('an encrypted crate asks for its key only after the server says it needs one, and sends it with the preview', async () => {
        let asked = 0;
        const { fetcher, calls } = server({
            [PLAN]: () => {
                asked += 1;
                if (asked === 1) throw new ApiError('refused', 409, null, { detail: { code: 'needs_identity', detail: 'encrypted' } });
                return OWN;
            },
        });
        const target = await open({ fetcher });
        expect(target.querySelector('[data-crt-problem]')).toBeNull();
        const key = target.querySelector<HTMLInputElement>('[data-crt-import-key]')!;
        expect(key.type).toBe('password');
        key.value = 'AGE-SECRET-KEY-TEST';
        key.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        await click(target, '[data-crt-preview]');
        expect(calls[1]!.body).toMatchObject({ identity: 'AGE-SECRET-KEY-TEST' });
        expect(JSON.stringify(calls[0]!.body)).not.toContain('identity');
    });

    test('only the ticks that mean something for the plan show', async () => {
        const claims = { ...BLOCKED, project: { ...BLOCKED.project, suggested_root: null }, provenance_reason: 'claims_this_computer_not_proven', instructions: { memory_files: 2, plans: 1, held_back: true },
            conversations: [{ id: 'c1', title: 'one', class: 'conflict', resume: 'native' }] };
        const { fetcher, calls } = server({ [PLAN]: () => claims });
        const target = await open({ fetcher });
        expect(target.querySelector('[data-crt-import-made-here]')).not.toBeNull();
        expect(target.querySelector('[data-crt-import-instructions]')).not.toBeNull();
        expect(target.querySelector('[data-crt-import-skip-conflicts]')).not.toBeNull();
        expect(target.querySelector('[data-crt-import-held-back]')).not.toBeNull();
        expect(calls).toHaveLength(1);
    });
});

describe('import wire', () => {
    test('parses a plan without inventing numbers and builds the body the route takes', () => {
        const parsed = parseImportPlan({ ok: false, fingerprint: '', blockers: [{ code: 'busy', detail: '' }] });
        expect(parsed.ok).toBe(false);
        expect(parsed.fingerprint).toBeNull();
        expect(parsed.files).toBeNull();
        expect(parsed.conversations).toEqual([]);
        expect(importBody({ source: { folder: 'primary', name: 'a.crate' }, mode: 'relocate', newRoot: '/p/x', madeHere: true }))
            .toEqual({ source: { folder: 'primary', name: 'a.crate' }, mode: 'relocate', new_root: '/p/x', made_here: true });
        expect(() => parseImportPlan(null)).toThrow();
    });
});

describe('import look', () => {
    test('names no literal color in the dialog, the preview or the shared stylesheet', () => {
        const color = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/;
        for (const file of ['ImportDialog.svelte', 'ImportPreview.svelte', 'crate-dialog.css']) {
            const source = readFileSync(resolve(process.cwd(), 'src/cplugs/crate', file), 'utf8').replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '');
            expect(source, file).not.toMatch(color);
        }
    });
});
