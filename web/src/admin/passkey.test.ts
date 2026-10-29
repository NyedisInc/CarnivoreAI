/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount } from 'svelte';

import { AdminApi, type Fetcher } from './admin.js';
import { createHost, createTokenStore, TOKEN_KEY } from './admin-host.svelte.js';
import { b64uDecode, b64uEncode, type CredentialsLike } from './passkey.js';
import Passkeys from './Passkeys.svelte';
import { refusalMessage } from './admin.js';
import { t } from './text.js';

interface Call {
    method: string;
    url: string;
    body: Record<string, unknown>;
}

const BASE = 'https://api.carnivore.ai/v1';
const CHALLENGE = new Uint8Array([251, 255, 190, 250, 62]);

function routed(answers: Record<string, unknown>) {
    const calls: Call[] = [];
    const fetcher: Fetcher = async (url, init) => {
        const method = init?.method || 'GET';
        const body = init?.body ? JSON.parse(init.body) : {};
        calls.push({ method, url, body });
        let answer = answers[method + ' ' + url] as { status: number; body: unknown } | (() => { status: number; body: unknown });
        if (typeof answer === 'function') answer = answer();
        if (!answer) throw new Error('unscripted request: ' + method + ' ' + url);
        return { ok: answer.status < 300, status: answer.status, json: async () => answer.body };
    };
    return { fetcher, calls };
}

function browser(refuse = false) {
    const seen: { get: Record<string, any>[]; create: Record<string, any>[] } = { get: [], create: [] };
    const raw = (n: number) => new Uint8Array([n, 255, 254]).buffer;
    const creds: CredentialsLike = {
        async get({ publicKey }) {
            seen.get.push(publicKey);
            if (refuse) throw new DOMException('no', 'NotAllowedError');
            return {
                rawId: raw(1),
                response: {
                    clientDataJSON: raw(2), authenticatorData: raw(3), signature: raw(4), userHandle: raw(5),
                },
            };
        },
        async create({ publicKey }) {
            seen.create.push(publicKey);
            if (refuse) throw new DOMException('no', 'NotAllowedError');
            return {
                rawId: raw(6),
                response: { clientDataJSON: raw(7), attestationObject: raw(8), getTransports: () => ['internal'] },
            };
        },
    };
    return { creds, seen };
}

const OPTIONS = {
    publicKey: {
        rpId: 'admin.carnivore.ai', challenge: b64uEncode(CHALLENGE), timeout: 120000,
        userVerification: 'required', allowCredentials: [],
    },
    challenge_token: 'chtok',
};
const REG_OPTIONS = {
    publicKey: {
        rp: { id: 'admin.carnivore.ai', name: 'carnivore admin' }, user: { id: b64uEncode(CHALLENGE), name: 'a@b.c', displayName: 'a@b.c' },
        challenge: b64uEncode(CHALLENGE), authenticatorSelection: { residentKey: 'required', userVerification: 'required' },
        excludeCredentials: [],
    },
    challenge_token: 'regtok',
};
const ADMIN = { user_id: 'cognito:1', login: 'a@b.c', provider: 'email', is_admin: true };

function build(answers: Record<string, unknown>, refuse = false) {
    const { fetcher, calls } = routed(answers);
    const { creds, seen } = browser(refuse);
    const tokens = createTokenStore(globalThis);
    const host = createHost({ api: new AdminApi(fetcher, () => tokens.read()), tokens, credentials: () => creds });
    return { host, calls, seen };
}

afterEach(() => {
    window.sessionStorage.clear();
    document.body.innerHTML = '';
});

describe('passkey sign in', () => {
    test('hands the browser the decoded server challenge and posts a base64url assertion with the challenge token', async () => {
        const { host, calls, seen } = build({
            [`POST ${BASE}/auth/passkey/login/options`]: { status: 200, body: OPTIONS },
            [`POST ${BASE}/auth/passkey/login/verify`]: { status: 200, body: { access_token: 'tok-passkey', login: 'a@b.c', refresh_token: 'NEVER' } },
            [`GET ${BASE}/me`]: { status: 200, body: ADMIN },
        });
        await host.signInPasskey();

        const given = seen.get[0]!;
        expect(Array.from(new Uint8Array(given.challenge))).toEqual(Array.from(CHALLENGE));
        expect(given.rpId).toBe('admin.carnivore.ai');
        expect(given.userVerification).toBe('required');

        const verify = calls.find((c) => c.url.endsWith('/login/verify'))!;
        expect(verify.body.challenge_token).toBe('chtok');
        const wire = JSON.stringify(verify.body);
        expect(wire).not.toMatch(/[+=]/);
        expect(verify.body.rawId).toBe(b64uEncode(new Uint8Array([1, 255, 254])));
        expect((verify.body.response as Record<string, string>).signature).toBe(b64uEncode(new Uint8Array([4, 255, 254])));

        expect(host.step).toBe('signed_in');
        expect(window.sessionStorage.getItem(TOKEN_KEY)).toBe('tok-passkey');
        expect(JSON.stringify(window.sessionStorage)).not.toContain('NEVER');
        expect(JSON.stringify(window.localStorage)).not.toContain('tok-passkey');
    });

    test('a refused browser prompt is a plain sentence and posts nothing', async () => {
        const { host, calls } = build({ [`POST ${BASE}/auth/passkey/login/options`]: { status: 200, body: OPTIONS } }, true);
        await host.signInPasskey();
        expect(calls.some((c) => c.url.endsWith('/login/verify'))).toBe(false);
        expect(host.step).not.toBe('signed_in');
        expect(refusalMessage(host.refusal, t)).toBe(t('admin.refused.passkey_cancelled'));
        expect(window.sessionStorage.getItem(TOKEN_KEY)).toBeNull();
    });
});

