/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { resourcePush } from '../sdk';
import { setLocale, t } from '../../lib/i18n/index.svelte';
import type { Fetcher } from './crate-api';
import CratePanel from './CratePanel.svelte';
import ExportDialog from './ExportDialog.svelte';
import JobProgress from './JobProgress.svelte';

setLocale('en');

interface Call {
    path: string;
    method: string;
    body: Record<string, unknown> | null;
}

type Route = (call: Call) => unknown;

function server(routes: Record<string, Route>): { fetcher: Fetcher; calls: Call[] } {
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

const SUMMARY = {
    folders: { primary: { path: '/state/crates', state: 'ok', reason: null, free_bytes: 5 * 1024 ** 3 }, second: null },
    encrypt_default: false, recipients: [], running_job: null, bundles: 1,
};
const BUNDLE = {
    bundle_id: 'crate-20261017T000000Z-project-1a2b3c4d', scope: 'project', label: 'before the move', created_at: '2026-10-17T00:00:00Z',
    verified_at: null, conversations: 3, locations: [{ where: '/state/crates/crate-x.crate', verified_at: null, state: 'present' }],
};
const PLAN_OK = { ok: true, fingerprint: 'f'.repeat(64), conversations: [{ id: 'a' }], files: 4, estimate_bytes: 4096,
    excluded_count: 0, blockers: [], warnings: [], folder: '/state/crates' };

async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) {
        await Promise.resolve();
        flushSync();
    }
}

const mounted: Array<Record<string, unknown>> = [];

async function open<P extends Record<string, unknown>>(component: unknown, props: P): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(component as never, { target, props }) as Record<string, unknown>);
    await settle();
    return target;
}

async function click(target: HTMLElement, selector: string): Promise<void> {
    const el = target.querySelector<HTMLElement>(selector);
    expect(el, selector).not.toBeNull();
    el!.click();
    await settle();
}

afterEach(() => {
    for (const instance of mounted.splice(0)) unmount(instance);
    document.body.innerHTML = '';
    resourcePush().store.closed();
});

describe('settings block', () => {
    test('shows the folders and the crates, and verify starts a job it follows', async () => {
        let job = { job_id: 'job-1', kind: 'verify', state: 'running', phase: 'verifying', percent: null };
        const { fetcher, calls } = server({
            'GET /cplugs/crate/summary': () => SUMMARY,
            'GET /cplugs/crate/bundles': () => ({ bundles: [BUNDLE] }),
            'POST /cplugs/crate/bundles/': () => ({ job_id: 'job-1' }),
            'GET /cplugs/crate/jobs/job-1': () => job,
        });
        const target = await open(CratePanel, { fetcher });
        expect(target.querySelector('[data-crt-folder="primary"]')!.textContent).toContain('/state/crates');
        expect(target.querySelector('[data-crt-folder="primary"]')!.textContent).toContain('5.0 gb free');
        expect(target.querySelector('[data-crt-no-second]')).not.toBeNull();
        const row = target.querySelector(`[data-crt-bundle="${BUNDLE.bundle_id}"]`)!;
        expect(row.textContent).toContain('before the move');
        expect(row.textContent).toContain(t('cplug.crate.panel.never_verified'));
        expect(row.querySelector('[data-crt-copy]')).toBeNull();

        await click(target, `[data-crt-verify="${BUNDLE.bundle_id}"]`);
        expect(calls.find((c) => c.method === 'POST')).toEqual({
            path: `/cplugs/crate/bundles/${BUNDLE.bundle_id}/verify`, method: 'POST', body: { level: 'full' },
        });
        expect(target.querySelector('[data-crt-job="job-1"]')!.getAttribute('data-crt-state')).toBe('running');
        expect(target.querySelector<HTMLButtonElement>(`[data-crt-verify="${BUNDLE.bundle_id}"]`)!.disabled).toBe(true);

        job = { ...job, state: 'done' };
        const push = resourcePush().store;
        push.hello({ resource_topics: ['cplug.crate.jobs', 'exports'] });
        push.frame({ topics: ['cplug.crate.jobs:job-1'] });
        await settle();
        expect(target.querySelector('[data-crt-done]')!.textContent).toBe(t('cplug.crate.job.done.verify'));
        expect(target.querySelector<HTMLButtonElement>(`[data-crt-verify="${BUNDLE.bundle_id}"]`)!.disabled).toBe(false);
    });

    test('a second folder that is ready offers the copy; an unread count is said as unknown', async () => {
        const summary = { ...SUMMARY, bundles: null, folders: { ...SUMMARY.folders,
            second: { path: '/Volumes/Backup/crates', state: 'ok', reason: null, free_bytes: 1024 } } };
        const { fetcher } = server({
            'GET /cplugs/crate/summary': () => summary,
            'GET /cplugs/crate/bundles': () => ({ bundles: [BUNDLE] }),
        });
        const target = await open(CratePanel, { fetcher });
        expect(target.querySelector(`[data-crt-copy="${BUNDLE.bundle_id}"]`)).not.toBeNull();
        expect(target.querySelector('[data-crt-bundles] .oc-card__title')!.textContent).toContain(t('cplug.crate.panel.crates_unknown'));
    });
});

