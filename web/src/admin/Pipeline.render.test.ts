/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Queue from './Queue.svelte';
import ReportView from './ReportView.svelte';
import { AdminApi, type Fetcher, type Me, type ReportAnswer, type SubmissionRow } from './admin.js';
import { createHost, createTokenStore } from './admin-host.svelte.js';
import { QUEUE_STAGES, QUEUE_STATUSES, queueStageOf } from './queue-stage.js';

const ADMIN: Me = {
    user_id: 'u1', login: 'a@example.test', provider: 'email', email: 'a@example.test', is_admin: true,
} as Me;
const SHA = 'a'.repeat(64);

const REPORT = {
    submission_id: 'aw1', gate_state: 'awaiting_approval', report_sha256: SHA, overridable: false,
    report: {
        outcome: 'passed_with_mentions', app_sha: 'b'.repeat(40), grade: 'b',
        gates: [
            { n: 7, id: 'secrets', verdict: 'advisory', code: 'secret_shaped',
              findings: [{ code: 'secret_found', detector: 'aws_key', path: 'src/a.py', line: 12 }] },
            { n: 10, id: 'ai_review', verdict: 'advisory', code: 'review_warn',
              findings: [{ code: 'broad_shell', detector: 'review', path: 'hooks/run.sh' }] },
            { n: 11, id: 'clean_room', verdict: 'pass', code: 'ok', findings: [] },
        ],
        diff: { first_release: false, base_version: '1.0.0', added: 1, removed: 0, changed: 1, bytes_delta: 42,
                paths: [{ path: 'SKILL.md', change: 'changed' }, { path: 'extra.md', change: 'added' }] },
    },
};

const served: { report: ReportAnswer } = { report: REPORT };

type Call = { method: string; url: string; body: Record<string, unknown> | null };

function world(rowFor: (status: string) => SubmissionRow[]) {
    const calls: Call[] = [];
    const fetcher: Fetcher = async (url, init) => {
        const method = (init?.method as string) || 'GET';
        const body = init?.body ? JSON.parse(init.body as string) : null;
        calls.push({ method, url, body });
        const json = (status: number, payload: unknown) => ({
            ok: status < 400, status, json: async () => payload, headers: { get: () => 'application/json' },
        });
        if (url.endsWith('/me')) return json(200, ADMIN);
        if (url.includes('/report')) return json(200, served.report);
        if (method === 'POST') return json(200, { ok: true });
        if (url.includes('/submissions?')) {
            return json(200, { submissions: rowFor(new URL(url, 'http://x').searchParams.get('status') || '') });
        }
        return json(200, { files: [] });
    };
    return { fetcher, calls };
}

let mounted: Array<Record<string, unknown>> = [];
afterEach(() => {
    for (const m of mounted) unmount(m);
    mounted = [];
    document.body.innerHTML = '';
    vi.restoreAllMocks();
    served.report = REPORT;
});

const settle = async () => { for (let i = 0; i < 80; i++) { await Promise.resolve(); flushSync(); } };
const button = (text: string) =>
    [...document.querySelectorAll('button')].find((b) => b.textContent?.includes(text)) as HTMLButtonElement | undefined;

function showReport(report: ReportAnswer['report']): void {
    mounted.push(mount(ReportView, { target: document.body, props: { answer: { ...REPORT, report } } }));
    flushSync();
}

