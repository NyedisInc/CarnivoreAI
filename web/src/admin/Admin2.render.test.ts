/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Moderation from './Moderation.svelte';
import Audit from './Audit.svelte';
import Queue from './Queue.svelte';
import { AdminApi, type Fetcher } from './admin.js';
import { auditActor, auditTarget } from './moderation.js';
import { createHost, createTokenStore, TOKEN_KEY } from './admin-host.svelte.js';
import { createCommunityHost } from './community-host.svelte.js';

interface Call { url: string; method: string; body: string }

let mounted: Array<Record<string, unknown>> = [];
afterEach(() => {
    for (const m of mounted) unmount(m);
    mounted = [];
    document.body.innerHTML = '';
});

function router(table: Record<string, unknown>): { fetcher: Fetcher; calls: Call[] } {
    const calls: Call[] = [];
    const fetcher: Fetcher = async (url, init) => {
        const method = init?.method || 'GET';
        calls.push({ url, method, body: init?.body || '' });
        const key = Object.keys(table).find((k) => `${method} ${url}`.includes(k));
        return { ok: true, status: 200, json: async () => (key ? table[key] : {}) };
    };
    return { fetcher, calls };
}

const settle = async () => { for (let i = 0; i < 8; i++) { await new Promise((r) => setTimeout(r, 0)); flushSync(); } };
const button = (text: string) =>
    [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === text) as HTMLButtonElement;

const HIDDEN = { item_id: 'a/b', comment_id: 'c1', status: 'hidden', body: 'rude', created_at: 1, author_handle: 'ann' };

describe('button colours', () => {
    test('confirm is primary, destructive is danger, loads and filters are neither', async () => {
        const { fetcher } = router({ '/moderation/queue': { comments: [{ ...HIDDEN, status: 'visible', queue: 'reported' }] } });
        const host = createCommunityHost({ api: new AdminApi(fetcher, () => 't') });
        mounted.push(mount(Moderation, { target: document.body, props: { host } }));
        await settle();
        const cls = (text: string) => button(text).getAttribute('data-btn') ?? '';
        expect(cls('hide')).toBe('danger');
        expect(cls('delete')).toBe('danger');
        expect(cls('restore')).toBe('secondary');
        expect(cls('load reviews')).toBe('secondary');
        host.askMode('hold_all');
        await settle();
        expect(cls('switch the mode')).toBe('confirm');
    });

    test('the audit load button is neutral', async () => {
        const { fetcher } = router({ '/moderation/audit': { entries: [], next: null } });
        const host = createCommunityHost({ api: new AdminApi(fetcher, () => 't') });
        mounted.push(mount(Audit, { target: document.body, props: { host } }));
        await settle();
        expect(button('show that day').getAttribute('data-btn')).toBe('secondary');
    });

    test('the page draws no button of its own: the look is the base Button', () => {
        const css = readFileSync('src/admin/admin.css', 'utf8');
        expect(css).not.toMatch(/\.admin-btn/);
        expect(css).toContain("@import '../lib/base/base.css'");
    });
});

describe('hidden comments', () => {
    test('the item tab lists a hidden comment and restore calls the restore route', async () => {
        const { fetcher, calls } = router({ '/moderation/comments': { comments: [HIDDEN], next: null } });
        const host = createCommunityHost({ api: new AdminApi(fetcher, () => 't') });
        mounted.push(mount(Moderation, { target: document.body, props: { host } }));
        await settle();
        button('comments of an item').click();
        await settle();
        host.setCommentItem('a/b');
        button('load comments').click();
        await settle();
        expect(calls.some((c) => c.url.includes('/moderation/comments?item_id=a%2Fb'))).toBe(true);
        expect(document.body.textContent).toContain('rude');
        button('restore').click();
        await settle();
        const sent = calls.find((c) => c.url.endsWith('/moderation/restore'));
        expect(sent?.method).toBe('POST');
        expect(JSON.parse(sent?.body || '{}')).toMatchObject({ item_id: 'a/b', comment_id: 'c1' });
    });
});

describe('the audit line', () => {
    test('reads time, actor, action, target, reason; a deleted actor says so', async () => {
        const entries = [
            { audit_id: '1', at: 1789000000, actor_id: 'cognito:x', actor_handle: 'ann', action: 'hide',
              target: { item_id: 'a/b', comment_id: 'c1' }, detail: { reason: 'spam' } },
            { audit_id: '2', at: 1789000060, actor_id: 'cognito:gone', actor_handle: null, actor_deleted: true,
              action: 'submission_file_read', target: { submission_id: 's1', path: 'theme.json' }, detail: {} },
        ];
        const { fetcher } = router({ '/moderation/audit': { entries, next: null } });
        const host = createCommunityHost({ api: new AdminApi(fetcher, () => 't') });
        mounted.push(mount(Audit, { target: document.body, props: { host } }));
        await settle();
        const rows = [...document.querySelectorAll('li')].map((li) =>
            [...li.querySelectorAll('span')].map((s) => s.textContent?.trim()));
        expect(rows[0]).toEqual(['2026-09-10 00:26', 'ann', 'hide', 'comment on a/b', 'reason: spam']);
        expect(rows[1]).toEqual(['2026-09-10 00:27', 'deleted account', 'read a submission file', 'file theme.json of submission s1']);
        expect(document.body.textContent).not.toContain('cognito:gone');
    });

    test('targets are phrases, and unknown shapes list sorted keys', () => {
        expect(auditTarget({ target: { item_id: 'a/b', review_ref: 'r9' } })).toBe('review r9 on a/b');
        expect(auditTarget({ target: { user_id: 'u', target_ignored: 1 }, target_handle: 'bo' } as never)).toBe('account bo');
        expect(auditTarget({ target: { user_id: 'u' }, target_deleted: true })).toBe('account deleted account');
        expect(auditTarget({ target: { zeta: 1, alpha: 2 } })).toBe('alpha 2 zeta 1');
        expect(auditActor({ actor_id: 'system' })).toBe('system');
    });
});

describe('reject', () => {
    test('the reason field opens beside the buttons and the typed reason is sent', async () => {
        const { fetcher, calls } = router({
            '/submissions?status=pending': { status: 'pending', count: 1, submissions: [{ submission_id: 'ab12', name: 'night', kind: 'skill' }] },
            '/reject': { ok: true },
            '/me': { user_id: 'u', login: 'a', provider: 'email', email: 'a@x.test', is_admin: true },
        });
        const api = new AdminApi(fetcher, () => 't');
        const host = createHost({ api, tokens: createTokenStore(window) });
        window.sessionStorage.setItem(TOKEN_KEY, 'tok');
        await host.adopt();
        await host.loadQueue('in_review');
        mounted.push(mount(Queue, { target: document.body, props: { host } }));
        await settle();
        button('reject').click();
        await settle();
        const input = document.querySelector('#reason-ab12') as HTMLInputElement;
        expect(input).not.toBeNull();
        input.value = 'not useful';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        (document.querySelector('button[data-btn="danger"]') as HTMLButtonElement).click();
        await settle();
        const sent = calls.find((c) => c.url.endsWith('/submissions/ab12/reject'));
        expect(sent?.method).toBe('POST');
        expect(JSON.parse(sent?.body || '{}')).toEqual({ reason: 'not useful' });
    });
});
