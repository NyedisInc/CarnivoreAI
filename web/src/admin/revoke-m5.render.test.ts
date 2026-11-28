/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Queue from './Queue.svelte';
import SubmissionDetail from './SubmissionDetail.svelte';
import { AdminApi, type Fetcher, type Me, type SubmissionRow } from './admin.js';
import { canRevokeStatus, type SubmissionRowM5 } from './admin-m5-types.js';
import { createHost, createTokenStore } from './admin-host.svelte.js';

const ADMIN: Me = {
    user_id: 'u1',
    login: 'admin@example.test',
    provider: 'email',
    email: 'admin@example.test',
    is_admin: true,
} as Me;

type Call = { method: string; url: string; body: Record<string, unknown> | null };

type PostHandler = (url: string, body: Record<string, unknown> | null) => { status: number; payload: unknown };

function createWorld(rowsByStatus: Record<string, SubmissionRowM5[]>, onPost?: PostHandler) {
    const calls: Call[] = [];
    const fetcher: Fetcher = async (url, init) => {
        const method = (init?.method as string) || 'GET';
        const body = init?.body ? JSON.parse(init.body as string) : null;
        calls.push({ method, url, body });
        const json = (status: number, payload: unknown) => ({
            ok: status < 400,
            status,
            json: async () => payload,
            headers: { get: () => 'application/json' },
        });
        if (url.endsWith('/me')) return json(200, ADMIN);
        if (method === 'POST') {
            if (onPost) {
                const res = onPost(url, body);
                return json(res.status, res.payload);
            }
            return json(200, { ok: true, revocation_state: 'revoked' });
        }
        if (url.includes('/submissions?')) {
            const status = new URL(url, 'http://x').searchParams.get('status') || '';
            return json(200, { submissions: rowsByStatus[status] || [] });
        }
        return json(200, {
            submission: {
                submission_id: 'sub-pub',
                status: 'publishing',
                files: [],
            },
            files: [],
        });
    };
    return { fetcher, calls };
}

async function setupHost(rowsByStatus: Record<string, SubmissionRowM5[]>, onPost?: PostHandler) {
    const { fetcher, calls } = createWorld(rowsByStatus, onPost);
    const store = createTokenStore({
        sessionStorage: {
            getItem: () => 'tok',
            setItem: () => {},
            removeItem: () => {},
        },
    });
    const host = createHost({ api: new AdminApi(fetcher, () => 'tok'), tokens: store });
    await host.adopt();
    return { host, calls };
}

