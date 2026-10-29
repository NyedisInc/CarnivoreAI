/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import PhoneLinkPanel from './PhoneLinkPanel.svelte';
import { setLocale } from '../i18n/index.svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import type { Fetcher } from './phone-link/api';
import { refreshAccount } from '../carnivore-account/account-store.svelte';
import { registerSignInOpener, cancelPendingAccount } from '../carnivore-account/funnel';

setLocale('en');

const STATUS = {
    enabled: true, running: true, tunnel: 'connected', hostname: 'h.link.carnivore.ai', devices: 1, window_open: false, pairing: { state: 'none', device: null }, error: '',
    cert: { issuer: '(STAGING) Test', not_after: '2026-12-29T10:00:00+00:00', environment: 'staging' },
};
const DEVICE = {
    id: 'd1', label: 'iphone', kind: 'app', created_at: 1, last_seen: 1790000000,
    push: [{ service: 'web.push.apple.com', last_result: { status: 201, at: '2026-09-30T01:02:03+00:00' } }],
};

const mounted: ReturnType<typeof mount>[] = [];
async function account(signedIn: boolean): Promise<void> {
    (globalThis as any).API = { getCatalogSession: async () => ({ signed_in: signedIn, login: 'a@b.c', provider: 'email' }) };
    await refreshAccount();
}

afterEach(async () => {
    cancelPendingAccount();
    registerSignInOpener(null);
    await account(true);
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
});

const live: { pairing: { state: string; device: unknown; locked?: boolean }; qrSecondsLeft: number } = { pairing: { state: 'none', device: null }, qrSecondsLeft: 120 };