describe('job progress', () => {
    test('moves on a pushed frame for its own job, and not on another job or a timer', async () => {
        let job: Record<string, unknown> = { job_id: 'job-7', kind: 'export', state: 'running', phase: 'files',
            done_bytes: 1024, total_bytes: 4096, files_done: 1, files_total: 4, percent: 25 };
        const { fetcher, calls } = server({ 'GET /cplugs/crate/jobs/job-7': () => job });
        const push = resourcePush().store;
        push.hello({ resource_topics: ['cplug.crate.jobs'] });
        const target = await open(JobProgress, { jobId: 'job-7', fetcher });
        expect(target.querySelector('[data-crt-phase]')!.textContent).toBe(t('cplug.crate.job.phase.files'));
        expect(target.querySelector('[data-crt-counts]')!.textContent).toContain('1.0 kb of 4.0 kb');
        expect(target.querySelector('.oc-gauge')).not.toBeNull();
        const reads = calls.length;

        push.frame({ topics: ['cplug.crate.jobs:job-8'] });
        await settle();
        expect(calls.length).toBe(reads);

        job = { ...job, state: 'failed', error: { code: 'source_changed', detail: 'a.jsonl changed' } };
        push.frame({ topics: ['cplug.crate.jobs:job-7'] });
        await settle();
        expect(calls.length).toBe(reads + 1);
        expect(target.querySelector('[data-crt-failed]')!.textContent!.trim()).toBe(t('cplug.crate.error.source_changed'));
        expect(target.querySelector('[data-crt-cancel]')).toBeNull();
    });
});