describe('stored ai review and code inventory', () => {
    test('shows complete coverage, model findings and all-code totals while escaping submitted text', () => {
        showReport({
            code_inventory: { file_count: 101, total_bytes: 9381, files: [{ path: 'src/<script>.py', bytes: 42 }], truncated: true },
            review: { status: 'reviewed', verdict: 'flagged', summary: '<img src=x onerror=alert(1)>',
                model: 'review-model', reviewed_at: '2026-10-27T12:00:00Z',
                coverage: { text_files: 2, total_chars: 900, reviewed_chars: 900, omitted_files: 0,
                    truncated_files: 0, binary_files: 0, complete: true },
                warnings: [{ kind: 'shell_access', detail: '<script>alert(1)</script>', file: 'src/run.py', line: 9 }] },
        });
        const text = document.body.textContent || '';
        expect(text).toContain('101 code files, 9,381 bytes total');
        expect(text).toContain('src/<script>.py  42 bytes');
        expect(text).toContain('first 100 paths');
        expect(text).toContain('complete scan: 900 of 900');
        expect(text).toContain('reviewed by review-model at 2026-10-27T12:00:00Z');
        expect(text).toContain('shell_access  src/run.py:9  <script>alert(1)</script>');
        expect(document.querySelector('script, img')).toBeNull();
    });

    test('names limited coverage and missing reviews without implying a clean scan', () => {
        showReport({ review: { status: 'reviewed', verdict: 'flagged', summary: 'partial read',
            model: 'review-model', reviewed_at: '2026-10-27T12:00:00Z',
            coverage: { text_files: 3, total_chars: 2000, reviewed_chars: 600, omitted_files: 1,
                truncated_files: 1, binary_files: 1, complete: false }, warnings: [] } });
        expect(document.body.textContent).toContain('limited scan: 600 of 2,000');
        expect(document.body.textContent).toContain('1 omitted, 1 truncated, 1 binary');
        unmount(mounted.pop()!);
        document.body.innerHTML = '';
        showReport({ gates: [{ n: 10, id: 'ai_review', verdict: 'undetermined', code: 'review_unavailable' }] });
        expect(document.body.textContent).toContain('scan status unknown');
        expect(document.body.textContent).toContain('review_unavailable');
        expect(document.body.textContent).not.toContain('no warnings recorded');
    });
});

async function paint(rowFor: (status: string) => SubmissionRow[]) {
    const w = world(rowFor);
    const store = createTokenStore({ sessionStorage: { getItem: () => 'tok', setItem: () => {}, removeItem: () => {} } });
    const host = createHost({ api: new AdminApi(w.fetcher, () => 'tok'), tokens: store });
    await host.adopt();
    mounted.push(mount(Queue, { target: document.body, props: { host } }));
    await settle();
    return { host, ...w };
}

const HOSTED_STATUSES = [...readFileSync('../hosted/catalog/api/submissions.py', 'utf8')
    .match(/ALL_STATUSES = \(([^)]*)\)/)![1]!.matchAll(/\b([A-Z_]+)\b/g)].map((m) => m[1]!.toLowerCase());

const stage = async (name: string) => {
    ([...document.querySelectorAll('[role=tab]')].find((b) => b.textContent?.trim().startsWith(name)) as HTMLElement).click();
    await settle();
};

describe('queue tabs', () => {
    test('the queue fetches every hosted status, which is every status the server has', () => {
        expect([...QUEUE_STATUSES].sort()).toEqual([...HOSTED_STATUSES].sort());
    });

    test('exactly four stage tabs, each with a count, opening on in review', async () => {
        await paint((status) => (status === 'pending' ? [{ submission_id: 'a', name: 'n', status, gate_state: 'received' }] : []));
        const tabs = [...document.querySelectorAll('[role=tab]')].map((b) => b.textContent?.replace(/\s+/g, ' ').trim());
        expect(tabs).toEqual(['submitted 1', 'in review 0', 'approved 0', 'rejected 0']);
        expect(document.querySelector('[role=tab][aria-selected=true]')?.textContent).toContain('in review');
    });

    test('every status lands in exactly one stage and its tab shows it with its own word', async () => {
        const gated = { pending: ['received', 'gating', 'awaiting_approval', 'stuck', ''] };
        const rows: SubmissionRow[] = [];
        for (const status of HOSTED_STATUSES) {
            for (const gate of status === 'pending' ? gated.pending : ['']) {
                rows.push({ submission_id: `${status}-${gate}`, name: `row-${status}-${gate}`, status, ...(gate ? { gate_state: gate } : {}) });
            }
        }
        await paint((status) => rows.filter((r) => r.status === status));
        const want: Record<string, string[]> = {
            submitted: ['pending-received'],
            in_review: ['pending-gating', 'pending-awaiting_approval', 'pending-stuck', 'pending-', 'publishing-'],
            approved: ['approved-', 'published-', 'superseded-'],
            rejected: ['gate_failed-', 'rejected-', 'revoked-', 'withdrawn-'],
        };
        expect(Object.values(want).flat().sort()).toEqual(rows.map((r) => r.submission_id).sort());
        for (const s of QUEUE_STAGES) {
            await stage(s.id === 'in_review' ? 'in review' : s.id);
            const shown = [...document.querySelectorAll('.admin-list__name')].map((n) => n.textContent?.trim().replace('row-', ''));
            for (const w of document.querySelectorAll('.admin-state')) expect(w.textContent).not.toMatch(/_|gate state/);
            expect(shown.sort(), s.id).toEqual(want[s.id]!.slice().sort());
            for (const r of rows.filter((r) => queueStageOf(r) === s.id)) expect(want[s.id]).toContain(r.submission_id);
        }
    });

    test('a published row shows its word and no gate state text, a note is not the alarm tone', async () => {
        await paint((status) => (status === 'published'
            ? [{ submission_id: 'p', name: 'live', status, gate_state: 'awaiting_approval', gate_outcome: 'passed_with_mentions' }]
            : []));
        await stage('approved');
        expect(document.querySelector('.admin-state')?.textContent).toBe('published');
        expect(document.body.textContent).not.toMatch(/gate state|awaiting_approval/);
        expect(document.querySelector('.admin-state--bad')).toBeNull();
    });

    test('rows are merged newest first', async () => {
        await paint((status) => (status === 'pending'
            ? [{ submission_id: 'old', name: 'old', status, created_at: '2026-01-01T00:00:00Z' }]
            : status === 'publishing' ? [{ submission_id: 'new', name: 'new', status, created_at: '2026-02-01T00:00:00Z' }] : []));
        expect([...document.querySelectorAll('.admin-list__name')].map((n) => n.textContent?.trim())).toEqual(['new', 'old']);
    });
});