describe('first enrolment', () => {
    test('asks the server with the terminal code before the browser creates, then posts the attestation', async () => {
        const { host, calls, seen } = build({
            [`POST ${BASE}/auth/passkey/register/options`]: { status: 200, body: REG_OPTIONS },
            [`POST ${BASE}/auth/passkey/register/verify`]: { status: 200, body: { ok: true } },
            [`GET ${BASE}/auth/passkey/credentials`]: {
                status: 200,
                body: { configured: true, required: false, enrolled: true, can_enroll_first: false, window_open: false, credentials: [] },
            },
        });
        window.sessionStorage.setItem(TOKEN_KEY, 'email-session');
        const ok = await host.pk.enroll('first', ' 0123456789abcdef ', 'mac');
        expect(ok).toBe(true);
        expect(calls[0]!.url).toBe(`${BASE}/auth/passkey/register/options`);
        expect(calls[0]!.body).toEqual({ mode: 'first', enrol_code: '0123456789abcdef' });
        expect(seen.create).toHaveLength(1);
        expect(Array.from(new Uint8Array(seen.create[0]!.challenge))).toEqual(Array.from(CHALLENGE));
        const verify = calls[1]!;
        expect(verify.body.challenge_token).toBe('regtok');
        expect(verify.body.enrol_code).toBe('0123456789abcdef');
        expect(verify.body.label).toBe('mac');
        expect(JSON.stringify(verify.body)).not.toMatch(/[+=]/);
        expect(host.step).toBe('signed_in');
    });

    test('a wrong code stops before the browser is asked to create', async () => {
        const { host, seen } = build({
            [`POST ${BASE}/auth/passkey/register/options`]: { status: 403, body: { code: 'bad_enrol_code' } },
        });
        window.sessionStorage.setItem(TOKEN_KEY, 'email-session');
        expect(await host.pk.enroll('first', 'nope', 'mac')).toBe(false);
        expect(seen.create).toEqual([]);
        expect(refusalMessage(host.refusal, t)).toBe(t('admin.refused.bad_enrol_code'));
    });
});

describe('the passkey list', () => {
    test('removes an item through the danger button and reads the list again', async () => {
        let rows = [
            { id: 'aa', label: 'mac', created_at: 1789000000, last_used_at: 0, synced: true },
            { id: 'bb', label: 'key', created_at: 1789000000, last_used_at: 1789000100, synced: false },
        ];
        const status = () => ({
            status: 200,
            body: { configured: true, required: false, enrolled: true, can_enroll_first: false, window_open: false, credentials: rows },
        });
        const { host, calls } = build({
            [`GET ${BASE}/auth/passkey/credentials`]: status,
            [`DELETE ${BASE}/auth/passkey/credentials/aa`]: () => {
                rows = rows.filter((r) => r.id !== 'aa');
                return { status: 200, body: { ok: true } };
            },
        });
        window.sessionStorage.setItem(TOKEN_KEY, 'passkey-session');
        const target = document.createElement('div');
        document.body.appendChild(target);
        mount(Passkeys, { target, props: { host } });
        await host.pk.load();
        flushSync();
        const buttons = () => Array.from(target.querySelectorAll<HTMLButtonElement>('button[data-btn="danger"]'));
        expect(buttons()).toHaveLength(2);
        expect(target.textContent).toContain('mac');
        buttons()[0]!.click();
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 0));
        flushSync();
        expect(calls.some((c) => c.method === 'DELETE' && c.url.endsWith('/credentials/aa'))).toBe(true);
        expect(buttons()).toHaveLength(1);
        expect(target.textContent).not.toContain('mac');
    });

    test('a fresh_passkey_required answer runs one passkey sign in and repeats the action once', async () => {
        let attempts = 0;
        const { host, calls } = build({
            [`DELETE ${BASE}/auth/passkey/credentials/aa`]: () => {
                attempts += 1;
                return attempts === 1 ? { status: 403, body: { code: 'fresh_passkey_required' } } : { status: 200, body: { ok: true } };
            },
            [`POST ${BASE}/auth/passkey/login/options`]: { status: 200, body: OPTIONS },
            [`POST ${BASE}/auth/passkey/login/verify`]: { status: 200, body: { access_token: 'fresh', login: 'a@b.c' } },
            [`GET ${BASE}/auth/passkey/credentials`]: {
                status: 200,
                body: { configured: true, required: false, enrolled: true, can_enroll_first: false, window_open: false, credentials: [] },
            },
        });
        window.sessionStorage.setItem(TOKEN_KEY, 'old');
        await host.pk.remove('aa');
        expect(calls.filter((c) => c.method === 'DELETE')).toHaveLength(2);
        expect(window.sessionStorage.getItem(TOKEN_KEY)).toBe('fresh');
    });
});

describe('base64url', () => {
    test('encodes without + / or padding and round trips', () => {
        const text = b64uEncode(CHALLENGE);
        expect(text).toBe('-_---j4');
        expect(text).not.toMatch(/[+/=]/);
        expect(Array.from(b64uDecode(text))).toEqual(Array.from(CHALLENGE));
    });
});
