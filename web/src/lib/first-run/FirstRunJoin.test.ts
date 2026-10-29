/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import FirstRun from './FirstRun.svelte';
import FirstRunJoin from './FirstRunJoin.svelte';
import { decideEntry, fetchEnrollment } from './first-run-api';
import { errorKeyFor } from './join-api';
import { setLocale, t } from '../i18n/index.svelte';

setLocale('en');

const json = (status: number, body: unknown = {}) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const status = (state: string, extra: Record<string, unknown> = {}) => json(200, { state, error: null, main_label: null, candidates: [], ...extra });
const STATUS = '/api/v1/auth/join/status';
const POST = '/api/v1/auth/join';

type Handler = () => Response | Error | Promise<Response>;
let calls: Array<{ url: string; init?: RequestInit }> = [];
let routes: Record<string, Handler | Handler[]> = {};
const auth = { showLoginForm: vi.fn(), acceptLogin: vi.fn(), finishFirstRun: vi.fn() };
const mounted: ReturnType<typeof mount>[] = [];

function install(map: Record<string, Handler | Handler[]>): void {
    routes = map;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, init });
        const entry = routes[url];
        const handler = Array.isArray(entry) ? (entry.length > 1 ? entry.shift()! : entry[0]!) : entry;
        const out = handler ? await handler() : json(404);
        if (out instanceof Error) throw out;
        return out.clone();
    }));
}
const count = (url: string) => calls.filter((c) => c.url === url).length;
const settle = async () => {
    for (let i = 0; i < 8; i++) await tick();
    flushSync();
};
const q = (sel: string) => document.querySelector(sel) as HTMLElement | null;
const all = (sel: string) => Array.from(document.querySelectorAll(sel)) as HTMLInputElement[];
const click = async (sel: string) => {
    (q(sel) as HTMLElement).click();
    await vi.advanceTimersByTimeAsync(0);
    await settle();
};
const elapse = async (ms: number) => {
    await vi.advanceTimersByTimeAsync(ms);
    await settle();
};
async function render(entry: 'first-run' | 'remote' | 'joined' = 'first-run') {
    mounted.push(mount(FirstRun, { target: document.body, props: { entry } }));
    await vi.advanceTimersByTimeAsync(0);
    await settle();
}
async function paste(text: string) {
    const event = new Event('paste', { bubbles: true, cancelable: true }) as Event & { clipboardData: unknown };
    event.clipboardData = { getData: () => text };
    all('[data-first-run="cell"]')[0]!.dispatchEvent(event);
    await vi.advanceTimersByTimeAsync(0);
    await settle();
}
const postBodies = () => calls.filter((c) => c.url === POST).map((c) => JSON.parse(String(c.init?.body)));

beforeEach(() => {
    vi.useFakeTimers();
    calls = [];
    Object.values(auth).forEach((f) => f.mockReset());
    (window as unknown as { Auth: unknown }).Auth = auth;
    delete (window as unknown as Record<string, unknown>).carnivoreDesktop;
});
afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe('entry rows', () => {
    const cases: Array<[string, unknown, string]> = [
        ['joined and local', { paired: true, local: true, joined: true, join_pending: false }, 'joined'],
        ['joined but not local', { paired: true, local: false, joined: true, join_pending: false }, 'totp'],
        ['join pending and local', { paired: false, local: true, joined: false, join_pending: true }, 'first-run'],
        ['join pending, not local', { paired: false, local: false, joined: false, join_pending: true }, 'remote'],
        ['joined is the string "true"', { paired: true, local: true, joined: 'true' }, 'totp'],
        ['unpaired and local', { paired: false, local: true, joined: false, join_pending: false }, 'first-run'],
    ];
    test.each(cases)('%s', async (_name, body, want) => {
        install({ '/api/v1/auth/enrollment/status': () => json(200, body) });
        expect(await decideEntry()).toBe(want);
    });
    test('409 joined from the enrollment is its own failure', async () => {
        install({ '/api/v1/auth/enrollment': () => json(409, { detail: { reason: 'joined' } }) });
        expect(await fetchEnrollment()).toEqual({ ok: false, failure: 'joined' });
    });
});

