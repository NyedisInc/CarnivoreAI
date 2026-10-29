/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import Pair from './Pair.svelte';
import { claimSecret, navigate, pairStatus, submitCode, verifyOtp } from './pair-api';
import { setLocale } from '../lib/i18n/index.svelte';

setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
    vi.unstubAllGlobals();
    history.replaceState(null, '', '/');
    localStorage.clear();
});

const reply = (status: number, body: unknown = {}) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

type Answers = Record<string, Response | Error>;
let replaced: string[] = [];

async function render(hash: string, standalone: boolean, answers: Answers) {
    history.replaceState(null, '', `/pair${hash}`);
    replaced = [];
    const fetchMock = vi.fn(async (path: string) => {
        const answer = answers[path];
        if (answer instanceof Error) throw answer;
        return (answer ?? reply(404)).clone();
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(navigate, 'to').mockImplementation((url: string) => void replaced.push(url));
    window.matchMedia = ((q: string) => ({ matches: standalone && q.includes('standalone') })) as typeof window.matchMedia;
    mounted.push(mount(Pair, { target: document.body }));
    await settle();
    return fetchMock;
}
const settle = async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
    for (let i = 0; i < 5; i++) await tick();
    flushSync();
};
const q = (sel: string) => document.querySelector(sel);
const type = async (sel: string, value: string) => {
    (q(sel) as HTMLInputElement).value = value;
    (q(sel) as HTMLInputElement).dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
};

describe('pair page', () => {
    test('a QR fragment is cleared from the address bar BEFORE the claim, and the claim only asks for the authenticator code', async () => {
        let hashAtFetch = 'unset';
        history.replaceState(null, '', '/pair#sekrit');
        const fetchMock = await render('#sekrit', false, { '/pair/claim': reply(200, { ok: true, status: 'pending' }) });
        hashAtFetch = location.hash;
        expect(hashAtFetch).toBe('');
        const [path, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
        expect(path).toBe('/pair/claim');
        expect(JSON.parse(init.body as string).secret).toBe('sekrit');
        expect(q('[data-pair="otp-code"]')).not.toBeNull();
        expect(replaced).toEqual([]);
        expect(localStorage.getItem('claude_tunnel_token')).toBeNull();
    });

    test('the right authenticator code keeps the session, then the app opens', async () => {
        const fetchMock = await render('#sekrit', false, {
            '/pair/claim': reply(200, { ok: true, status: 'pending' }),
            '/pair/verify': reply(200, { ok: true, status: 'paired', access_token: 'A', refresh_token: 'R' }),
        });
        await type('[data-pair="otp-code"]', '123456');
        (q('[data-pair="otp-submit"]') as HTMLButtonElement).click();
        await settle();
        const verify = fetchMock.mock.calls.find((c) => c[0] === '/pair/verify') as unknown as [string, RequestInit];
        expect(JSON.parse(verify[1].body as string)).toEqual({ code: '123456' });
        expect(localStorage.getItem('claude_tunnel_token')).toBe('A');
        expect(localStorage.getItem('claude_refresh_token')).toBe('R');
        expect(replaced).toEqual(['/']);
    });

    test('a wrong code stays on the code step; a dead pairing goes back to scanning', async () => {
        await render('#sekrit', false, { '/pair/claim': reply(200, { status: 'pending' }), '/pair/verify': reply(401, { detail: 'x' }) });
        await type('[data-pair="otp-code"]', '000000');
        (q('[data-pair="otp-submit"]') as HTMLButtonElement).click();
        await settle();
        expect(q('[data-pair-error="wrong_otp"]')).not.toBeNull();
        expect(q('[data-pair="otp-code"]')).not.toBeNull();
        vi.stubGlobal('fetch', vi.fn(async () => reply(403, { detail: 'pairing_dead' })));
        await type('[data-pair="otp-code"]', '111111');
        (q('[data-pair="otp-submit"]') as HTMLButtonElement).click();
        await settle();
        expect(q('[data-pair-error="pairing_dead"]')?.textContent).toContain('ran out');
        expect(q('[data-pair="otp-code"]')).toBeNull();
        expect(q('[data-pair="no-camera"]')).not.toBeNull();
        expect(replaced).toEqual([]);
    });

    test('a browser that is already paired goes straight in', async () => {
        await render('#again', false, { '/pair/claim': reply(200, { ok: true, status: 'already_paired' }) });
        expect(replaced).toEqual(['/']);
        document.body.replaceChildren();
        await render('', false, { '/pair/status': reply(200, { paired: true, pending: false }) });
        expect(replaced).toEqual(['/']);
    });

    test('a reload mid pairing asks for the code again', async () => {
        await render('', false, { '/pair/status': reply(200, { paired: false, pending: true }) });
        expect(q('[data-pair="otp-code"]')).not.toBeNull();
    });

    test('an expired or used link says so and keeps the typed code one tap away', async () => {
        await render('#old', false, { '/pair/claim': reply(403, { detail: 'link_used' }) });
        expect(q('[data-pair-error="link_used"]')?.textContent).toContain('ran out or was already used');
        expect(q('[data-pair="code"]')).toBeNull();
        (q('[data-pair="no-camera"]') as HTMLButtonElement).click();
        flushSync();
        expect(q('[data-pair="code"]')).not.toBeNull();
    });

    test('an unpaired browser with no fragment says to scan, with the form behind a button', async () => {
        await render('', false, { '/pair/status': reply(200, { paired: false, pending: false }) });
        expect(q('.pair__head')?.textContent).toContain('scan the code on your computer');
        expect(q('[data-pair="code"]')).toBeNull();
        expect(q('[data-pair="no-camera"]')).not.toBeNull();
    });

    test('the installed app with no cookie shows the code entry at once', async () => {
        await render('', true, { '/pair/status': reply(200, { paired: false, pending: false }) });
        expect(q('.pair__head')?.textContent).toContain('this app is not paired yet');
        expect(q('[data-pair="code"]')).not.toBeNull();
    });

    test('a typed window code leads to the authenticator code, not into the app', async () => {
        await render('', true, { '/pair/status': reply(200, { paired: false, pending: false }), '/pair/code': reply(200, { ok: true, status: 'pending' }) });
        await type('[data-pair="code"]', 'abcd2345');
        (q('[data-pair="submit"]') as HTMLButtonElement).click();
        await settle();
        expect(q('[data-pair="otp-code"]')).not.toBeNull();
        expect(replaced).toEqual([]);
    });

    test('the installed app still clears a fragment from the address bar and claims it like safari', async () => {
        const fetchMock = await render('#secret', true, { '/pair/claim': reply(200, { status: 'pending' }) });
        expect(location.hash).toBe('');
        expect(fetchMock.mock.calls[0]?.[0]).toBe('/pair/claim');
    });
});

describe('pair api', () => {
    test('429 is throttled, 503 unavailable, a network failure network, a bad origin its own failure', async () => {
        expect(await claimSecret('x', (async () => reply(429)) as unknown as typeof fetch)).toEqual({ ok: false, failure: 'throttled' });
        expect(await submitCode('abc', (async () => reply(503)) as unknown as typeof fetch)).toEqual({ ok: false, failure: 'unavailable' });
        expect(await submitCode('abc', (async () => { throw new TypeError('x'); }) as unknown as typeof fetch)).toEqual({ ok: false, failure: 'network' });
        expect(await claimSecret('x', (async () => reply(403, { detail: 'bad_origin' })) as unknown as typeof fetch)).toEqual({ ok: false, failure: 'bad_origin' });
        expect(await verifyOtp('1', (async () => reply(401)) as unknown as typeof fetch)).toEqual({ ok: false, failure: 'wrong_otp' });
        expect(await verifyOtp('1', (async () => reply(403, { detail: 'no_pending' })) as unknown as typeof fetch)).toEqual({ ok: false, failure: 'pairing_dead' });
    });
    test('a typed code is trimmed and upper cased before it is sent', async () => {
        let body = '';
        await submitCode(' ab12 ', (async (_p: string, init: RequestInit) => { body = init.body as string; return reply(200); }) as unknown as typeof fetch);
        expect(JSON.parse(body).code).toBe('AB12');
    });
    test('a failed status check reads as neither paired nor pending', async () => {
        expect(await pairStatus((async () => { throw new TypeError('x'); }) as unknown as typeof fetch)).toEqual({ paired: false, pending: false });
    });
});

describe('pair page per-address hint', () => {
    test('the scan page explains that pairing is kept per address', async () => {
        await render('', false, { '/pair/status': reply(200, { paired: false, pending: false }) });
        expect(q('[data-pair="per-address-hint"]')?.textContent).toContain('pairing is kept per address');
    });
});