let mounted: Array<Record<string, unknown>> = [];
afterEach(() => {
    for (const m of mounted) unmount(m);
    mounted = [];
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

const settle = async () => {
    for (let i = 0; i < 60; i++) {
        await Promise.resolve();
        flushSync();
    }
};

describe('M5.3 admin revoke & provenance metadata', () => {
    test('canRevokeStatus enables revoke for published, approved, and publishing only', () => {
        expect(canRevokeStatus('published')).toBe(true);
        expect(canRevokeStatus('approved')).toBe(true);
        expect(canRevokeStatus('publishing')).toBe(true);
        expect(canRevokeStatus('pending')).toBe(false);
        expect(canRevokeStatus('gate_failed')).toBe(false);
        expect(canRevokeStatus('rejected')).toBe(false);
        expect(canRevokeStatus('revoked')).toBe(false);
        expect(canRevokeStatus(undefined)).toBe(false);
    });

    test('Queue surfaces flagged/clean pills, git provenance, and 1-click inline quick revoke', async () => {
        const { host, calls } = await setupHost({
            approved: [
                {
                    submission_id: 'sub-flagged',
                    name: 'risky-plug',
                    kind: 'cplug',
                    status: 'approved',
                    gate_state: 'approved',
                    version: '1.2.0',
                    submitted_by_login: 'alice',
                    review_verdict: 'flagged',
                    flagged: true,
                    requires_warning_ack: true,
                    warning_reasons: ['shell command in hook'],
                    review_summary: 'Flags shell usage. Verify intent.',
                    git_repo: 'acme/risky-plug',
                    git_tag: 'v1.2.0',
                    git_commit_sha: '1234567890abcdef',
                } as SubmissionRowM5,
            ],
            published: [
                {
                    submission_id: 'sub-clean',
                    name: 'safe-plug',
                    kind: 'cplug',
                    status: 'published',
                    gate_state: 'approved',
                    version: '2.0.0',
                    submitted_by_login: 'bob',
                    review_verdict: 'clean',
                    flagged: false,
                } as SubmissionRowM5,
            ],
        });
        mounted.push(mount(Queue, { target: document.body, props: { host } }));
        await settle();
        host.selectQueueStage('approved');
        await settle();

        expect(document.body.textContent).toContain('flagged');
        expect(document.body.textContent).toContain('clean');
        expect(document.body.textContent).toContain('acme/risky-plug@v1.2.0');

        const confirmSpy = vi.spyOn(window, 'confirm');
        const quickBtn = [...document.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('quick revoke'),
        );
        expect(quickBtn).toBeDefined();
        quickBtn?.click();
        flushSync();

        const reasonInput = document.getElementById('quick-revoke-sub-flagged') as HTMLInputElement;
        expect(reasonInput).not.toBeNull();
        reasonInput.value = 'malicious upstream release';
        reasonInput.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();

        const revokeNowBtn = [...document.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('revoke now'),
        );
        expect(revokeNowBtn?.disabled).toBe(false);
        revokeNowBtn?.click();
        await settle();

        expect(confirmSpy).not.toHaveBeenCalled();
        const post = calls.find((c) => c.method === 'POST' && c.url.includes('/admin/submissions/sub-flagged/revoke'));
        expect(post?.body).toEqual({ reason: 'malicious upstream release' });
    });

    test('SubmissionDetail shows M5 AI verdict, warning reasons, commit SHA, and revoke bar for publishing status', async () => {
        const row: SubmissionRowM5 = {
            submission_id: 'sub-pub',
            name: 'publishing-plug',
            kind: 'cplug',
            status: 'publishing',
            gate_state: 'approved',
            version: '1.0.1',
            review_verdict: 'flagged',
            flagged: true,
            requires_warning_ack: true,
            warning_reasons: ['requests secrets'],
            review_summary: 'Reads API token from keychain. Discloses host endpoint.',
            git_repo: 'acme/pub-plug',
            git_tag: 'v1.0.1',
            git_commit_sha: 'deadbeefcafebabe1234',
        } as SubmissionRowM5;
        const { host } = await setupHost({});
        mounted.push(mount(SubmissionDetail, { target: document.body, props: { host, row: row as SubmissionRow } }));
        await settle();

        expect(document.body.textContent).toContain('Reads API token from keychain.');
        expect(document.body.textContent).toContain('requests secrets');
        expect(document.body.textContent).toContain('acme/pub-plug@v1.0.1');
        expect(document.body.textContent).toContain('deadbeefcafebabe1234');
        expect(document.getElementById('revoke-sub-pub')).not.toBeNull();
    });

    test('Queue inline quick-revoke stays open with typed reason on HTTP 503/409 failure and clears on retry 200', async () => {
        let attempts = 0;
        const { host, calls } = await setupHost(
            {
                approved: [
                    {
                        submission_id: 'sub-flagged',
                        name: 'risky-plug',
                        kind: 'cplug',
                        status: 'approved',
                        gate_state: 'approved',
                        version: '1.2.0',
                        submitted_by_login: 'alice',
                        review_verdict: 'flagged',
                        flagged: true,
                        requires_warning_ack: true,
                    } as SubmissionRowM5,
                ],
            },
            (url) => {
                if (url.includes('/admin/submissions/sub-flagged/revoke')) {
                    attempts += 1;
                    if (attempts === 1) {
                        return { status: 503, payload: { detail: { code: 'catalog_unavailable' } } };
                    }
                    return { status: 200, payload: { ok: true, revocation_state: 'revoked' } };
                }
                return { status: 200, payload: { ok: true } };
            },
        );

        mounted.push(mount(Queue, { target: document.body, props: { host } }));
        await settle();
        host.selectQueueStage('approved');
        await settle();

        const quickBtn = [...document.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('quick revoke'),
        );
        quickBtn?.click();
        flushSync();

        const reasonInput = document.getElementById('quick-revoke-sub-flagged') as HTMLInputElement;
        expect(reasonInput).not.toBeNull();
        reasonInput.value = 'malicious upstream release';
        reasonInput.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();

        const revokeNowBtn = [...document.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('revoke now'),
        );
        revokeNowBtn?.click();
        await settle();

        const preservedInput = document.getElementById('quick-revoke-sub-flagged') as HTMLInputElement | null;
        expect(preservedInput).not.toBeNull();
        expect(preservedInput?.value).toBe('malicious upstream release');
        expect(host.revoking).toBe('sub-flagged');
        expect(host.refusal).not.toBeNull();
        expect(host.refusal?.status).toBe(503);

        const retryBtn = [...document.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('revoke now'),
        );
        retryBtn?.click();
        await settle();

        expect(document.getElementById('quick-revoke-sub-flagged')).toBeNull();
        expect(host.revoking).toBe('');
        expect(host.revokeReason).toBe('');
        expect(host.refusal).toBeNull();
        const revokePosts = calls.filter(
            (c) => c.method === 'POST' && c.url.includes('/admin/submissions/sub-flagged/revoke'),
        );
        expect(revokePosts).toHaveLength(2);
    });
});
