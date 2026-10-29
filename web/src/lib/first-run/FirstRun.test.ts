/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import FirstRun from './FirstRun.svelte';
import { decideEntry, navigate, readHealth } from './first-run-api';
import { setLocale, t } from '../i18n/index.svelte';

setLocale('en');

const QR = 'data:image/svg+xml;base64,PHN2Zy8+';
const SECRET = 'JBSWY3DPEHPK3PXPJBSWY3DP';
const json = (status: number, body: unknown = {}) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const enrolled = () => json(200, { otpauth_uri: 'otpauth://totp/x', secret: SECRET, qr_image: QR, issuer: 'Carnivore', account: 'x' });
const tokens = () => json(200, { access_token: 'a', refresh_token: 'r' });
const profilesList = () => json(200, { revision: 1, profiles: [{ id: 'claude-default', harness: 'claude', installed: true }] });
const health = (restart: boolean | null) => json(200, { status: 'healthy', bind: { restart_required: restart } });

type Handler = () => Response | Error | Promise<Response>;
let calls: Array<{ url: string; init?: RequestInit }> = [];
let routes: Record<string, Handler | Handler[]> = {};
const auth = { showLoginForm: vi.fn(), acceptLogin: vi.fn(), finishFirstRun: vi.fn() };
const mounted: ReturnType<typeof mount>[] = [];

/** Install a fetch mock: a route holds one handler, or a queue whose last entry repeats. */
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
const click = async (sel: string) => {
    (q(sel) as HTMLElement).click();
    await settle();
};
async function render(entry: 'first-run' | 'remote' = 'first-run') {
    mounted.push(mount(FirstRun, { target: document.body, props: { entry } }));
    await vi.advanceTimersByTimeAsync(0);
    await settle();
    if (entry === 'first-run' && q('[data-first-run="choose-new"]')) await click('[data-first-run="choose-new"]');
}
async function typeCode(value: string) {
    const field = q('[data-first-run="code"]') as HTMLInputElement;
    field.value = value;
    field.dispatchEvent(new Event('input', { bubbles: true }));
    await vi.advanceTimersByTimeAsync(0);
    await settle();
}
async function reachDone(healthQueue: Handler[]) {
    install({ '/api/v1/auth/enrollment': enrolled, '/api/v1/auth/verify': tokens, '/health': healthQueue, '/api/v1/launch-profiles': profilesList });
    await render();
    await click('[data-first-run="next"]');
    await typeCode('123456');
    await click('[data-first-run="agent-continue"]');
    await click('[data-first-run="profiles-continue"]');
}

beforeEach(() => {
    vi.useFakeTimers();
    calls = [];
    Object.values(auth).forEach((f) => f.mockReset());
    (window as unknown as { Auth: unknown }).Auth = auth;
});
afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe('decideEntry', () => {
    const cases: Array<[string, Handler, string]> = [
        ['unpaired and local', () => json(200, { paired: false, local: true }), 'first-run'],
        ['unpaired and remote', () => json(200, { paired: false, local: false }), 'remote'],
        ['paired and local', () => json(200, { paired: true, local: true }), 'totp'],
        ['paired null', () => json(200, { paired: null, local: true }), 'totp'],
        ['401', () => json(401), 'totp'],
        ['403', () => json(403), 'totp'],
        ['404', () => json(404), 'totp'],
        ['429', () => json(429), 'totp'],
        ['500', () => json(500), 'totp'],
        ['network rejection', () => new Error('down'), 'totp'],
        ['bad JSON', () => new Response('<html>', { status: 200 }), 'totp'],
        ['negative control: paired is the string "false"', () => json(200, { paired: 'false', local: true }), 'totp'],
        ['local is a string', () => json(200, { paired: false, local: 'true' }), 'totp'],
    ];
    test.each(cases)('%s', async (_name, handler, want) => {
        install({ '/api/v1/auth/enrollment/status': handler });
        expect(await decideEntry()).toBe(want);
    });

    test('a hung probe gives up at 3 s and shows the totp form', async () => {
        vi.stubGlobal('fetch', vi.fn((_u: string, init: RequestInit) => new Promise((_res, rej) => init.signal!.addEventListener('abort', () => rej(new Error('abort'))))));
        const pending = decideEntry();
        await vi.advanceTimersByTimeAsync(2999);
        let settled = false;
        void pending.then(() => (settled = true));
        await vi.advanceTimersByTimeAsync(0);
        expect(settled).toBe(false);
        await vi.advanceTimersByTimeAsync(2);
        expect(await pending).toBe('totp');
    });

    test('the status probe and the verify post carry no Authorization header', async () => {
        install({ '/api/v1/auth/enrollment/status': () => json(200, { paired: false, local: true }), '/api/v1/auth/enrollment': enrolled, '/api/v1/auth/verify': tokens, '/health': () => health(false) });
        await decideEntry();
        await render();
        await click('[data-first-run="next"]');
        await typeCode('123456');
        expect(count('/api/v1/auth/verify')).toBe(1);
        for (const c of calls) expect(JSON.stringify(c.init?.headers ?? {}).toLowerCase()).not.toContain('authorization');
    });
});