describe('choose and the cells', () => {
    test('opens on the choice and does not poll while it shows', async () => {
        install({ [STATUS]: () => status('idle') });
        await render();
        expect(q('[data-first-run="choose-new"]')!.textContent).toBe(t('first_run.choose.new'));
        expect(q('[data-first-run="choose-join"]')!.textContent).toBe(t('first_run.choose.join'));
        await elapse(10_000);
        expect(count(STATUS)).toBe(1);
        expect(count(POST)).toBe(0);
    });

    test('join shows six numeric one-time-code cells; back returns to the choice', async () => {
        install({ [STATUS]: () => status('idle') });
        await render();
        await click('[data-first-run="choose-join"]');
        const cells = all('[data-first-run="cell"]');
        expect(cells).toHaveLength(6);
        for (const cell of cells) {
            expect(cell.getAttribute('inputmode')).toBe('numeric');
            expect(cell.getAttribute('autocomplete')).toBe('one-time-code');
        }
        expect(q('[data-first-run="warning-setup"]')).toBeNull();
        await click('[data-first-run="back"]');
        expect(q('[data-first-run="choose-new"]')).not.toBeNull();
    });

    test('a paste fills every cell, the sixth digit submits once, no Authorization header', async () => {
        install({ [STATUS]: () => status('idle'), [POST]: () => new Promise<Response>(() => undefined) });
        await render();
        await click('[data-first-run="choose-join"]');
        await paste('12 34-56');
        expect(all('[data-first-run="cell"]').map((c) => c.value).join('')).toBe('123456');
        expect(postBodies()).toEqual([{ code: '123456' }]);
        for (const c of calls) expect(JSON.stringify(c.init?.headers ?? {}).toLowerCase()).not.toContain('authorization');
    });

    test('typing digit by digit submits on the sixth', async () => {
        install({ [STATUS]: () => status('idle'), [POST]: () => json(202, { state: 'finding', error: null, main_label: null, candidates: [] }) });
        await render();
        await click('[data-first-run="choose-join"]');
        const cells = all('[data-first-run="cell"]');
        for (const [i, d] of ['1', '2', '3', '4', '5'].entries()) {
            cells[i]!.value = d;
            cells[i]!.dispatchEvent(new Event('input', { bubbles: true }));
        }
        await settle();
        expect(count(POST)).toBe(0);
        cells[5]!.value = '6';
        cells[5]!.dispatchEvent(new Event('input', { bubbles: true }));
        await vi.advanceTimersByTimeAsync(0);
        expect(postBodies()).toEqual([{ code: '123456' }]);
    });

    test('a pasted link posts the link and never a code', async () => {
        install({ [STATUS]: () => status('idle'), [POST]: () => json(202, { state: 'finding', error: null, main_label: null, candidates: [] }) });
        await render();
        await click('[data-first-run="choose-join"]');
        await click('[data-first-run="toggle-link"]');
        const field = q('[data-first-run="link"]') as HTMLInputElement;
        field.value = 'carnivore://join/v1?h=a&p=1&k=0&i=x&s=y';
        field.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        await click('[data-first-run="join-go"]');
        expect(postBodies()).toEqual([{ link: 'carnivore://join/v1?h=a&p=1&k=0&i=x&s=y' }]);
    });

    test('the set-up warning shows only when the view says the computer is set up', async () => {
        mounted.push(mount(FirstRunJoin, { target: document.body, props: { setup: true, onBack: () => undefined } }));
        await settle();
        expect(q('[data-first-run="warning-setup"]')!.textContent).toBe(t('first_run.join.warning_setup'));
    });
});