describe('export dialog', () => {
    test('a blocked plan shows each blocker and offers no export', async () => {
        const blocked = { ...PLAN_OK, ok: false, blockers: [{ code: 'session_live', detail: 'session a is running' }] };
        const { fetcher, calls } = server({ 'GET /cplugs/crate/summary': () => SUMMARY, 'POST /cplugs/crate/plan': () => blocked });
        const target = await open(ExportDialog, { scope: 'project', target: '18', subject: 'this project', close: () => {}, fetcher });
        await click(target, '[data-crt-preview]');
        expect(calls.find((c) => c.path.endsWith('/plan'))!.body).toEqual({
            scope: 'project', target: '18', variant: 'own', encrypt: false, label: null,
        });
        expect(target.querySelector('[data-crt-blocker="session_live"]')!.textContent).toBe(t('cplug.crate.error.session_live'));
        expect(target.textContent).toContain('session a is running');
        expect(target.querySelector('[data-crt-go]')).toBeNull();
    });

    test('shows a measuring row with ticking seconds while the preview is pending, and clears it after', async () => {
        vi.useFakeTimers();
        try {
            let release: (value: unknown) => void = () => {};
            const pending = new Promise((resolve) => { release = resolve; });
            const { fetcher } = server({ 'GET /cplugs/crate/summary': () => SUMMARY, 'POST /cplugs/crate/plan': () => pending });
            const target = await open(ExportDialog, { scope: 'project', target: '18', subject: 'p', close: () => {}, fetcher });
            await click(target, '[data-crt-project-files]');
            expect(target.querySelector('[data-crt-measuring]')).toBeNull();
            await click(target, '[data-crt-preview]');
            expect(target.querySelector('[data-crt-measuring]')!.textContent).toContain(t('cplug.crate.export.measuring_files'));
            expect(target.querySelector('[data-crt-preview]')!.textContent).toBe(t('cplug.crate.export.previewing'));
            vi.advanceTimersByTime(3000);
            await settle();
            expect(target.querySelector('[data-crt-elapsed]')!.textContent).toBe('3 s');
            release(PLAN_OK);
            await settle();
            expect(target.querySelector('[data-crt-measuring]')).toBeNull();
            expect(vi.getTimerCount()).toBe(0);
        } finally {
            vi.useRealTimers();
        }
    });

    test('exports the plan it showed; a changed choice drops the preview', async () => {
        let closed: unknown = 'open';
        const { fetcher, calls } = server({
            'GET /cplugs/crate/summary': () => SUMMARY,
            'POST /cplugs/crate/plan': () => PLAN_OK,
            'POST /cplugs/crate/exports': () => ({ job_id: 'job-5' }),
            'GET /cplugs/crate/jobs/job-5': () => ({ job_id: 'job-5', kind: 'export', state: 'done' }),
        });
        const target = await open(ExportDialog, { scope: 'project', target: '18', subject: 'this project', close: (v: unknown) => (closed = v), fetcher });
        await click(target, '[data-crt-preview]');
        expect(target.querySelector('[data-crt-plan-counts]')!.textContent).toContain('1 conversations, 4 files, about 4.0 kb');
        await click(target, '[data-crt-variant="share"]');
        expect(target.querySelector('[data-crt-plan]')).toBeNull();
        expect(target.querySelector('[data-crt-share-note]')).not.toBeNull();
        await click(target, '[data-crt-preview]');
        await click(target, '[data-crt-go]');
        expect(calls.find((c) => c.path.endsWith('/exports'))!.body).toEqual({
            scope: 'project', target: '18', variant: 'share', encrypt: false, label: null, fingerprint: 'f'.repeat(64),
        });
        expect(target.querySelector('[data-crt-done]')).not.toBeNull();
        await click(target, '[data-crt-close]');
        expect(closed).toBe('job-5');
    });

    test('including the project files rides the request, shows the walk, and a share has no such choice', async () => {
        const walked = { ...PLAN_OK, project_files: { files: 7, bytes: 2048, links: 1, skipped: [{ path: 'node_modules', bytes: 4096, files: 3 }],
            skipped_folders: 1, skipped_bytes: 4096, specials: ['pipe'], large: true, warn_bytes: 1073741824 } };
        const { fetcher, calls } = server({ 'GET /cplugs/crate/summary': () => SUMMARY, 'POST /cplugs/crate/plan': () => walked });
        const target = await open(ExportDialog, { scope: 'project', target: '18', subject: 'p', close: () => {}, fetcher });
        await click(target, '[data-crt-project-files]');
        await click(target, '[data-crt-preview]');
        expect(calls.find((c) => c.path.endsWith('/plan'))!.body).toMatchObject({ variant: 'own', include_project_files: true });
        expect(target.querySelector('[data-crt-project-counts]')!.textContent).toBe(t('cplug.crate.export.project_counts', { files: 7, size: '2.0 kb' }));
        expect(target.querySelector('[data-crt-project-skipped-folder]')!.textContent).toBe(t('cplug.crate.export.project_skipped_one', { path: 'node_modules', size: '4.0 kb' }));
        expect(target.querySelector('[data-crt-project-specials]')!.textContent).toContain('pipe');
        expect(target.querySelector('[data-crt-project-large]')!.textContent).toBe(t('cplug.crate.export.project_large', { size: '1.0 gb' }));
        await click(target, '[data-crt-variant="share"]');
        expect(target.querySelector('[data-crt-project-files]')).toBeNull();
        await click(target, '[data-crt-preview]');
        expect(calls.filter((c) => c.path.endsWith('/plan')).at(-1)!.body).not.toHaveProperty('include_project_files');
    });

    test('the include-backups tick is off by default, rides an own request only, and a share has no such choice', async () => {
        const { fetcher, calls } = server({ 'GET /cplugs/crate/summary': () => SUMMARY, 'POST /cplugs/crate/plan': () => PLAN_OK });
        const target = await open(ExportDialog, { scope: 'project', target: '18', subject: 'p', close: () => {}, fetcher });
        await click(target, '[data-crt-preview]');
        expect(calls.find((c) => c.path.endsWith('/plan'))!.body).not.toHaveProperty('include_backups');
        await click(target, '[data-crt-include-backups]');
        await click(target, '[data-crt-preview]');
        expect(calls.filter((c) => c.path.endsWith('/plan')).at(-1)!.body).toMatchObject({ variant: 'own', include_backups: true });
        await click(target, '[data-crt-variant="share"]');
        expect(target.querySelector('[data-crt-include-backups]')).toBeNull();
        await click(target, '[data-crt-preview]');
        expect(calls.filter((c) => c.path.endsWith('/plan')).at(-1)!.body).not.toHaveProperty('include_backups');
    });

    test('the export offers one backup tick per plugin folder family, off by default, greyed with a reason, and sends the ticked units', async () => {
        const folders = [{ unit: 'reviewboard.boards', plugin: 'reviewboard', plugin_name_key: '', state: 'ok' },
            { unit: 'tasks.items', plugin: 'tasks', plugin_name_key: '', state: 'switched_off' }];
        const { fetcher, calls } = server({ 'GET /cplugs/crate/summary': () => SUMMARY, 'POST /cplugs/crate/plan': () => PLAN_OK,
            'POST /cplugs/crate/backup-families': () => ({ conversations: { available: true }, folders }) });
        const target = await open(ExportDialog, { scope: 'project', target: '18', subject: 'p', close: () => {}, fetcher });
        const boards = target.querySelector('[data-crt-backup-folder="reviewboard.boards"]') as HTMLInputElement;
        const off = target.querySelector('[data-crt-backup-folder="tasks.items"]') as HTMLInputElement;
        expect(boards.disabled).toBe(false);
        expect(boards.checked).toBe(false);
        expect(off.disabled).toBe(true);
        expect(off.closest('label')!.textContent).toContain('switched off');
        await click(target, '[data-crt-preview]');
        expect(calls.find((c) => c.path.endsWith('/plan'))!.body).not.toHaveProperty('backup_units');
        await click(target, '[data-crt-backup-folder="reviewboard.boards"]');
        await click(target, '[data-crt-preview]');
        expect(calls.filter((c) => c.path.endsWith('/plan')).at(-1)!.body).toMatchObject({ backup_units: ['reviewboard.boards'] });
    });

    test('the include-backups tick is greyed with its reason when the server says no enabled plugin provides backup points', async () => {
        const off = { ...SUMMARY, backups_available: false };
        const { fetcher, calls } = server({ 'GET /cplugs/crate/summary': () => off, 'POST /cplugs/crate/plan': () => PLAN_OK });
        const target = await open(ExportDialog, { scope: 'project', target: '18', subject: 'p', close: () => {}, fetcher });
        const tick = target.querySelector('[data-crt-include-backups]') as HTMLInputElement;
        expect(tick.disabled).toBe(true);
        expect(tick.closest('label')!.textContent).toContain(t('cplug.crate.export.include_backups_off'));
        await click(target, '[data-crt-preview]');
        expect(calls.find((c) => c.path.endsWith('/plan'))!.body).not.toHaveProperty('include_backups');
        const on = server({ 'GET /cplugs/crate/summary': () => ({ ...SUMMARY, backups_available: true }), 'POST /cplugs/crate/plan': () => PLAN_OK });
        const live = await open(ExportDialog, { scope: 'project', target: '18', subject: 'p', close: () => {}, fetcher: on.fetcher });
        expect((live.querySelector('[data-crt-include-backups]') as HTMLInputElement).disabled).toBe(false);
    });

    test('a finished own crate that is not encrypted and had scan hits warns with the count; an encrypted one does not', async () => {
        for (const [result, expected] of [
            [{ variant: 'own', encrypted: false, findings: 3 }, true],
            [{ variant: 'own', encrypted: true, findings: 3 }, false],
            [{ variant: 'own', encrypted: false, findings: 0 }, false],
        ] as const) {
            const { fetcher } = server({
                'GET /cplugs/crate/summary': () => SUMMARY,
                'POST /cplugs/crate/plan': () => PLAN_OK,
                'POST /cplugs/crate/exports': () => ({ job_id: 'job-6' }),
                'GET /cplugs/crate/jobs/job-6': () => ({ job_id: 'job-6', kind: 'export', state: 'done', result }),
            });
            const target = await open(ExportDialog, { scope: 'session', target: 'u', subject: 's', close: () => {}, fetcher });
            await click(target, '[data-crt-preview]');
            await click(target, '[data-crt-go]');
            const line = target.querySelector('[data-crt-secrets-warning]');
            expect(line !== null).toBe(expected);
            if (line) expect(line.textContent).toBe(t('cplug.crate.export.secrets_warning', { count: 3 }));
        }
    });
});