describe('scan', () => {
    test('renders the data: image, the grouped key and copies the raw key', async () => {
        install({ '/api/v1/auth/enrollment': enrolled });
        const writeText = vi.fn(async () => undefined);
        vi.stubGlobal('navigator', { clipboard: { writeText } });
        await render();
        const img = q('img.first-run__qr') as HTMLImageElement;
        expect(img.getAttribute('src')).toBe(QR);
        expect(img.getAttribute('alt')).toBe(t('first_run.qr_alt'));
        expect(q('[data-first-run="key"]')).toBeNull();
        await click('[data-first-run="reveal"]');
        expect(q('[data-first-run="key"]')!.textContent).toBe('JBSW Y3DP EHPK 3PXP JBSW Y3DP');
        await click('[data-first-run="copy"]');
        expect(writeText).toHaveBeenCalledWith(SECRET);
        expect(q('[data-first-run="copy"]')!.textContent!.trim()).toBe(t('first_run.key.copied'));
    });

    test('a non-svg qr_image is never placed in the page', async () => {
        install({ '/api/v1/auth/enrollment': () => json(200, { secret: SECRET, qr_image: 'javascript:alert(1)' }) });
        await render();
        expect(q('img.first-run__qr')).toBeNull();
        expect(q('[data-first-run-error="load"]')).not.toBeNull();
    });

    test('403 shows remote', async () => {
        install({ '/api/v1/auth/enrollment': () => json(403, { detail: { reason: 'enrollment_local_only' } }) });
        await render();
        expect(q('main')!.getAttribute('data-first-run')).toBe('remote');
    });

    test('409 already_paired goes to the login form', async () => {
        install({ '/api/v1/auth/enrollment': () => json(409, { detail: { reason: 'already_paired' } }) });
        await render();
        expect(auth.showLoginForm).toHaveBeenCalledTimes(1);
    });

    test.each([
        ['409 restart_pending', 409, 'restart_pending', 'first_run.error.restart_pending'],
        ['503 config_unreadable', 503, 'config_unreadable', 'first_run.error.config'],
        ['503 totp_not_configured', 503, 'totp_not_configured', 'first_run.error.config'],
    ])('%s shows its words, no login form, no retry, no second fetch in 30 s', async (_n, status, reason, key) => {
        install({ '/api/v1/auth/enrollment': () => json(status, { detail: { reason } }) });
        await render();
        expect(q('[data-first-run-error]')!.textContent).toBe(t(key));
        expect(q('[data-first-run="retry"]')).toBeNull();
        await vi.advanceTimersByTimeAsync(30_000);
        expect(count('/api/v1/auth/enrollment')).toBe(1);
        expect(auth.showLoginForm).not.toHaveBeenCalled();
    });

    test.each([['500', () => json(500)], ['429', () => json(429)], ['other 409', () => json(409, { detail: { reason: 'x' } })], ['network', () => new Error('x')], ['bad json', () => new Response('<', { status: 200 })]])(
        '%s shows load with one retry per click',
        async (_n, handler) => {
            install({ '/api/v1/auth/enrollment': handler });
            await render();
            expect(q('[data-first-run-error]')!.textContent).toBe(t('first_run.error.load'));
            await vi.advanceTimersByTimeAsync(30_000);
            expect(count('/api/v1/auth/enrollment')).toBe(1);
            await click('[data-first-run="retry"]');
            expect(count('/api/v1/auth/enrollment')).toBe(2);
        },
    );

    test('remote never requests the enrollment', async () => {
        install({});
        await render('remote');
        expect(q('main')!.getAttribute('data-first-run')).toBe('remote');
        expect(calls).toEqual([]);
    });
});

