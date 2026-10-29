/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { describe, expect, test, vi } from 'vitest';

import { AdminApi, whoText, type Fetcher } from './admin.js';
import { auditReason, auditTarget, auditTime } from './moderation.js';
import { createHost, type TokenStore } from './admin-host.svelte.js';
import { createCommunityHost } from './community-host.svelte.js';

interface Call { url: string; method: string; body: string }

function fake(status: number, body: unknown): { fetcher: Fetcher; calls: Call[] } {
    const calls: Call[] = [];
    const fetcher: Fetcher = async (url, init) => {
        calls.push({ url, method: init?.method || 'GET', body: init?.body || '' });
        return { ok: status < 300, status, json: async () => body };
    };
    return { fetcher, calls };
}

const ROW = { item_id: 'a/b', comment_id: 'c1', status: 'held', body: 'x', created_at: 1 };

describe('moderation host', () => {
    test('hide sends the reason', async () => {
        const { fetcher, calls } = fake(200, { comments: [], mode: 'instant' });
        const host = createCommunityHost({ api: new AdminApi(fetcher, () => 't') });
        host.setReason('  spam  ');
        await host.comment('hide', ROW);
        const hide = calls.find((c) => c.url.endsWith('/moderation/hide'));
        expect(hide?.method).toBe('POST');
        expect(JSON.parse(hide?.body || '{}')).toEqual({
            item_id: 'a/b', comment_id: 'c1', reason: 'spam',
        });
    });

    test('a 401 signs out', async () => {
        const { fetcher } = fake(401, { code: 'unauthorized' });
        const out = vi.fn();
        const host = createCommunityHost({
            api: new AdminApi(fetcher, () => 't'), onUnauthorized: out,
        });
        await host.load();
        expect(out).toHaveBeenCalledTimes(1);
    });

    test('mode flips only after the confirm', async () => {
        const { fetcher, calls } = fake(200, { mode: 'hold_all' });
        const host = createCommunityHost({ api: new AdminApi(fetcher, () => 't') });
        host.askMode('hold_all');
        expect(calls.length).toBe(0);
        await host.confirmMode();
        expect(calls[0]?.method).toBe('PUT');
        expect(host.mode).toBe('hold_all');
    });
});

describe('reports tab', () => {
    const GROUP = {
        kind: 'review', item_id: 'a/b', ref: 'rita', count: 2, reasons: { spam: 2 },
        first_at: 1, last_at: 2, reporters: ['ann', 'bo'],
    };

    test('loads item and review reports and lists them oldest first', async () => {
        const { fetcher, calls } = fake(200, { groups: [GROUP] });
        const host = createCommunityHost({ api: new AdminApi(fetcher, () => 't') });
        await host.loadReports();
        expect(calls.map((c) => c.url.split('/moderation')[1])).toEqual([
            '/reports?kind=item', '/reports?kind=review',
        ]);
        expect(host.reportsLoaded).toBe(true);
        expect(host.reports[0]?.reporters).toEqual(['ann', 'bo']);
    });

    test('dismiss sends the reviewer and the typed reason, then reloads', async () => {
        const { fetcher, calls } = fake(200, { groups: [] });
        const host = createCommunityHost({ api: new AdminApi(fetcher, () => 't') });
        host.setReason(' fine ');
        await host.dismissReport(GROUP);
        const sent = calls.find((c) => c.url.endsWith('/moderation/reports/dismiss'));
        expect(JSON.parse(sent?.body || '{}')).toEqual({
            kind: 'review', item_id: 'a/b', reviewer: 'rita', reason: 'fine',
        });
        expect(calls.some((c) => c.url.includes('/reports?kind=item'))).toBe(true);
    });

    test('opening the reviews loads that item', async () => {
        const { fetcher, calls } = fake(200, { reviews: [] });
        const host = createCommunityHost({ api: new AdminApi(fetcher, () => 't') });
        await host.openReviews('a/b');
        expect(calls[0]?.url).toContain('/moderation/reviews?item_id=a%2Fb');
    });
});

