/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import App from './App.svelte';
import { AdminApi, type Fetcher, type Me } from './admin.js';
import { QUEUE_STATUSES } from './queue-stage.js';
import { createHost, createTokenStore, TOKEN_KEY } from './admin-host.svelte.js';

const SESSION = 'COGNITO-SESSION-STRING';
const ACCESS = 'CATALOG-ACCESS-TOKEN';
const REFRESH = 'CATALOG-REFRESH-TOKEN';

/** An administrator, as `/v1/me` answers. */
const ADMIN: Me = {
    user_id: 'cognito:11111111-2222-3333-4444-555555555555',
    login: 'alex@example.test',
    provider: 'email',
    email: 'alex@example.test',
    is_admin: true,
};

const USERS = [
    {
        user_id: '88456975',
        provider: 'github',
        login: 'example-owner',
        email: '',
        seen_at: 1789000000,
        disabled: false,
        is_admin: false,
    },
    {
        user_id: 'cognito:99999999-2222-3333-4444-555555555555',
        provider: 'email',
        login: 'blocked@example.test',
        email: 'blocked@example.test',
        seen_at: 1788900000,
        disabled: true,
        is_admin: false,
    },
];

const PENDING = [
    {
        submission_id: 'ab12',
        status: 'pending',
        name: 'sme',
        handle: 'carnivore',
        version: '1.0.0',
        item_id: 'carnivore/sme',
        created_at: '2026-09-15T10:00:00Z',
        submitted_by_login: 'example-owner',
        submitted_by_id: '88456975',
    },
];

/** One recorded request. */
interface Call {
    url: string;
    method: string;
    headers: Record<string, string>;
}

/** A fake fetch answering by path, recording every call. */
function routed(answers: Record<string, { status: number; body: unknown }>): {
    fetcher: Fetcher;
    calls: Call[];
} {
    const calls: Call[] = [];
    const fetcher: Fetcher = async (url, init) => {
        const method = init?.method || 'GET';
        calls.push({ url, method, headers: init?.headers || {} });
        const answer = answers[method + ' ' + url];
        if (!answer) throw new Error('unscripted request: ' + method + ' ' + url);
        return {
            ok: answer.status >= 200 && answer.status < 300,
            status: answer.status,
            json: async () => answer.body,
        };
    };
    return { fetcher, calls };
}

const QUEUE_ANSWERS: Record<string, { status: number; body: unknown }> = Object.fromEntries(
    QUEUE_STATUSES.map((status) => [
        'GET https://api.carnivore.ai/v1/submissions?status=' + status,
        { status: 200, body: { status, count: 0, submissions: status === 'pending' ? PENDING : [] } },
    ]),
);

function paint(answers: Record<string, { status: number; body: unknown }>) {
    const { fetcher, calls } = routed(answers);
    const tokens = createTokenStore(globalThis);
    const host = createHost({
        api: new AdminApi(fetcher, () => tokens.read()),
        tokens,
    });
    const target = document.createElement('div');
    document.body.appendChild(target);
    const app = mount(App, { target, props: { host } });
    flushSync();
    return { app, target, host, calls, tokens };
}

function buttonText(target: HTMLElement): string[] {
    return Array.from(target.querySelectorAll('button')).map(
        (b) => (b.textContent || '').trim(),
    );
}

afterEach(() => {
    window.sessionStorage.clear();
    document.body.innerHTML = '';
});