async function render(status: Omit<typeof STATUS, 'cert' | 'pairing'> & { cert: typeof STATUS.cert | null } = STATUS, devices: (Omit<typeof DEVICE, 'last_seen'> & { last_seen: number | null })[] = [DEVICE]) {
    const calls: string[] = [];
    live.pairing = { state: 'none', device: null };
    const fetcher = (async (path: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? 'GET'} ${path}`);
        const now = Date.now() / 1000;
        if (path === '/phone-link/pairing-window' && init?.method === 'POST') {
            live.pairing = { state: 'open', device: null };
            return { url: 'https://h/pair#s', pair_url: 'https://h/pair', code: 'ABCD2345', expires_at: now + 600, qr: 'data:image/png;base64,AA==', qr_expires_at: now + live.qrSecondsLeft, qr_rotate_seconds: 60 };
        }
        if (path === '/phone-link/pairing-window/acknowledge') return { acknowledged: true };
        if (path === '/phone-link/pairing-window/qr') return { url: 'https://h/pair#t', qr: 'data:image/png;base64,BB==', qr_expires_at: now + 120 };
        if (path === '/phone-link/pairing-window') return { closed: true };
        if (path === '/phone-link/devices') return init?.method === 'DELETE' ? { revoked: true } : devices;
        if (path === '/phone-link/devices/d1') return { revoked: true };
        if (path === '/phone-link') return init?.method === 'PUT' ? { ...status, enabled: false } : { ...status, window_open: live.pairing.state === 'open', pairing: live.pairing };
        return {};
    }) as unknown as Fetcher;
    mounted.push(mount(PhoneLinkPanel, { target: document.body, props: { fetcher } }));
    for (let i = 0; i < 4; i++) await tick();
    flushSync();
    return calls;
}

const settle = async () => {
    await new Promise((resolve) => setTimeout(resolve, 10));
    for (let i = 0; i < 6; i++) await tick();
    flushSync();
};

const q = (sel: string) => document.querySelector(sel);

describe('PhoneLinkPanel', () => {
    test('shows the certificate issuer, expiry and environment, the tunnel, and the device with last seen and push', async () => {
        await render();
        expect(q('[data-pl="cert"]')?.textContent).toContain('(STAGING) Test');
        expect(q('[data-pl="cert"]')?.textContent).toContain('2026-12-29');
        expect(q('[data-pl="cert"]')?.textContent).toContain('staging');
        expect(q('[data-pl="tunnel"]')?.textContent?.trim()).toBe('connected');
        const row = q('[data-pl-device="d1"]')?.textContent ?? '';
        expect(row).toContain('iphone');
        expect(row).toContain('last seen 2026-');
        expect(row).toContain('last push 201');
    });

    test('pair a mobile device shows the QR and a countdown, and keeps the code behind "no camera? show a code"', async () => {
        const calls = await render();
        (q('[data-pl="pair"]') as HTMLButtonElement).click();
        await settle();
        expect(calls).toContain('POST /phone-link/pairing-window');
        expect((q('[data-pl="qr"]') as HTMLImageElement).src).toContain('data:image/png;base64,AA');
        expect(q('[data-pl="countdown"]')?.textContent).toMatch(/closes in (9|10):\d\d/);
        expect(q('[data-pl="code"]')).toBeNull();
        (q('[data-pl="show-code"]') as HTMLButtonElement).click();
        flushSync();
        expect(q('[data-pl="code"]')?.textContent).toBe('ABCD2345');
        expect(q('[data-pl="type-at"]')?.textContent).toContain('https://h/pair');
    });

    test('a fresh QR is not fetched while more than a minute of the current one is left', async () => {
        live.qrSecondsLeft = 120;
        const calls = await render();
        (q('[data-pl="pair"]') as HTMLButtonElement).click();
        await settle();
        expect(calls).not.toContain('POST /phone-link/pairing-window/qr');
        expect((q('[data-pl="qr"]') as HTMLImageElement).src).toContain('data:image/png;base64,AA');
    });

    test('the QR is swapped for a fresh one when under a minute of it is left', async () => {
        live.qrSecondsLeft = 30;
        try {
            const calls = await render();
            (q('[data-pl="pair"]') as HTMLButtonElement).click();
            await settle();
            expect(calls).toContain('POST /phone-link/pairing-window/qr');
            expect((q('[data-pl="qr"]') as HTMLImageElement).src).toContain('data:image/png;base64,BB');
        } finally {
            live.qrSecondsLeft = 120;
        }
    });

    test('a pagehide (the phone switching tabs to type the code) does not close the open window (#1322)', async () => {
        const calls = await render();
        (q('[data-pl="pair"]') as HTMLButtonElement).click();
        await settle();
        window.dispatchEvent(new Event('pagehide'));
        await settle();
        expect(calls).not.toContain('DELETE /phone-link/pairing-window');
    });

    test('cancel closes the window on the server', async () => {
        const calls = await render();
        (q('[data-pl="pair"]') as HTMLButtonElement).click();
        await settle();
        (q('[data-pl="close"]') as HTMLButtonElement).click();
        await settle();
        expect(calls).toContain('DELETE /phone-link/pairing-window');
        expect(q('[data-pl="window"]')).toBeNull();
    });

    test('a scan shows "waiting for its code", then "paired" with a revoke of that device', async () => {
        vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
        try {
            const calls = await render();
            (q('[data-pl="pair"]') as HTMLButtonElement).click();
            await vi.advanceTimersByTimeAsync(10);
            live.pairing = { state: 'pending', device: null };
            await vi.advanceTimersByTimeAsync(3000);
            await settle();
            expect(q('[data-pl="scanned"]')?.textContent).toBe('phone scanned, waiting for its code');
            expect(q('[data-pl="qr"]')).toBeNull();
            live.pairing = { state: 'claimed', device: { id: 'd1', label: 'iphone', kind: 'browser', created_at: 1 } };
            await vi.advanceTimersByTimeAsync(3000);
            await settle();
            expect(q('[data-pl="paired"]')?.textContent).toBe('paired: iphone');
            (q('[data-pl="paired-revoke"]') as HTMLButtonElement).click();
            await vi.advanceTimersByTimeAsync(10);
            await settle();
            expect(calls).toContain('DELETE /phone-link/devices/d1');
            expect(calls).toContain('DELETE /phone-link/pairing-window');
        } finally {
            vi.useRealTimers();
        }
    });

    test('a scan that never finishes gets a fresh QR', async () => {
        vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
        try {
            const calls = await render();
            (q('[data-pl="pair"]') as HTMLButtonElement).click();
            await vi.advanceTimersByTimeAsync(10);
            live.pairing = { state: 'pending', device: null };
            await vi.advanceTimersByTimeAsync(3000);
            live.pairing = { state: 'none', device: null };
            await vi.advanceTimersByTimeAsync(3000);
            await settle();
            expect(calls.filter((c) => c === 'POST /phone-link/pairing-window').length).toBe(2);
            expect(q('[data-pl="qr"]')).not.toBeNull();
            expect(q('[data-pl="note"]')?.textContent).toContain('did not finish');
        } finally {
            vi.useRealTimers();
        }
    });

    test('a pairing that died from wrong codes is never reopened by the panel; try again is the owner\'s click', async () => {
        vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
        try {
            const calls = await render();
            (q('[data-pl="pair"]') as HTMLButtonElement).click();
            await vi.advanceTimersByTimeAsync(10);
            live.pairing = { state: 'pending', device: null };
            await vi.advanceTimersByTimeAsync(3000);
            live.pairing = { state: 'failed', device: null, locked: true };
            await vi.advanceTimersByTimeAsync(9000);
            await settle();
            expect(calls.filter((c) => c === 'POST /phone-link/pairing-window').length).toBe(1);
            expect(q('[data-pl="qr"]')).toBeNull();
            expect(q('[data-pl="failed"]')?.textContent).toContain('paused until you acknowledge');
            (q('[data-pl="retry"]') as HTMLButtonElement).click();
            await vi.advanceTimersByTimeAsync(10);
            await settle();
            expect(calls.indexOf('POST /phone-link/pairing-window/acknowledge')).toBeGreaterThan(-1);
            expect(calls.filter((c) => c === 'POST /phone-link/pairing-window').length).toBe(2);
            expect(q('[data-pl="qr"]')).not.toBeNull();
        } finally {
            vi.useRealTimers();
        }
    });

    test('pair a phone is disabled while the link is off, and a device with no push says so', async () => {
        await render({ ...STATUS, enabled: false, cert: null }, [{ ...DEVICE, last_seen: null, push: [] }]);
        expect((q('[data-pl="pair"]') as HTMLButtonElement).disabled).toBe(true);
        expect(q('[data-pl="cert"]')?.textContent).toContain('none yet');
        expect(q('[data-pl-device="d1"]')?.textContent).toContain('not seen yet');
        expect(q('[data-pl-device="d1"]')?.textContent).toContain('no alerts on');
    });

    test('served over the link (403) the panel shows nothing, not an error', async () => {
        const fetcher = (async () => {
            throw new ApiError('not available over the link', 403, null, { detail: 'not available over the link' });
        }) as unknown as Fetcher;
        mounted.push(mount(PhoneLinkPanel, { target: document.body, props: { fetcher } }));
        for (let i = 0; i < 4; i++) await tick();
        flushSync();
        expect(q('[data-pl="panel"]')).toBeNull();
        expect(q('[data-pl="problem"]')).toBeNull();
    });

    test('an account_required 403 is the sign-in wall, not the link: the panel is not blanked', async () => {
        const fetcher = (async () => {
            throw new ApiError('sign in', 403, 'account_required', { code: 'account_required', feature: 'phone_link' });
        }) as unknown as Fetcher;
        mounted.push(mount(PhoneLinkPanel, { target: document.body, props: { fetcher } }));
        for (let i = 0; i < 4; i++) await tick();
        flushSync();
        expect(q('[data-pl="problem"]')).toBeNull();
        expect(document.body.textContent ?? '').not.toBe('');
    });

    test('revoke sends DELETE for that device', async () => {
        const calls = await render();
        (q('[data-pl="revoke"]') as HTMLButtonElement).click();
        await new Promise((resolve) => setTimeout(resolve, 10));
        expect(calls).toContain('DELETE /phone-link/devices/d1');
    });

    test('signed out with mobile sync off: a sign-in panel replaces the switch and pair; its button asks for the account for phone_link', async () => {
        await account(false);
        const opened = vi.fn();
        registerSignInOpener(opened);
        await render({ ...STATUS, enabled: false, cert: null });
        expect(q('[data-pl="signin"]')).not.toBeNull();
        expect(q('[data-pl="switch"]')).toBeNull();
        expect(q('[data-pl="pair"]')).toBeNull();
        expect(q('[data-pl="signin"]')?.textContent).toContain('sign in with your free carnivore account');
        expect(q('[data-pl-device="d1"]')).not.toBeNull();
        (q('[data-pl="signin-btn"]') as HTMLButtonElement).click();
        await new Promise((resolve) => setTimeout(resolve, 10));
        expect(opened).toHaveBeenCalledWith({ feature: 'phone_link', src: 'phone_link' });
    });

    test('signed out with mobile sync already on: normal state, the paired list and disable, plus a later sign-in note', async () => {
        await account(false);
        const calls = await render();
        expect(q('[data-pl="signin"]')).toBeNull();
        expect(q('[data-pl="switch"]')).not.toBeNull();
        expect(q('[data-pl="grace"]')).not.toBeNull();
        expect(q('[data-pl-device="d1"]')).not.toBeNull();
        (q('[data-pl="switch"]') as HTMLElement).click();
        await new Promise((resolve) => setTimeout(resolve, 10));
        expect(calls).toContain('PUT /phone-link');
    });
});
