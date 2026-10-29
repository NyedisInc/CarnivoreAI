import { describe, expect, test } from 'vitest';

import {
    AdminApi,
    ApiRefusal,
    adminAction,
    mayChangeStanding,
    refusalKey,
    refusalMessage,
    rejectionRefusal,
    looksLikeCode,
    seenAtText,
    standingAction,
    type Fetcher,
    type Me,
} from './admin.js';
import { createHost, createTokenStore, parseRoute, TOKEN_KEY } from './admin-host.svelte.js';
import { t, hasKey } from './text.js';
import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

interface Call {
    url: string;
    method: string;
    headers: Record<string, string>;
    body: string;
}

function fakeFetch(
    answers: Array<{ status: number; body: unknown } | Error>,
): { fetcher: Fetcher; calls: Call[] } {
    const calls: Call[] = [];
    let index = 0;
    const fetcher: Fetcher = async (url, init) => {
        calls.push({
            url,
            method: init?.method || 'GET',
            headers: init?.headers || {},
            body: init?.body || '',
        });
        const next = answers[index];
        index += 1;
        if (next === undefined) throw new Error('unscripted request: ' + url);
        if (next instanceof Error) throw next;
        return {
            ok: next.status >= 200 && next.status < 300,
            status: next.status,
            json: async () => next.body,
        };
    };
    return { fetcher, calls };
}

function memoryStore(): {
    store: ReturnType<typeof createTokenStore>;
    values: Record<string, string>;
} {
    const values: Record<string, string> = {};
    const fake = {
        sessionStorage: {
            getItem: (k: string) => (k in values ? values[k] : null),
            setItem: (k: string, v: string) => {
                values[k] = v;
            },
            removeItem: (k: string) => {
                delete values[k];
            },
        },
    };
    return { store: createTokenStore(fake), values };
}

const ADMIN: Me = {
    user_id: 'cognito:11111111-2222-3333-4444-555555555555',
    login: 'acme@example.test',
    provider: 'email',
    email: 'acme@example.test',
    is_admin: true,
};

describe('the refusal ladder', () => {
    test('a code only this page can provoke renders its own sentence', () => {
        expect(refusalKey('self_change')).toBe(ADMIN_KEYS.refusedSelfChange);
        expect(refusalKey('bootstrap_admin')).toBe(ADMIN_KEYS.refusedBootstrapAdmin);
    });

    test('a shared code renders the SHARED sentence, so the two surfaces agree', () => {
        expect(refusalKey('unauthorized')).toBe('skill.refused.unauthorized');
        expect(refusalKey('rate_limited')).toBe('skill.refused.rate_limited');
        expect(refusalKey('unavailable')).toBe('skill.refused.unavailable');
    });

    test('a code nothing has a sentence for is REPORTED, never swallowed', () => {
        expect(refusalKey('a_code_from_the_future')).toBe(ADMIN_KEYS.refusedUnrecognised);
        const said = refusalMessage(
            { status: 400, code: 'a_code_from_the_future', params: {} },
            t,
        );
        expect(said).toContain('a_code_from_the_future');
    });

    test('NEGATIVE CONTROL: the ladder can actually fall through', () => {
        expect(hasKey('admin.refused.self_change')).toBe(true);
        expect(hasKey('skill.refused.unauthorized')).toBe(true);
        expect(hasKey('admin.refused.a_code_from_the_future')).toBe(false);
        expect(hasKey('skill.refused.a_code_from_the_future')).toBe(false);
        expect(refusalMessage(null, t)).toBe('');
    });

    test('every key this page names exists in the one catalog', () => {
        for (const key of Object.values(ADMIN_KEYS)) {
            expect(hasKey(key), key).toBe(true);
            expect(t(key, { code: 'x', login: 'x', provider: 'x', destination: 'x', author: 'x', version: 'x' }), key).not.toBe(key);
        }
    });
});

