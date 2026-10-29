/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, unmount } from 'svelte';
import SignInModal from './SignInModal.svelte';
import { TERMS_VERSION, type SignInHost } from './signin-flow';

let panel: Record<string, unknown> | null = null;
const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

function fakeHost() {
    let release: (v: unknown) => void = () => undefined;
    const host = {
        startWeb: vi.fn((_body: unknown) => new Promise((resolve) => { release = resolve; })),
        pollWeb: vi.fn(async () => ({ signed_in: true, login: 'ada@example.test', provider: 'google' })),
        startEmail: vi.fn(async () => ({ flow_id: 'f1', destination: 'a***@example.test', expires_in: 900 })),
        verifyEmail: vi.fn(async () => ({ signed_in: true, login: 'ada@example.test', provider: 'email' })),
        verifyMailbox: vi.fn(),
    };
    return { host: host as unknown as SignInHost, spies: host, release: (v: unknown) => release(v) };
}

function open(host: SignInHost) {
    const close = vi.fn();
    panel = mount(SignInModal, { target: document.body, props: { feature: 'share_link', src: 'menu', close, host } as never }) as never;
    return close;
}

beforeEach(() => vi.useRealTimers());
afterEach(() => {
    if (panel) unmount(panel as never);
    panel = null;
    document.body.innerHTML = '';
    vi.restoreAllMocks();
    vi.useRealTimers();
});

describe('SignInModal', () => {
    it('draws google, github, then the email continue, with the feature headline', () => {
        open(fakeHost().host);
        const order = [...document.querySelectorAll('[data-signin-provider], [data-signin-continue]')]
            .map((el) => el.getAttribute('data-signin-provider') ?? 'email');
        expect(order).toEqual(['google', 'github', 'email']);
        expect(document.body.textContent).toContain('sign in to share this session');
    });

    it('opens the tab inside the click, before the start request resolves, and sends consent and src', async () => {
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
        const tab = { closed: false, opener: {}, location: { href: '' }, close: vi.fn() };
        const openSpy = vi.spyOn(window, 'open').mockReturnValue(tab as never);
        const { host, spies, release } = fakeHost();
        const close = open(host);
        const seen = vi.fn();
        window.addEventListener('cloude:catalog-session', seen);
        document.querySelector<HTMLButtonElement>('[data-signin-provider="google"]')!.click();
        expect(openSpy).toHaveBeenCalledTimes(1);
        expect(spies.startWeb).toHaveBeenCalledTimes(1);
        expect(spies.startWeb.mock.calls[0]![0]).toEqual({
            provider: 'google', src: 'menu', consent: { terms_version: TERMS_VERSION, age_16_plus: true, news: true },
        });
        expect(tab.location.href).toBe('');
        release({ flow_id: 'w1', url: 'https://provider.example/auth', expires_in: 600, interval: 3 });
        await vi.advanceTimersByTimeAsync(0);
        expect(tab.location.href).toBe('https://provider.example/auth');
        await vi.advanceTimersByTimeAsync(3000);
        expect(spies.pollWeb).toHaveBeenCalledWith('w1');
        expect(seen).toHaveBeenCalled();
        expect(close).toHaveBeenCalledWith('signed_in');
        window.removeEventListener('cloude:catalog-session', seen);
    });

    it('both provider buttons wear their brand glyph, the same size, left of the label (#1200)', () => {
        const { host } = fakeHost();
        open(host);
        for (const provider of ['google', 'github']) {
            const button = document.querySelector<HTMLButtonElement>(`[data-signin-provider="${provider}"]`)!;
            const icon = button.querySelector('.signin__icon svg[data-icon]')!;
            expect(icon.getAttribute('data-icon')).toBe(provider);
            expect(icon.getAttribute('width')).toBe('16');
            expect(icon.getAttribute('fill')).toBe('currentColor');
            expect(button.firstElementChild!.classList.contains('signin__icon')).toBe(true);
        }
    });

    it('renders the email code step inline and sends the unticked news choice with the verify', async () => {
        const { host, spies } = fakeHost();
        const close = open(host);
        const news = document.querySelector<HTMLButtonElement>('[data-signin-news]')!;
        expect(news.getAttribute('aria-checked')).toBe('true');
        news.click();
        const email = document.querySelector<HTMLInputElement>('[data-signin-email]')!;
        email.value = 'ada@example.test';
        email.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        document.querySelector<HTMLButtonElement>('[data-signin-continue]')!.click();
        await settle();
        const code = document.querySelector<HTMLInputElement>('[data-signin-code]')!;
        expect(code).not.toBeNull();
        code.value = '12345678';
        code.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        document.querySelector<HTMLButtonElement>('[data-signin-use-code]')!.click();
        await settle();
        expect(spies.verifyEmail).toHaveBeenCalledWith('f1', '12345678', {
            consent: { terms_version: TERMS_VERSION, age_16_plus: true, news: false }, src: 'menu',
        });
        expect(close).toHaveBeenCalledWith('signed_in');
    });

    it('sends the terms version the hosted api currently accepts', () => {
        const hosted = readFileSync(resolve(process.cwd(), '../hosted/catalog/api/terms.py'), 'utf8');
        expect(hosted).toContain(`TERMS_VERSION = "${TERMS_VERSION}"`);
    });
});
