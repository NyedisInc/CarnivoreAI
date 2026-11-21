import { describe, expect, test } from 'vitest';

import { ApiError } from '../sdk';
import { setLocale, t } from '../../lib/i18n/index.svelte';
import {
    bytesText,
    changedPlan,
    codeSentence,
    errorCode,
    errorSentence,
    fetchBundles,
    jobFinished,
    parseBundle,
    parseJob,
    parsePlan,
    parseSummary,
    previewPlan,
    startExport,
    verifyBundle,
    type Fetcher,
} from './crate-api';

setLocale('en');

interface Call {
    path: string;
    method: string;
    body: unknown;
}

function fake(answer: unknown): { fetcher: Fetcher; calls: Call[] } {
    const calls: Call[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        calls.push({ path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null });
        return answer;
    }) as unknown as Fetcher;
    return { fetcher, calls };
}

function refused(status: number, code: string, detail: unknown): ApiError {
    return new ApiError('refused', status, null, { detail: { code, detail } });
}

describe('parsing', () => {
    test('an absent field is null, never invented', () => {
        const summary = parseSummary({ folders: { primary: { path: '/c' } } });
        expect(summary.primary).toEqual({ path: '/c', state: null, reason: null, freeBytes: null });
        expect(summary.second).toBeNull();
        expect(summary.bundles).toBeNull();
        expect(summary.encryptDefault).toBeNull();
        expect(summary.runningJob).toBeNull();
        expect(summary.recipients).toEqual([]);

        const job = parseJob({ job_id: 'job-1', state: 'running' })!;
        expect(job.percent).toBeNull();
        expect(job.totalBytes).toBeNull();
        expect(job.error).toBeNull();

        const bundle = parseBundle({ bundle_id: 'crate-x', locations: [{ where: '/c/x.crate' }, { state: 'present' }] })!;
        expect(bundle.verifiedAt).toBeNull();
        expect(bundle.conversations).toBeNull();
        expect(bundle.locations).toEqual([{ where: '/c/x.crate', verifiedAt: null, state: null }]);

        const plan = parsePlan({ ok: true });
        expect(plan.conversations).toBeNull();
        expect(plan.estimateBytes).toBeNull();
        expect(plan.fingerprint).toBeNull();
    });

    test('a view with no id is no view, and a summary that is not an object throws', () => {
        expect(parseJob({ state: 'done' })).toBeNull();
        expect(parseBundle({ scope: 'project' })).toBeNull();
        expect(() => parseSummary(null)).toThrow();
        expect(() => parsePlan('nope')).toThrow();
    });

    test('a full answer keeps every field it carries', () => {
        const job = parseJob({
            job_id: 'job-2', kind: 'export', state: 'failed', phase: 'files', done_bytes: 5, total_bytes: 10, files_done: 1,
            files_total: 2, percent: 50, result: null, error: { code: 'name_taken', detail: 'x exists' }, updated_at: 'now',
        })!;
        expect(job).toMatchObject({ kind: 'export', percent: 50, error: { code: 'name_taken', detail: 'x exists' } });
        expect(jobFinished(job)).toBe(true);
        expect(jobFinished(parseJob({ job_id: 'j', state: 'running' }))).toBe(false);
        const plan = parsePlan({
            ok: false, fingerprint: 'f'.repeat(64), conversations: [{ id: 'a' }, { id: 'b' }], files: 9, estimate_bytes: 2048,
            blockers: [{ code: 'session_live', detail: 'session a is running' }, { detail: 'no code' }], warnings: ['w', 3],
        });
        expect(plan.conversations).toBe(2);
        expect(plan.blockers).toEqual([{ code: 'session_live', detail: 'session a is running' }]);
        expect(plan.warnings).toEqual(['w']);
    });
});