describe('revoking a published release', () => {
    const LIVE: SubmissionRow = { submission_id: 'p1', name: 'shipped', status: 'published' };

    test('revoke stays disabled until a reason is typed, then one click posts the reason with no confirm dialog', async () => {
        const confirmSpy = vi.fn(() => false);
        vi.stubGlobal('confirm', confirmSpy);
        const { calls } = await paint(() => [LIVE]);
        await stage('approved');
        button('review files')!.click();
        await settle();
        expect(button('revoke this release')!.disabled).toBe(true);
        const input = document.querySelector('#revoke-p1') as HTMLInputElement;
        input.value = '   ';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect(button('revoke this release')!.disabled).toBe(true);
        input.value = 'ships a binary';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect(button('revoke this release')!.disabled).toBe(false);
        button('revoke this release')!.click();
        await settle();
        const posts = calls.filter((c) => c.url.endsWith('/admin/submissions/p1/revoke'));
        expect(posts.length).toBe(1);
        expect(posts[0]?.method).toBe('POST');
        expect(posts[0]?.body).toEqual({ reason: 'ships a binary' });
        expect(confirmSpy).not.toHaveBeenCalled();
        vi.unstubAllGlobals();
    });

    test('a pending row offers no revoke, and the rejected tab shows a revoked row with its word', async () => {
        await paint((status) => (status === 'revoked'
            ? [{ submission_id: 'r1', name: 'gone', status, revocation_state: 'pending' }]
            : [{ submission_id: 'q1', name: 'waiting', status: 'pending' }]));
        button('review files')!.click();
        await settle();
        expect(button('revoke this release')).toBeUndefined();
        await stage('rejected');
        expect(document.querySelector('.admin-state')?.textContent).toBe('revoked');
    });
});

describe('an awaiting_approval row with mentions', () => {
    const ROW: SubmissionRow = {
        submission_id: 'aw1', name: 'night', kind: 'skill', status: 'pending', gate_state: 'awaiting_approval',
        gate_outcome: 'passed_with_mentions', report_sha256: SHA,
    };

    test('shows the note, the report, the review warnings, the clean room and the diff', async () => {
        await paint(() => [ROW]);
        expect(document.body.textContent).toContain('passed with notes');
        expect(document.querySelector('.admin-state')?.textContent).toBe('waiting for approval');
        button('review files')!.click();
        await settle();
        const text = document.body.textContent || '';
        expect(text).toContain('src/a.py:12');
        expect(text).toContain('ai review');
        expect(text).toContain('hooks/run.sh');
        expect(text).toContain('clean room steps');
        expect(text).toContain('against 1.0.0: 1 added, 0 removed, 1 changed, 42 bytes');
        expect(text).toContain('changed  SKILL.md');
        expect(document.querySelector('.admin-actionbar')).not.toBeNull();
    });

    test('one click posts report_sha256 and asks for no confirmation', async () => {
        const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
        const { calls } = await paint(() => [ROW]);
        button('review files')!.click();
        await settle();
        ([...document.querySelectorAll('.admin-actionbar button')].find((b) => b.textContent?.trim() === 'approve') as HTMLButtonElement).click();
        await settle();
        const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/approve'));
        expect(post?.body).toEqual({ report_sha256: SHA });
        expect(confirm).not.toHaveBeenCalled();
    });
});