describe('every code the catalog api can answer this page with', () => {
    const SERVER_CODES = [
        'bad_email', 'bad_code', 'bad_request', 'code_mismatch', 'code_expired',
        'email_refused', 'rate_limited', 'account_disabled', 'unavailable',
        'email_auth_not_configured', 'unauthorized', 'forbidden',
        'admin_not_configured', 'unknown_user', 'not_pending', 'not_found',
        'self_change', 'bootstrap_admin',
        'report_mismatch', 'not_overridable', 'gates_not_passed',
        'override_needs_reason', 'reason_too_long',
    ];

    test('has a sentence, on one rung of the ladder or the other', () => {
        for (const code of SERVER_CODES) {
            expect(refusalKey(code), code).not.toBe(ADMIN_KEYS.refusedUnrecognised);
            const said = refusalMessage({ status: 400, code, params: {} }, t);
            expect(said, code).not.toBe('');
            expect(said, code).not.toContain('admin.refused.');
            expect(said, code).not.toContain('skill.refused.');
        }
    });

    test('NEGATIVE CONTROL: a code the api cannot answer has none', () => {
        expect(refusalKey('not_a_code_any_route_raises'))
            .toBe(ADMIN_KEYS.refusedUnrecognised);
    });
});

describe('the rules that refuse before any request', () => {
    test('the caller cannot change their own standing', () => {
        expect(mayChangeStanding({ user_id: ADMIN.user_id }, ADMIN)).toBe(false);
        expect(mayChangeStanding({ user_id: '10000001' }, ADMIN)).toBe(true);
        expect(mayChangeStanding({ user_id: '10000001' }, null)).toBe(false);
    });

    test('a disabled row is offered enable, and never disable', () => {
        expect(standingAction({ user_id: '1', disabled: true })).toBe('enable');
        expect(standingAction({ user_id: '1', disabled: false })).toBe('disable');
        expect(standingAction({ user_id: '1' })).toBe('disable');
        expect(standingAction({ user_id: '1', disabled: 'yes' as never })).toBe('disable');
    });

    test('an administrator is offered revoke, and everyone else grant', () => {
        expect(adminAction({ user_id: '1', is_admin: true })).toBe('revoke');
        expect(adminAction({ user_id: '1' })).toBe('grant');
        expect(adminAction({ user_id: '1', is_admin: 1 as never })).toBe('grant');
    });

    test('a rejection needs a reason', () => {
        expect(rejectionRefusal('')?.code).toBe('reject_needs_reason');
        expect(rejectionRefusal('   ')?.code).toBe('reject_needs_reason');
        expect(rejectionRefusal('ships a binary')).toBe(null);
    });

    test('last seen is UNIX SECONDS, and a row with none says so', () => {
        expect(seenAtText(1789000000)).toBe('2026-09-10');
        expect(seenAtText(null)).toBe('');
        expect(seenAtText(undefined)).toBe('');
        expect(seenAtText(0)).toBe('');
        expect(seenAtText('2026-09-15' as never)).toBe('');
        expect(seenAtText(Number.NaN)).toBe('');
        expect(seenAtText(1e300)).toBe('');
    });

    test('a code is digits, with no length assumed', () => {
        expect(looksLikeCode('12345678')).toBe(true);
        expect(looksLikeCode('123456')).toBe(true);
        expect(looksLikeCode('1234 5678')).toBe(false);
        expect(looksLikeCode('')).toBe(false);
        expect(looksLikeCode('abcdefgh')).toBe(false);
    });

    test('the hash names the screen, and a stranger lands on the queue', () => {
        expect(parseRoute('#/users')).toBe('users');
        expect(parseRoute('#/notes')).toBe('notes');
        expect(parseRoute('#/system')).toBe('system');
        expect(parseRoute('#/queue')).toBe('queue');
        expect(parseRoute('')).toBe('queue');
        expect(parseRoute('#/nothing-like-it')).toBe('queue');
    });
});

