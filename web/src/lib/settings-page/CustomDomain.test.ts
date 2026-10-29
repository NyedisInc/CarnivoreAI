/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import CustomDomain from './CustomDomain.svelte';
import { setLocale } from '../i18n/index.svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import type { CustomDomain as View, Fetcher } from './phone-link/custom-domain';
import { checkMessage, errorKey, ledOf, refusalKey, stateKey } from './phone-link/custom-domain';

setLocale('en');

const NONE: View = {
    domain: null, domain_display: null, state: 'none', target: null, dead_reason: null,
    lockout_until: null, check: null, cert: null, error: null, updated_at: 0,
};
const PENDING: View = {
    ...NONE, domain: 'sync.example.com', domain_display: 'sync.example.com', state: 'pending',
    target: 'dev.d.link.carnivore.ai', check: { result: 'flattened_or_proxied', seen: null, checked_at: 1 },
};

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
});

async function render(initial: View, onPut?: (body: { domain: string }) => View | ApiError) {
    const calls: string[] = [];
    let current = initial;
    const fetcher = (async (path: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? 'GET'} ${path}`);
        if (init?.method === 'PUT') {
            const out = onPut!(JSON.parse(String(init.body)));
            if (out instanceof ApiError) throw out;
            return (current = out);
        }
        if (init?.method === 'DELETE') return (current = { ...NONE, state: 'dead', dead_reason: 'removed', domain: current.domain });
        return current;
    }) as unknown as Fetcher;
    mounted.push(mount(CustomDomain, { target: document.body, props: { fetcher } }));
    for (let i = 0; i < 4; i++) await tick();
    flushSync();
    return calls;
}
const q = (sel: string) => document.querySelector(sel);
const settle = async () => {
    await new Promise((r) => setTimeout(r, 5));
    for (let i = 0; i < 4; i++) await tick();
    flushSync();
};

describe('CustomDomain', () => {
    test('with no name it shows the field and submit sends the typed name', async () => {
        let sent = '';
        const calls = await render(NONE, (body) => ((sent = body.domain), PENDING));
        const input = q('[data-cd="input"]') as HTMLInputElement;
        const submit = q('[data-cd="submit"]') as HTMLButtonElement;
        expect(submit.disabled).toBe(true);
        input.value = 'sync.example.com';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();
        submit.click();
        await settle();
        expect(sent).toBe('sync.example.com');
        expect(calls).toContain('PUT /phone-link/custom-domain');
        expect(q('[data-cd="domain"]')?.textContent).toBe('sync.example.com');
    });

    test('a pending name shows the one record in three copyable cells and the named problem in plain words', async () => {
        await render(PENDING);
        expect(q('[data-cd="cell-name"]')?.textContent).toBe('sync.example.com.');
        expect(q('[data-cd="cell-type"]')?.textContent).toBe('CNAME');
        expect(q('[data-cd="cell-target"]')?.textContent).toBe('dev.d.link.carnivore.ai.');
        expect(q('[data-cd="check"]')?.textContent).toContain('turn the orange cloud off');
        expect(q('[data-cd-led]')?.getAttribute('data-cd-led')).toBe('wait');
        expect(document.body.textContent).not.toContain('Mac');
    });

    test('copy puts the cell on the clipboard', async () => {
        let copied = '';
        Object.defineProperty(navigator, 'clipboard', { value: { writeText: async (t: string) => void (copied = t) }, configurable: true });
        await render(PENDING);
        (q('[data-cd="copy-target"]') as HTMLButtonElement).click();
        await settle();
        expect(copied).toBe('dev.d.link.carnivore.ai.');
    });

    test('the setup prompt carries the live name, target and every rule', async () => {
        let copied = '';
        Object.defineProperty(navigator, 'clipboard', { value: { writeText: async (t: string) => void (copied = t) }, configurable: true });
        await render(PENDING);
        (q('[data-cd="copy-prompt"]') as HTMLButtonElement).click();
        await settle();
        for (const part of ['sync.example.com', 'dev.d.link.carnivore.ai', 'ttl 300', 'orange cloud', 'dns only', 'aaaa', 'do not touch any other record',
            'do not add a txt, caa', 'apex', '@1.1.1.1', '@8.8.8.8', 'dev.d.link.carnivore.ai. (with the trailing dot)', 'dig output']) {
            expect(copied).toContain(part);
        }
        expect(copied).not.toMatch(/\{(name|target)\}/);
    });

    test('a live name shows the certificate expiry and no record, and remove calls DELETE', async () => {
        const live: View = {
            ...PENDING, state: 'live', check: null,
            cert: { issuer: 'R11', not_after: '2026-12-29T10:00:00+00:00', profile: 'shortlived' },
        };
        const calls = await render(live);
        expect(q('[data-cd="record"]')).toBeNull();
        expect(q('[data-cd="cert"]')?.textContent).toContain('R11');
        expect(q('[data-cd="cert"]')?.textContent).toContain('2026-12-29');
        expect(q('[data-cd-led]')?.getAttribute('data-cd-led')).toBe('ok');
        (q('[data-cd="remove"]') as HTMLButtonElement).click();
        await settle();
        expect(calls).toContain('DELETE /phone-link/custom-domain');
    });

    test('a refused name says which rule it broke, from the catalog', async () => {
        await render(NONE, () => new ApiError('bad', 400, 'bad_domain', { code: 'bad_domain', reason: 'apex' }));
        const input = q('[data-cd="input"]') as HTMLInputElement;
        input.value = 'example.com';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();
        (q('[data-cd="submit"]') as HTMLButtonElement).click();
        await settle();
        expect(q('[data-cd="problem"]')?.textContent).toContain('bare domain cannot hold a cname');
    });

    test('an older server that answers nothing useful reads as no binding', async () => {
        const fetcher = (async () => ({})) as unknown as Fetcher;
        mounted.push(mount(CustomDomain, { target: document.body, props: { fetcher } }));
        await settle();
        expect(q('[data-cd="input"]')).not.toBeNull();
    });
});

describe('custom domain wording helpers', () => {
    test('states, reasons, leds and errors map to catalog keys', () => {
        expect(stateKey({ ...NONE, state: 'dead', dead_reason: 'sync_off' })).toBe('phoneLink.customDomain.dead.sync_off');
        expect(stateKey({ ...NONE, state: 'lockout' })).toBe('phoneLink.customDomain.state.lockout');
        expect(ledOf('live')).toBe('ok');
        expect(ledOf('dead')).toBe('bad');
        expect(ledOf('released')).toBe('off');
        expect(errorKey('control_refused:cd_limit')).toBe('phoneLink.customDomain.error.control_refused');
        expect(errorKey(null)).toBeNull();
        expect(checkMessage({ ...PENDING, check: { result: 'match', seen: null, checked_at: 1 } })).toBeNull();
        expect(checkMessage({ ...PENDING, check: { result: 'weird', seen: null, checked_at: 1 } })?.key).toBe('phoneLink.customDomain.check.dns_error');
        expect(refusalKey(new ApiError('x', 409, 'domain_exists', { code: 'domain_exists' }))).toBe('phoneLink.customDomain.refused.domain_exists');
        expect(refusalKey(new Error('x'))).toBeNull();
    });
});