describe('confirm', () => {
    test.each([
        ['401 string', () => json(401, { detail: 'Invalid TOTP code' }), 'first_run.error.invalid'],
        ['401 code_reused', () => json(401, { detail: { success: false, reason: 'code_reused' } }), 'first_run.error.reused'],
        ['429', () => json(429, { error: 'slow' }), 'first_run.error.rate_limited'],
        ['500', () => json(500), 'first_run.error.network'],
    ])('%s', async (_n, handler, key) => {
        install({ '/api/v1/auth/enrollment': enrolled, '/api/v1/auth/verify': handler });
        await render();
        await click('[data-first-run="next"]');
        await typeCode('654321');
        expect(q('[data-first-run-error]')!.textContent).toBe(t(key));
        expect((q('[data-first-run="code"]') as HTMLInputElement).value).toBe('');
        expect(auth.acceptLogin).not.toHaveBeenCalled();
    });

    test('five digits do not submit, the sixth does, success calls acceptLogin once and not finishFirstRun', async () => {
        install({ '/api/v1/auth/enrollment': enrolled, '/api/v1/auth/verify': tokens, '/health': () => health(true) });
        await render();
        await click('[data-first-run="next"]');
        await typeCode('12345');
        expect(count('/api/v1/auth/verify')).toBe(0);
        await typeCode('123456');
        expect(count('/api/v1/auth/verify')).toBe(1);
        expect(auth.acceptLogin).toHaveBeenCalledTimes(1);
        expect(auth.acceptLogin).toHaveBeenCalledWith({ access_token: 'a', refresh_token: 'r' });
        expect(auth.finishFirstRun).not.toHaveBeenCalled();
    });
});

describe('readHealth', () => {
    test('asks exactly /health, no Authorization header', async () => {
        install({ '/health': () => health(false) });
        expect(await readHealth()).toEqual({ ok: true, restartRequired: false });
        expect(calls.map((c) => c.url)).toEqual(['/health']);
        expect(JSON.stringify(calls[0]!.init?.headers ?? {}).toLowerCase()).not.toContain('authorization');
    });
});

describe('the agent row between the code and done (#2576)', () => {
    test('a good code shows the agent row, reads the self-check, and only continue starts the health read', async () => {
        install({
            '/api/v1/auth/enrollment': enrolled,
            '/api/v1/auth/verify': tokens,
            '/api/v1/self-check': () => json(200, { status: 'FAIL', checks: [{ name: 'claude_cli', status: 'FAIL', summary: 'claude not found', findings: [] }], agents: { codex: { found: false, path: null } } }),
            '/api/v1/launch-profiles': profilesList,
            '/health': () => health(false),
        });
        await render();
        await click('[data-first-run="next"]');
        await typeCode('123456');
        expect(q('[data-first-run="claude"]')!.textContent).toContain(t('first_run.agent.claude_missing'));
        expect(q('[data-first-run="paired"]')).toBeNull();
        expect(count('/health')).toBe(0);
        expect(auth.finishFirstRun).not.toHaveBeenCalled();
        await click('[data-first-run="agent-continue"]');
        expect(q('[data-first-run="profiles-continue"]')).not.toBeNull();
        expect(count('/health')).toBe(0);
        await click('[data-first-run="profiles-continue"]');
        expect(auth.finishFirstRun).toHaveBeenCalledTimes(1);
    });
});