describe('the api client', () => {
    test('every request is relative and carries the bearer when it should', async () => {
        const { fetcher, calls } = fakeFetch([
            { status: 200, body: { users: [], cursor: '' } },
        ]);
        const api = new AdminApi(fetcher, () => 'access-token-value');
        await api.users('');
        expect(calls[0]?.url).toBe('https://api.carnivore.ai/v1/users');
        expect(calls[0]?.headers.authorization).toBe('Bearer access-token-value');
    });

    test('the sign in routes carry NO bearer, because there is none yet', async () => {
        const { fetcher, calls } = fakeFetch([
            { status: 200, body: { session: 'cognito-session', destination: 'a***@b.c' } },
        ]);
        const api = new AdminApi(fetcher, () => '');
        const flow = await api.start('A@B.C');
        expect(calls[0]?.url).toBe('https://api.carnivore.ai/v1/auth/email/start');
        expect(calls[0]?.headers.authorization).toBeUndefined();
        expect(flow.destination).toBe('a***@b.c');
    });

    test('approve posts to the submission, with the bearer attached', async () => {
        const { fetcher, calls } = fakeFetch([{ status: 200, body: { ok: true } }]);
        const api = new AdminApi(fetcher, () => 'tok');
        await api.approve('ab/cd');
        expect(calls[0]?.method).toBe('POST');
        expect(calls[0]?.url).toBe('https://api.carnivore.ai/v1/submissions/ab%2Fcd/approve');
        expect(calls[0]?.headers.authorization).toBe('Bearer tok');
    });

    test('NEGATIVE CONTROL: a reject with no reason sends NOTHING', async () => {
        const { fetcher, calls } = fakeFetch([{ status: 200, body: { ok: true } }]);
        const api = new AdminApi(fetcher, () => 'tok');
        await expect(api.reject('ab', '  ')).rejects.toBeInstanceOf(ApiRefusal);
        expect(calls).toEqual([]);
        await api.reject('ab', 'ships a binary');
        expect(calls).toHaveLength(1);
        expect(calls[0]?.body).toBe(JSON.stringify({ reason: 'ships a binary' }));
    });

    test('a refusal is read from the CODE, never from the status', async () => {
        const { fetcher } = fakeFetch([
            { status: 400, body: { code: 'code_mismatch', detail: 'no' } },
        ]);
        const api = new AdminApi(fetcher, () => '');
        await expect(
            api.verify('a@b.c', { session: 's', destination: '' }, '1'),
        ).rejects.toMatchObject({ refusal: { status: 400, code: 'code_mismatch' } });
    });

    test('verify re-presents the ORIGINAL session, with the address beside it', async () => {
        const { fetcher, calls } = fakeFetch([{ status: 200, body: {} }]);
        const api = new AdminApi(fetcher, () => '');
        await api.verify('A@B.C', { session: 'THE-SESSION', destination: '' }, '12345678');
        expect(JSON.parse(calls[0]?.body || '{}')).toEqual({
            email: 'A@B.C',
            session: 'THE-SESSION',
            code: '12345678',
        });
    });

    test('a transport failure is a refusal too, not an unhandled throw', async () => {
        const { fetcher } = fakeFetch([new TypeError('network down')]);
        const api = new AdminApi(fetcher, () => 'tok');
        await expect(api.me()).rejects.toMatchObject({ refusal: { code: 'offline' } });
    });

    test('verify hands back the access token and nothing else', async () => {
        const { fetcher } = fakeFetch([
            {
                status: 200,
                body: {
                    access_token: 'ACCESS-VALUE',
                    refresh_token: 'REFRESH-VALUE',
                    login: 'a@b.c',
                    provider: 'email',
                },
            },
        ]);
        const api = new AdminApi(fetcher, () => '');
        const answer = await api.verify(
            'a@b.c',
            { session: 's', destination: '' },
            '12345678',
        );
        expect(answer.access_token).toBe('ACCESS-VALUE');
        expect(JSON.stringify(answer)).not.toContain('REFRESH-VALUE');
    });
});