describe('a regate that changes the report digest', () => {
    test('the open detail refetches and approve quotes the new digest', async () => {
        const NEW = 'c'.repeat(64);
        const ROW: SubmissionRow = { submission_id: 'aw1', name: 'night', kind: 'skill', status: 'pending', gate_state: 'awaiting_approval', gate_outcome: 'passed_with_mentions', report_sha256: SHA };
        let row: SubmissionRow = { ...ROW };
        const { host, calls } = await paint(() => [row]);
        button('review files')!.click();
        await settle();
        served.report = { ...REPORT, report_sha256: NEW };
        row = { ...ROW, report_sha256: NEW };
        await host.regate('aw1');
        await settle();
        ([...document.querySelectorAll('.admin-actionbar button')].find((b) => b.textContent?.trim() === 'approve') as HTMLButtonElement).click();
        await settle();
        expect(calls.find((c) => c.url.endsWith('/approve'))?.body).toEqual({ report_sha256: NEW });
    });
});

describe('reject reason', () => {
    test('is sent trimmed', async () => {
        const { host, calls } = await paint(() => [{ submission_id: 'l1', name: 'old', status: 'pending' }]);
        host.beginReject('l1');
        host.setRejectReason('  ships a binary  ');
        await host.confirmReject();
        expect(calls.find((c) => c.url.endsWith('/reject'))?.body).toEqual({ reason: 'ships a binary' });
    });

    test('the legacy row input caps at 500 characters', async () => {
        const { host } = await paint(() => [{ submission_id: 'l1', name: 'old', status: 'pending' }]);
        host.beginReject('l1');
        await settle();
        expect((document.querySelector('#reason-l1') as HTMLInputElement).maxLength).toBe(500);
    });
});

describe('gate_failed rows', () => {
    const FAILED: SubmissionRow = {
        submission_id: 'f1', name: 'blocked', status: 'gate_failed', gate_state: 'failed',
        report_sha256: SHA, overridable: true,
    };

    test('override stays disabled until a reason is typed, then posts the reason and the digest', async () => {
        const { calls } = await paint(() => [FAILED]);
        await stage('rejected');
        button('review files')!.click();
        await settle();
        const go = button('override and approve')!;
        expect(go.disabled).toBe(true);
        const input = document.querySelector('#override-f1') as HTMLInputElement;
        input.value = 'false positive';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect(button('override and approve')!.disabled).toBe(false);
        button('override and approve')!.click();
        await settle();
        const post = calls.find((c) => c.url.endsWith('/override'));
        expect(post?.body).toEqual({ reason: 'false positive', report_sha256: SHA });
    });

    test('a failure that is not overridable offers no override, and regate runs the gates again', async () => {
        const { calls } = await paint(() => [{ ...FAILED, overridable: false }]);
        await stage('rejected');
        button('review files')!.click();
        await settle();
        expect(button('override and approve')).toBeUndefined();
        button('run the gates again')!.click();
        await settle();
        expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/f1/regate'))).toBe(true);
    });

    test('a reason over 500 characters is refused with nothing sent', async () => {
        const { host, calls } = await paint(() => [FAILED]);
        host.beginOverride('f1');
        host.setOverrideReason('x'.repeat(501));
        const before = calls.length;
        await host.confirmOverride();
        expect(calls.length).toBe(before);
        expect(host.refusal?.code).toBe('reason_too_long');
    });
});

describe('phone width', () => {
    test('the emitted stylesheet carries a max-width media rule and a sticky action bar', () => {
        const css = readFileSync('../hosted/catalog/admin/dist/admin.css', 'utf8');
        expect(css).toMatch(/@media\s*\(max-width:\s*640px\)/);
        expect(css).toMatch(/\.admin-actionbar\{[^}]*position:\s*sticky/);
    });
});