describe('done', () => {
    let reload: ReturnType<typeof vi.spyOn>;
    beforeEach(() => {
        reload = vi.spyOn(navigate, 'reload').mockImplementation(() => undefined);
    });
    const authenticated = vi.fn();
    beforeEach(() => {
        authenticated.mockReset();
        window.addEventListener('authenticated', authenticated);
    });
    afterEach(() => window.removeEventListener('authenticated', authenticated));

    test('(a) restart_required false finishes at once', async () => {
        await reachDone([() => health(false)]);
        expect(auth.finishFirstRun).toHaveBeenCalledTimes(1);
        expect(q('[data-first-run="restarting"]')).toBeNull();
    });

    test('(d) restart_required null counts as false', async () => {
        await reachDone([() => health(null)]);
        expect(auth.finishFirstRun).toHaveBeenCalledTimes(1);
    });

    test('(b) true, two failures, then false reloads once and never finishes', async () => {
        await reachDone([() => health(true), () => new Error('down'), () => new Error('down'), () => health(false)]);
        expect(q('[data-first-run="restarting"]')!.textContent).toBe(t('first_run.done.restarting'));
        await vi.advanceTimersByTimeAsync(5000);
        await settle();
        expect(reload).toHaveBeenCalledTimes(1);
        expect(auth.finishFirstRun).not.toHaveBeenCalled();
    });

    test('true then false without ever seeing the server down finishes without a reload', async () => {
        await reachDone([() => health(true), () => health(false)]);
        await vi.advanceTimersByTimeAsync(1000);
        expect(auth.finishFirstRun).toHaveBeenCalledTimes(1);
        expect(reload).not.toHaveBeenCalled();
    });

    test('(c) true for 15 s offers continue, which alone finishes', async () => {
        await reachDone([() => health(true)]);
        await vi.advanceTimersByTimeAsync(14_000);
        await settle();
        expect(q('[data-first-run="continue"]')).toBeNull();
        await vi.advanceTimersByTimeAsync(1500);
        await settle();
        expect(q('[data-first-run="manual"]')!.textContent).toBe(t('first_run.done.manual'));
        expect(auth.finishFirstRun).not.toHaveBeenCalled();
        await click('[data-first-run="continue"]');
        expect(auth.finishFirstRun).toHaveBeenCalledTimes(1);
    });

    test('(e) fail closed: the first read rejects, nothing signs in, a later good read reloads', async () => {
        await reachDone([() => new Error('down'), () => health(false)]);
        expect(auth.finishFirstRun).not.toHaveBeenCalled();
        expect(authenticated).not.toHaveBeenCalled();
        expect(q('[data-first-run="restarting"]')!.textContent).toBe(t('first_run.done.restarting'));
        await vi.advanceTimersByTimeAsync(1000);
        await settle();
        expect(reload).toHaveBeenCalledTimes(1);
        expect(auth.finishFirstRun).not.toHaveBeenCalled();
    });

    test('(f) an HTML 200 and a 200 with no bind both count as down', async () => {
        await reachDone([() => new Response('<html>', { status: 200 }), () => json(200, { status: 'healthy' }), () => health(false)]);
        expect(auth.finishFirstRun).not.toHaveBeenCalled();
        await vi.advanceTimersByTimeAsync(1000);
        expect(reload).not.toHaveBeenCalled();
        await vi.advanceTimersByTimeAsync(1000);
        await settle();
        expect(reload).toHaveBeenCalledTimes(1);
    });

    test('(g) polling stops at 10 minutes and continue stays', async () => {
        await reachDone([() => health(true)]);
        await vi.advanceTimersByTimeAsync(600_000 + 6000);
        await settle();
        const after = count('/health');
        await vi.advanceTimersByTimeAsync(120_000);
        expect(count('/health')).toBe(after);
        expect(q('[data-first-run="continue"]')).not.toBeNull();
        expect(auth.finishFirstRun).not.toHaveBeenCalled();
        expect(authenticated).not.toHaveBeenCalled();
    });
});

describe('boot.ts mount guard', () => {
    test('same entry keeps the instance, a different entry replaces it, unmount then mount is fresh', async () => {
        await import('./boot');
        const surface = (window as unknown as { CarnivoreFirstRun: { mount(id: string, e: string): void; unmount(): void } }).CarnivoreFirstRun;
        const host = document.createElement('div');
        host.id = 'first-run-screen';
        document.body.append(host);
        install({ '/api/v1/auth/enrollment': enrolled });
        surface.mount('first-run-screen', 'first-run');
        await vi.advanceTimersByTimeAsync(0);
        await settle();
        await click('[data-first-run="choose-new"]');
        await click('[data-first-run="next"]');
        await typeCode('123');
        surface.mount('first-run-screen', 'first-run');
        await settle();
        expect(count('/api/v1/auth/enrollment')).toBe(1);
        expect((q('[data-first-run="code"]') as HTMLInputElement).value).toBe('123');
        surface.mount('first-run-screen', 'remote');
        await settle();
        expect(q('main')!.getAttribute('data-first-run')).toBe('remote');
        surface.unmount();
        surface.mount('first-run-screen', 'first-run');
        await vi.advanceTimersByTimeAsync(0);
        await settle();
        await click('[data-first-run="choose-new"]');
        expect(count('/api/v1/auth/enrollment')).toBe(2);
        expect(q('[data-first-run="code"]')).toBeNull();
        surface.unmount();
    });
});