describe('the page state machine', () => {
    test('signing in stores the access token and NOT the refresh token', async () => {
        const { fetcher } = fakeFetch([
            { status: 200, body: { session: 'COGNITO-SESSION', destination: 'a***@b.c' } },
            {
                status: 200,
                body: {
                    access_token: 'ACCESS-VALUE',
                    refresh_token: 'REFRESH-VALUE',
                    login: 'a@b.c',
                    provider: 'email',
                },
            },
            { status: 200, body: { ...ADMIN, is_admin: true } },
        ]);
        const { store, values } = memoryStore();
        const host = createHost({
            api: new AdminApi(fetcher, () => store.read()),
            tokens: store,
        });
        await host.start('A@B.C');
        expect(host.step).toBe('code');
        expect(host.destination).toBe('a***@b.c');
        await host.submitCode('12345678');
        expect(host.step).toBe('signed_in');
        expect(values[TOKEN_KEY]).toBe('ACCESS-VALUE');
        expect(JSON.stringify(values)).not.toContain('REFRESH-VALUE');
        expect(JSON.stringify(values)).not.toContain('COGNITO-SESSION');
        expect(host.me?.is_admin).toBe(true);
    });

    test('a code that is not digits is refused with nothing sent', async () => {
        const { fetcher, calls } = fakeFetch([
            { status: 200, body: { session: 's', destination: 'a***@b.c' } },
        ]);
        const { store } = memoryStore();
        const host = createHost({ api: new AdminApi(fetcher, () => ''), tokens: store });
        await host.start('a@b.c');
        await host.submitCode('not-a-code');
        expect(calls).toHaveLength(1);
        expect(host.refusal?.code).toBe('code_not_digits');
        expect(host.step).toBe('code');
    });

    test('NEGATIVE CONTROL: a 401 from any route signs the page out', async () => {
        const { fetcher } = fakeFetch([
            { status: 401, body: { code: 'unauthorized', detail: 'no' } },
        ]);
        const { store, values } = memoryStore();
        store.write('STALE-TOKEN');
        const host = createHost({
            api: new AdminApi(fetcher, () => store.read()),
            tokens: store,
        });
        await host.adopt();
        expect(host.step).toBe('email');
        expect(host.me).toBe(null);
        expect(values[TOKEN_KEY]).toBeUndefined();
        expect(host.refusal?.code).toBe('unauthorized');
    });

    test('NEGATIVE CONTROL: a 503 does NOT sign the page out', async () => {
        const { fetcher } = fakeFetch([
            { status: 503, body: { code: 'unavailable', detail: 'saturated' } },
        ]);
        const { store, values } = memoryStore();
        store.write('GOOD-TOKEN');
        const host = createHost({
            api: new AdminApi(fetcher, () => store.read()),
            tokens: store,
        });
        await host.adopt();
        expect(host.step).toBe('signed_in');
        expect(values[TOKEN_KEY]).toBe('GOOD-TOKEN');
        expect(host.refusal?.code).toBe('unavailable');
        expect(refusalMessage(host.refusal, t)).toBe(t('skill.refused.unavailable'));
        expect(host.busy).toBe(false);
    });

    test('NEGATIVE CONTROL: the caller disabling their own row sends nothing', async () => {
        const { fetcher, calls } = fakeFetch([
            { status: 200, body: { ...ADMIN } },
            { status: 200, body: { users: [], cursor: '' } },
        ]);
        const { store } = memoryStore();
        store.write('tok');
        const host = createHost({
            api: new AdminApi(fetcher, () => store.read()),
            tokens: store,
        });
        await host.adopt();
        const before = calls.length;
        await host.toggleStanding({ user_id: ADMIN.user_id });
        expect(calls).toHaveLength(before);
        expect(host.refusal?.code).toBe('self_change');
        expect(host.mayChange({ user_id: ADMIN.user_id })).toBe(false);
        await host.toggleStanding({ user_id: '10000001' });
        expect(calls).toHaveLength(before);
        host.setDisableReason('spam');
        await host.confirmDisable();
        expect(calls.length).toBeGreaterThan(before);
        expect(calls[before]?.url).toBe('https://api.carnivore.ai/v1/users/10000001/disable');
    });

    test('NEGATIVE CONTROL: confirming a rejection with no reason sends nothing', async () => {
        const { fetcher, calls } = fakeFetch([
            { status: 200, body: { ...ADMIN } },
            { status: 200, body: { status: 'pending', count: 0, submissions: [] } },
        ]);
        const { store } = memoryStore();
        store.write('tok');
        const host = createHost({
            api: new AdminApi(fetcher, () => store.read()),
            tokens: store,
        });
        await host.adopt();
        await host.loadQueue('pending');
        const before = calls.length;
        host.beginReject('ab');
        await host.confirmReject();
        expect(calls).toHaveLength(before);
        expect(host.refusal?.code).toBe('reject_needs_reason');
        expect(host.rejecting).toBe('ab');
    });

    test('a token store that cannot store is not a page that falls over', () => {
        const throwing = createTokenStore({
            get sessionStorage(): Storage {
                throw new Error('site data is blocked');
            },
        });
        expect(throwing.read()).toBe('');
        expect(() => throwing.write('x')).not.toThrow();
        expect(() => throwing.clear()).not.toThrow();
        const { store } = memoryStore();
        store.write('kept');
        expect(store.read()).toBe('kept');
    });
});