describe('joining', () => {
    const accepted = () => json(202, { state: 'finding', error: null, main_label: null, candidates: [] });

    test('polls once a second ONLY while joining, shows the step, ends at joined and stops', async () => {
        install({
            [STATUS]: [() => status('idle'), () => status('finding'), () => status('connecting'), () => status('joined', { main_label: 'studio' })],
            [POST]: accepted,
        });
        await render();
        await click('[data-first-run="choose-join"]');
        await paste('123456');
        expect(q('[data-first-run="joining"]')!.textContent).toBe(t('first_run.join.step.finding'));
        const before = count(STATUS);
        await elapse(999);
        expect(count(STATUS)).toBe(before);
        await elapse(2);
        await elapse(1000);
        expect(q('[data-first-run="joining"]')!.textContent).toBe(t('first_run.join.step.connecting'));
        await elapse(1000);
        expect(q('[data-first-run="joined"]')!.textContent).toBe(t('first_run.join.done', { name: 'studio' }));
        expect(q('[data-first-run="joined-browser"]')!.textContent).toBe(t('first_run.join.done_browser', { name: 'studio' }));
        expect(q('[data-first-run="code"]')).toBeNull();
        const done = count(STATUS);
        await elapse(10_000);
        expect(count(STATUS)).toBe(done);
        expect(auth.acceptLogin).not.toHaveBeenCalled();
    });

    test('a used up code shows its words and try again returns to empty cells', async () => {
        install({ [STATUS]: [() => status('idle'), () => status('failed', { error: 'no_invite' })], [POST]: accepted });
        await render();
        await click('[data-first-run="choose-join"]');
        await paste('123456');
        await elapse(1000);
        expect(q('[data-first-run-error]')!.getAttribute('data-first-run-error')).toBe('used_up');
        expect(q('[data-first-run-error]')!.textContent).toBe(t('first_run.join.error.used_up'));
        await click('[data-first-run="retry"]');
        expect(all('[data-first-run="cell"]').every((c) => c.value === '')).toBe(true);
    });

    test('a refused start shows the words for the refusal', async () => {
        install({ [STATUS]: () => status('idle'), [POST]: () => json(429, {}) });
        await render();
        await click('[data-first-run="choose-join"]');
        await paste('123456');
        expect(q('[data-first-run-error]')!.getAttribute('data-first-run-error')).toBe('rate_limited');
    });

    test('several packs: rows show name and short id, a pick posts again with the same code and the fid', async () => {
        const candidates = [{ name: 'studio', fid: 'aaaa', fid_short: 'aa11' }, { name: 'laptop', fid: 'bbbb', fid_short: 'bb22' }];
        install({
            [STATUS]: () => status('idle'),
            [POST]: [() => json(202, { state: 'finding', error: null, main_label: null, candidates }), accepted],
        });
        await render();
        await click('[data-first-run="choose-join"]');
        await paste('123456');
        const rows = all('[data-first-run="pack"]');
        expect(rows.map((r) => r.textContent!.trim())).toEqual(['studio aa11', 'laptop bb22']);
        rows[1]!.click();
        await vi.advanceTimersByTimeAsync(0);
        await settle();
        expect(postBodies()).toEqual([{ code: '123456' }, { code: '123456', candidate_fid: 'bbbb' }]);
    });

    test('look for a pack: two offers, no hides one, yes then a code posts that candidate_fid (#1622)', async () => {
        const candidates = [
            { name: 'studio', fid: 'aaaa', fid_short: 'aa11', pack_name: null, label: 'studio aa11' },
            { name: 'laptop', fid: 'bbbb', fid_short: 'bb22', pack_name: 'home <b>pack</b>', label: 'home <b>pack</b>' },
        ];
        install({
            [STATUS]: [() => status('idle'), () => status('finding', { candidates })],
            '/api/v1/auth/join/look': () => json(202, { state: 'waiting_relay', error: null, main_label: null, candidates: [] }),
            [POST]: accepted,
        });
        await render();
        await click('[data-first-run="choose-join"]');
        await click('[data-first-run="look"]');
        expect(q('[data-first-run="joining"]')!.textContent).toBe(t('first_run.join.step.looking'));
        await elapse(1000);
        const offers = all('[data-first-run="offer"]');
        expect(offers.map((o) => o.querySelector('p')!.textContent)).toEqual(['join studio aa11?', 'join home <b>pack</b>?']);
        expect(offers[1]!.querySelector('b')).toBeNull();
        (offers[0]!.querySelector('[data-first-run="offer-no"]') as HTMLElement).click();
        await settle();
        expect(all('[data-first-run="offer"]')).toHaveLength(1);
        await click('[data-first-run="offer-yes"]');
        await paste('123456');
        expect(postBodies()).toEqual([{ code: '123456', candidate_fid: 'bbbb' }]);
    });

    test('a reload while several packs are held opens on the code cells, not on rows that would post an empty code (P9)', async () => {
        const candidates = [{ name: 'studio', fid: 'aaaa', fid_short: 'aa11' }, { name: 'laptop', fid: 'bbbb', fid_short: 'bb22' }];
        install({ [STATUS]: () => status('finding', { candidates }) });
        await render();
        expect(all('[data-first-run="pack"]')).toHaveLength(0);
        expect(all('[data-first-run="cell"]')).toHaveLength(6);
    });

    test('a join already running opens on joining, not on the choice', async () => {
        install({ [STATUS]: () => status('connecting') });
        await render();
        expect(q('[data-first-run="choose-new"]')).toBeNull();
        expect(q('[data-first-run="joining"]')!.textContent).toBe(t('first_run.join.step.connecting'));
    });

    test('every server error code maps to a catalog key that exists', () => {
        const codes = ['wrong_code', 'no_invite', 'expired', 'no_pack', 'unreachable', 'local_network_blocked', 'main_mismatch', 'busy',
            'rate_limited', 'refused', 'needs_owner', 'bad_link', 'join_has_peers', 'join_failed', 'something_new'];
        for (const code of codes) {
            const key = `first_run.join.error.${errorKeyFor(code)}`;
            expect(t(key), code).not.toBe(key);
        }
        expect(errorKeyFor('no_invite')).toBe('used_up');
        expect(errorKeyFor(null)).toBe('refused');
    });
});