describe('audit paging', () => {
    test('load more sends the cursor and appends the next page', async () => {
        const pages = [
            { entries: [{ audit_id: 'a1' }], next: 'a1' },
            { entries: [{ audit_id: 'a2' }], next: null },
        ];
        const calls: string[] = [];
        const fetcher: Fetcher = async (url) => {
            calls.push(url);
            return { ok: true, status: 200, json: async () => pages.shift() };
        };
        const host = createCommunityHost({ api: new AdminApi(fetcher, () => 't') });
        await host.loadAudit();
        expect(host.auditMore).toBe(true);
        await host.loadMoreAudit();
        expect(calls[1]).toContain('&after=a1');
        expect(host.entries.map((e) => e.audit_id)).toEqual(['a1', 'a2']);
        expect(host.auditMore).toBe(false);
    });
});

describe('disable needs a reason', () => {
    const tokens: TokenStore = { read: () => 't', write() {}, clear() {} };
    const user = { user_id: 'u2' };

    test('the reason is sent, and an empty one sends nothing', async () => {
        const { fetcher, calls } = fake(200, { users: [], user_id: 'me', is_admin: true });
        const host = createHost({ api: new AdminApi(fetcher, () => 't'), tokens });
        await host.adopt();
        calls.length = 0;
        await host.toggleStanding(user);
        expect(calls.length).toBe(0);
        await host.confirmDisable();
        expect(calls.length).toBe(0);
        expect(host.refusal?.code).toBe('reason_required');
        host.setDisableReason('abuse');
        await host.confirmDisable();
        const sent = calls.find((c) => c.url.endsWith('/users/u2/disable'));
        expect(JSON.parse(sent?.body || '{}')).toEqual({ reason: 'abuse' });
    });
});

describe('hide and delete need a reason', () => {
    const row = { item_id: 'a/b', comment_id: 'c1' } as never;
    const review = { review_ref: 'ref1' } as never;

    test('a blank reason sends nothing and says so; restore and dismiss stay optional', async () => {
        const { fetcher, calls } = fake(200, { comments: [], reviews: [], mode: 'instant' });
        const host = createCommunityHost({ api: new AdminApi(fetcher, () => 't') });
        host.setReviewItem('a/b');
        for (const blank of ['', '   ']) {
            host.setReason(blank);
            calls.length = 0;
            await host.comment('hide', row);
            await host.comment('delete', row);
            await host.review('hide', review);
            await host.review('remove', review);
            expect(calls.length).toBe(0);
            expect(host.refusal?.code).toBe('reason_required');
        }
        host.setReason('');
        await host.comment('restore', row);
        await host.comment('dismiss', row);
        expect(calls.filter((c) => c.url.endsWith('/moderation/restore') || c.url.endsWith('/moderation/dismiss')).length).toBe(2);
        host.setReason('spam');
        await host.comment('hide', row);
        expect(JSON.parse(calls.find((c) => c.url.endsWith('/moderation/hide'))?.body || '{}').reason).toBe('spam');
    });
});

describe('the audit line and the signed in name', () => {
    test('a row reads as time, target and reason text; the name is handle, then email', () => {
        expect(auditTime(1789000000)).toBe('2026-09-10 00:26');
        expect(auditTarget({ target: { item_id: 'a/b', comment_id: 'c1' } })).toBe('comment on a/b');
        expect(auditReason({ reason: 'spam' })).toBe('spam');
        expect(auditReason(null)).toBe('');
        expect(whoText({ handle: '', email: 'a@b.c', login: '' } as never)).toBe('a@b.c');
        expect(whoText({ handle: 'ann', email: 'a@b.c', login: '' } as never)).toBe('ann');
    });
});

describe('no markup from server data', () => {
    test.each(['Moderation.svelte', 'ReportsTab.svelte', 'Audit.svelte', 'Users.svelte', 'community-host.svelte.ts', 'moderation.ts'])(
        '%s has no {@html} or innerHTML',
        (file) => {
            const source = readFileSync(new URL('./' + file, import.meta.url), 'utf8');
            expect(source).not.toMatch(/\{@html|innerHTML/);
        },
    );
});