describe('auth.js resolveEntry', () => {
    type AuthObj = { init(): void; resolveEntry(): Promise<void>; showLoginForm(): void; _entryGen: number; constructor: new () => AuthObj };
    let A: AuthObj;
    const pending: Array<(v: string) => void> = [];
    let mountSpy: ReturnType<typeof vi.fn>;

    function loadAuth(): AuthObj {
        const w = window as unknown as Record<string, unknown>;
        new Function('window', 'document', readFileSync('../client/js/auth.js', 'utf8'))(window, document);
        return w.Auth as AuthObj;
    }
    function dom(): void {
        document.body.innerHTML = '<div id="auth-screen" class="screen"></div><div id="first-run-screen" class="screen"></div>';
    }
    beforeEach(() => {
        dom();
        pending.length = 0;
        mountSpy = vi.fn();
        const w = window as unknown as Record<string, unknown>;
        w.CarnivoreFirstRun = { probe: () => new Promise<string>((res) => pending.push(res)), mount: mountSpy, unmount: vi.fn() };
        A = loadAuth();
        A.init();
    });
    afterEach(() => {
        delete (window as unknown as Record<string, unknown>).CarnivoreFirstRun;
    });
    function showAuth(): Promise<void> {
        document.querySelectorAll('.screen').forEach((s) => s.classList.remove('active'));
        document.getElementById('auth-screen')!.classList.add('active');
        return A.resolveEntry();
    }
    const form = () => document.querySelector('#auth-screen .auth-container') as HTMLElement;
    const active = (id: string) => document.getElementById(id)!.classList.contains('active');

    test('A1: the form is hidden while the probe is pending; first-run mounts once', async () => {
        const p = showAuth();
        expect(form().classList.contains('hidden')).toBe(true);
        pending[0]!('first-run');
        await p;
        expect(active('auth-screen')).toBe(false);
        expect(active('first-run-screen')).toBe(true);
        expect(mountSpy).toHaveBeenCalledTimes(1);
        expect(mountSpy).toHaveBeenCalledWith('first-run-screen', 'first-run');
        expect(form().classList.contains('hidden')).toBe(true);
    });

    test('A2: an older probe resolving totp is stale; the newer first-run wins', async () => {
        const first = showAuth();
        const second = showAuth();
        pending[0]!('totp');
        await first;
        expect(form().classList.contains('hidden')).toBe(true);
        pending[1]!('first-run');
        await second;
        expect(active('first-run-screen')).toBe(true);
        expect(form().classList.contains('hidden')).toBe(true);
    });

    test('A3: showing auth again re-shows the panel without a second mount', async () => {
        let p = showAuth();
        pending[0]!('first-run');
        await p;
        p = showAuth();
        expect(active('first-run-screen')).toBe(false);
        pending[1]!('first-run');
        await p;
        expect(active('first-run-screen')).toBe(true);
        expect(mountSpy).toHaveBeenCalledTimes(1);
    });

    test('A4: the app navigated away before the probe resolved, nothing mounts', async () => {
        const p = showAuth();
        document.getElementById('auth-screen')!.classList.remove('active');
        pending[0]!('first-run');
        await p;
        expect(mountSpy).not.toHaveBeenCalled();
        expect(active('first-run-screen')).toBe(false);
    });

    test('A5: a missing bundle and a throwing probe both show the form with the field focused', async () => {
        delete (window as unknown as Record<string, unknown>).CarnivoreFirstRun;
        await showAuth();
        expect(form().classList.contains('hidden')).toBe(false);
        expect(document.activeElement?.id).toBe('totp-input');
        (document.activeElement as HTMLElement).blur();
        (window as unknown as Record<string, unknown>).CarnivoreFirstRun = { probe: () => Promise.reject(new Error('x')), mount: mountSpy, unmount: vi.fn() };
        await showAuth();
        expect(form().classList.contains('hidden')).toBe(false);
        expect(document.activeElement?.id).toBe('totp-input');
        expect(mountSpy).not.toHaveBeenCalled();
    });

    test('A7: a fresh Auth starts the counter at 0 and every entry renders', async () => {
        dom();
        const fresh = new A.constructor();
        expect(fresh._entryGen).toBe(0);
        A = fresh;
        A.init();
        let p = showAuth();
        pending.shift()!('totp');
        await p;
        expect(form().classList.contains('hidden')).toBe(false);
        p = showAuth();
        pending.shift()!('first-run');
        await p;
        expect(active('first-run-screen')).toBe(true);
        const older = showAuth();
        const newer = showAuth();
        pending.shift()!('first-run');
        await older;
        expect(active('first-run-screen')).toBe(false);
        pending.shift()!('totp');
        await newer;
        expect(form().classList.contains('hidden')).toBe(false);
    });

    test('A6: App.showAuth calls resolveEntry right after activating the auth screen', () => {
        const src = readFileSync('../client/js/app.js', 'utf8');
        const body = src.slice(src.indexOf('    showAuth() {'));
        const activate = body.indexOf("getElementById('auth-screen').classList.add('active');");
        const resolve = body.indexOf('window.Auth.resolveEntry();');
        expect(activate).toBeGreaterThan(0);
        expect(resolve).toBeGreaterThan(activate);
        expect(resolve - activate).toBeLessThan(120);
    });
});