describe('joined', () => {
    test('the desktop window signs itself in through the local login once the final step lands', async () => {
        const localLogin = vi.fn().mockResolvedValueOnce(null).mockResolvedValueOnce(null).mockResolvedValue({ access_token: 'a', refresh_token: 'r' });
        (window as unknown as Record<string, unknown>).carnivoreDesktop = { localLogin };
        install({ [STATUS]: () => status('joined', { main_label: 'studio' }) });
        await render();
        expect(localLogin).toHaveBeenCalledTimes(1);
        expect(q('[data-first-run="joined-browser"]')).toBeNull();
        await elapse(1000);
        await elapse(1000);
        expect(localLogin).toHaveBeenCalledTimes(3);
        expect(auth.acceptLogin).toHaveBeenCalledWith({ access_token: 'a', refresh_token: 'r' });
        expect(auth.finishFirstRun).toHaveBeenCalledTimes(1);
    });

    test('the joined entry in a plain browser shows the message and no sign in form', async () => {
        install({});
        await render('joined');
        expect(q('[data-first-run="joined"]')!.textContent).toBe(t('first_run.join.done', { name: t('first_run.join.main_fallback') }));
        expect(q('[data-first-run="code"]')).toBeNull();
        expect(q('[data-first-run="cell"]')).toBeNull();
        expect(calls).toHaveLength(0);
    });
});

describe('auth.js resolveEntry for a joined computer', () => {
    type AuthObj = { init(): void; resolveEntry(): Promise<void> };
    let A: AuthObj;
    let mountSpy: ReturnType<typeof vi.fn>;
    beforeEach(() => {
        document.body.innerHTML = '<div id="auth-screen" class="screen active"></div><div id="first-run-screen" class="screen"></div>';
        mountSpy = vi.fn();
        const w = window as unknown as Record<string, unknown>;
        w.CarnivoreFirstRun = { probe: async () => 'joined', mount: mountSpy, unmount: vi.fn() };
        new Function('window', 'document', readFileSync('../client/js/auth.js', 'utf8'))(window, document);
        A = w.Auth as AuthObj;
        A.init();
        vi.spyOn(A as unknown as { acceptLogin(r: unknown): void }, 'acceptLogin').mockImplementation(() => undefined);
    });
    afterEach(() => {
        delete (window as unknown as Record<string, unknown>).CarnivoreFirstRun;
    });

    test('with the desktop bridge and a login, the app takes over and nothing mounts', async () => {
        (window as unknown as Record<string, unknown>).carnivoreDesktop = { localLogin: async () => ({ access_token: 'a' }) };
        const authenticated = vi.fn();
        window.addEventListener('authenticated', authenticated, { once: true });
        await A.resolveEntry();
        expect(authenticated).toHaveBeenCalledTimes(1);
        expect(mountSpy).not.toHaveBeenCalled();
    });

    test('without the bridge the joined panel mounts', async () => {
        await A.resolveEntry();
        expect(mountSpy).toHaveBeenCalledWith('first-run-screen', 'joined');
    });

    test('a bridge that answers null leaves the joined panel to show', async () => {
        (window as unknown as Record<string, unknown>).carnivoreDesktop = { localLogin: async () => null };
        await A.resolveEntry();
        expect(mountSpy).toHaveBeenCalledWith('first-run-screen', 'joined');
    });
});