describe('signing in, then the members table', () => {
    test('the session and the access token are nowhere in the document', async () => {
        const { app, target, host, tokens } = paint({
            'POST https://api.carnivore.ai/v1/auth/email/start': {
                status: 200,
                body: { session: SESSION, destination: 'a***@example.test' },
            },
            'POST https://api.carnivore.ai/v1/auth/email/verify': {
                status: 200,
                body: {
                    access_token: ACCESS,
                    refresh_token: REFRESH,
                    login: ADMIN.login,
                    provider: 'email',
                },
            },
            'GET https://api.carnivore.ai/v1/me': { status: 200, body: { ...ADMIN } },
            'GET https://api.carnivore.ai/v1/users': { status: 200, body: { users: USERS, cursor: '' } },
        });

        await host.start('alex@example.test');
        flushSync();
        expect(target.textContent).toContain('a***@example.test');

        await host.submitCode('12345678');
        host.setRoute('#/users');
        flushSync();
        await host.loadUsers(false);
        flushSync();

        expect(target.textContent).toContain('example-owner');
        expect(target.textContent).toContain(ADMIN.login);
        expect(target.textContent).toContain('2026-09-10');
        expect(target.textContent).toContain('2026-09-08');
        expect(target.textContent).not.toContain('1789000000');
        expect(target.textContent).not.toContain('1788900000');

        expect(target.innerHTML).not.toContain(SESSION);
        expect(target.innerHTML).not.toContain(ACCESS);
        expect(target.innerHTML).not.toContain(REFRESH);
        expect(document.body.innerHTML).not.toContain(ACCESS);

        expect(tokens.read()).toBe(ACCESS);
        expect(window.sessionStorage.getItem(TOKEN_KEY)).toBe(ACCESS);
        const stored: string[] = [];
        for (let i = 0; i < window.sessionStorage.length; i += 1) {
            const key = window.sessionStorage.key(i) || '';
            stored.push(key, window.sessionStorage.getItem(key) || '');
        }
        expect(stored.join('|')).not.toContain(REFRESH);
        expect(stored.join('|')).not.toContain(SESSION);
        expect(Object.keys(window.localStorage).filter((k) => k !== 'cloude.huddle.swarmView')).toEqual([]);

        unmount(app);
    });

    test('a disabled row is offered enable, and the caller gets no controls', async () => {
        const { app, target, host } = paint({
            'GET https://api.carnivore.ai/v1/me': { status: 200, body: { ...ADMIN } },
            'GET https://api.carnivore.ai/v1/users': {
                status: 200,
                body: {
                    users: [
                        ...USERS,
                        {
                            user_id: ADMIN.user_id,
                            provider: 'email',
                            login: ADMIN.login,
                            email: ADMIN.login,
                            seen_at: 1789000001,
                            disabled: false,
                            is_admin: true,
                        },
                    ],
                    cursor: '',
                },
            },
        });
        window.sessionStorage.setItem(TOKEN_KEY, ACCESS);
        await host.adopt();
        host.setRoute('#/users');
        flushSync();
        await host.loadUsers(false);
        flushSync();

        const text = buttonText(target);
        expect(text).toContain('disable');
        expect(text).toContain('enable');
        expect(target.textContent).toContain('this is you');
        const rows = Array.from(target.querySelectorAll('tbody tr'));
        const own = rows.find((r) => (r.textContent || '').includes(ADMIN.login));
        expect(own).toBeTruthy();
        expect(own?.querySelectorAll('button').length).toBe(0);

        unmount(app);
    });
});

describe('the queue', () => {
    test('approve posts to the submission with the bearer attached', async () => {
        const { app, target, host, calls } = paint({
            'GET https://api.carnivore.ai/v1/me': { status: 200, body: { ...ADMIN } },
            ...QUEUE_ANSWERS,
            'POST https://api.carnivore.ai/v1/submissions/ab12/approve': { status: 200, body: { ok: true } },
        });
        window.sessionStorage.setItem(TOKEN_KEY, ACCESS);
        await host.adopt();
        flushSync();
        await host.loadQueue('in_review');
        flushSync();
        expect(target.textContent).toContain('sme');
        expect(target.textContent).toContain('by example-owner');
        expect(target.textContent).not.toContain('by carnivore');

        await host.approve('ab12');
        const approve = calls.find((c) => c.url.endsWith('/approve'));
        expect(approve?.method).toBe('POST');
        expect(approve?.url).toBe('https://api.carnivore.ai/v1/submissions/ab12/approve');
        expect(approve?.headers.authorization).toBe('Bearer ' + ACCESS);
        for (const call of calls) expect(call.url.startsWith('https://api.carnivore.ai/v1/')).toBe(true);

        unmount(app);
    });

    test('a rejection with no reason is refused with nothing sent', async () => {
        const { app, target, host, calls } = paint({
            'GET https://api.carnivore.ai/v1/me': { status: 200, body: { ...ADMIN } },
            ...QUEUE_ANSWERS,
        });
        window.sessionStorage.setItem(TOKEN_KEY, ACCESS);
        await host.adopt();
        await host.loadQueue('in_review');
        flushSync();

        host.beginReject('ab12');
        flushSync();
        expect(target.textContent).toContain('why it was rejected');

        const before = calls.length;
        await host.confirmReject();
        flushSync();
        expect(calls).toHaveLength(before);
        expect(target.textContent).toContain('a rejection needs a reason');

        unmount(app);
    });
});

describe('somebody who is not an administrator', () => {
    test('is told so, and the page asks the server for nothing else', async () => {
        const { app, target, host, calls } = paint({
            'GET https://api.carnivore.ai/v1/me': {
                status: 200,
                body: { ...ADMIN, login: 'someone@example.test', email: 'someone@example.test', is_admin: false },
            },
        });
        window.sessionStorage.setItem(TOKEN_KEY, ACCESS);
        await host.adopt();
        flushSync();

        expect(target.textContent).toContain('signed in as someone@example.test, not an admin');
        expect(target.querySelector('table')).toBe(null);
        expect(calls.map((c) => c.url)).toEqual([
            'https://api.carnivore.ai/v1/health',
            'https://api.carnivore.ai/v1/me',
        ]);

        unmount(app);
    });
});