describe('Carnivore rename Phase 7: the admin token migrates, never copies', () => {
    const LEGACY_TOKEN_KEY = 'cloude.admin.access_token';

    test('a token sitting only under the legacy key is found on first read', () => {
        const { store, values } = memoryStore();
        values[LEGACY_TOKEN_KEY] = 'PRE-RENAME-TOKEN';
        expect(store.read()).toBe('PRE-RENAME-TOKEN');
    });

    test('the legacy-only token MOVES: new key gains it, legacy key is gone, never both at once', () => {
        const { store, values } = memoryStore();
        values[LEGACY_TOKEN_KEY] = 'PRE-RENAME-TOKEN';
        store.read();
        expect(values[TOKEN_KEY]).toBe('PRE-RENAME-TOKEN');
        expect(values[LEGACY_TOKEN_KEY]).toBeUndefined();
        expect(Object.keys(values)).toEqual([TOKEN_KEY]);
    });

    test('a second read after the migration still answers, from the new key alone', () => {
        const { store, values } = memoryStore();
        values[LEGACY_TOKEN_KEY] = 'PRE-RENAME-TOKEN';
        store.read();
        expect(store.read()).toBe('PRE-RENAME-TOKEN');
        expect(values[LEGACY_TOKEN_KEY]).toBeUndefined();
    });

    test('a token already under the new key is used as-is, legacy left untouched', () => {
        const { store, values } = memoryStore();
        values[TOKEN_KEY] = 'FRESH-TOKEN';
        values[LEGACY_TOKEN_KEY] = 'STALE-TOKEN';
        expect(store.read()).toBe('FRESH-TOKEN');
        expect(values[LEGACY_TOKEN_KEY]).toBe('STALE-TOKEN');
    });

    test('write() lands on the new key only, and never re-mints the legacy name', () => {
        const { store, values } = memoryStore();
        store.write('BRAND-NEW-TOKEN');
        expect(values[TOKEN_KEY]).toBe('BRAND-NEW-TOKEN');
        expect(values[LEGACY_TOKEN_KEY]).toBeUndefined();
    });

    test('a full sign-in after a legacy-token migration writes the new key only', async () => {
        const { fetcher } = fakeFetch([
            { status: 200, body: { session: 's', destination: 'a***@b.c' } },
            {
                status: 200,
                body: {
                    access_token: 'NEW-LOGIN-TOKEN',
                    refresh_token: 'REFRESH-VALUE',
                    login: 'a@b.c',
                    provider: 'email',
                },
            },
            { status: 200, body: { ...ADMIN, is_admin: true } },
        ]);
        const { store, values } = memoryStore();
        values[LEGACY_TOKEN_KEY] = 'OLD-SESSION-TOKEN';
        const host = createHost({
            api: new AdminApi(fetcher, () => store.read()),
            tokens: store,
        });
        await host.start('a@b.c');
        await host.submitCode('12345678');
        expect(values[TOKEN_KEY]).toBe('NEW-LOGIN-TOKEN');
        expect(values[LEGACY_TOKEN_KEY]).toBeUndefined();
    });

    test('clear() removes both the new key and a not-yet-migrated legacy leftover', () => {
        const { store, values } = memoryStore();
        values[TOKEN_KEY] = 'CURRENT-TOKEN';
        values[LEGACY_TOKEN_KEY] = 'NEVER-READ-IN-THIS-TAB';
        store.clear();
        expect(values[TOKEN_KEY]).toBeUndefined();
        expect(values[LEGACY_TOKEN_KEY]).toBeUndefined();
    });

    test('neither key present still answers empty, and writes nothing', () => {
        const { store, values } = memoryStore();
        expect(store.read()).toBe('');
        expect(Object.keys(values)).toEqual([]);
    });
});