describe('calls', () => {
    test('plan and export send the documented bodies; export adds the fingerprint', async () => {
        const req = { scope: 'project', target: '18', variant: 'own', encrypt: null, label: '' } as const;
        const planned = fake({ ok: true, fingerprint: 'a'.repeat(64) });
        await previewPlan(req, planned.fetcher);
        expect(planned.calls[0]).toEqual({
            path: '/cplugs/crate/plan', method: 'POST',
            body: { scope: 'project', target: '18', variant: 'own', encrypt: null, label: null },
        });
        const started = fake({ job_id: 'job-9' });
        expect(await startExport(req, 'a'.repeat(64), started.fetcher)).toBe('job-9');
        expect(started.calls[0]!.path).toBe('/cplugs/crate/exports');
        expect((started.calls[0]!.body as Record<string, unknown>).fingerprint).toBe('a'.repeat(64));
    });

    test('the project files option is sent only when on, and the plan parses the walk', async () => {
        const req = { scope: 'session', target: 'u', variant: 'own', encrypt: null, label: null, includeProjectFiles: true } as const;
        const planned = fake({ ok: true, project_files: { files: 2, bytes: 5, skipped: [{ path: 'dist', bytes: 9 }, { nope: 1 }],
            skipped_folders: 1, skipped_bytes: 9, specials: ['pipe'], large: false, warn_bytes: 100 } });
        const plan = await previewPlan(req, planned.fetcher);
        expect(planned.calls[0]!.body).toEqual({ scope: 'session', target: 'u', variant: 'own', encrypt: null, label: null, include_project_files: true });
        expect(plan.projectFiles).toEqual({ files: 2, bytes: 5, skipped: [{ path: 'dist', bytes: 9 }], skippedFolders: 1, skippedBytes: 9,
            specials: ['pipe'], large: false, warnBytes: 100 });
        expect((await previewPlan({ ...req, includeProjectFiles: false }, fake({ ok: true }).fetcher)).projectFiles).toBeNull();
    });

    test('a project listing asks the project filter; verify posts its level', async () => {
        const listed = fake({ bundles: [{ bundle_id: 'crate-1' }, { nope: true }] });
        const bundles = await fetchBundles(18, listed.fetcher);
        expect(listed.calls[0]!.path).toBe('/cplugs/crate/bundles?project=18');
        expect(bundles.map((b) => b.bundleId)).toEqual(['crate-1']);
        const all = fake({ bundles: [] });
        await fetchBundles(null, all.fetcher);
        expect(all.calls[0]!.path).toBe('/cplugs/crate/bundles');
        const verify = fake({ job_id: 'job-3' });
        expect(await verifyBundle('crate-1', 'full', verify.fetcher)).toBe('job-3');
        expect(verify.calls[0]).toEqual({ path: '/cplugs/crate/bundles/crate-1/verify', method: 'POST', body: { level: 'full' } });
    });

    test('a 202 that names no job id is an error, not a silent success', async () => {
        await expect(verifyBundle('crate-1', 'full', fake({}).fetcher)).rejects.toThrow();
    });
});

describe('errors', () => {
    test('a known code reads its catalog sentence; an unknown one the server words', () => {
        const busy = refused(409, 'job_busy', 'job job-1 is running');
        expect(errorCode(busy)).toBe('job_busy');
        expect(errorSentence(busy, t)).toBe(t('cplug.crate.error.job_busy'));
        expect(errorSentence(busy, t)).not.toBe('cplug.crate.error.job_busy');
        expect(codeSentence('a_code_from_2031', 'the server said why', t)).toBe('the server said why');
        expect(codeSentence('a_code_from_2031', null, t)).toBe('a_code_from_2031');
        expect(errorSentence(new Error('plain'), t)).toBe('plain');
    });

    test('a plan_changed refusal carries the fresh plan', () => {
        const fresh = changedPlan(refused(409, 'plan_changed', { ok: true, fingerprint: 'b'.repeat(64) }));
        expect(fresh?.fingerprint).toBe('b'.repeat(64));
        expect(changedPlan(refused(409, 'job_busy', 'x'))).toBeNull();
    });

    test('every code the server documents has a sentence', () => {
        const codes = [
            'inventory_blocked', 'session_live', 'session_remote', 'no_crate_policy', 'source_forbidden', 'source_dataless',
            'conversation_missing', 'share_air_gapped', 'folder_unavailable', 'no_space', 'no_recipients', 'rows_unreadable',
            'vault_unreachable', 'vault_incomplete', 'file_not_traced', 'entry_unreadable', 'plan_changed', 'blocked', 'job_busy',
            'needs_identity', 'wrong_key', 'identity_invalid', 'project_not_found', 'name_taken', 'source_changed', 'verify_failed',
            'sha_mismatch', 'too_new', 'age_corrupt', 'job_crashed', 'interrupted',
        ];
        expect(codes.filter((code) => t(`cplug.crate.error.${code}`) === `cplug.crate.error.${code}`)).toEqual([]);
    });
});

test('bytes read in the largest whole unit; unknown reads empty', () => {
    expect(bytesText(1932735283)).toBe('1.8 gb');
    expect(bytesText(512)).toBe('512 b');
    expect(bytesText(null)).toBe('');
});
