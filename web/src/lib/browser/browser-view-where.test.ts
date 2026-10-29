/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.hoisted(() => localStorage.setItem('claude_tunnel_token', 'an-access-token'));
vi.mock('./browser-socket', () => ({ openBrowserSocket: () => ({ send: () => {}, reopen: () => {}, close: () => {} }) }));

import { t } from '../i18n/index.svelte';
import BrowserView from './BrowserView.svelte';

const BROWSER_ID = '0123456789abcdef';

afterEach(() => { document.body.innerHTML = ''; });

describe('the where note at the address bar', () => {
    test('shows while the address is being typed, and names the computer carnivore runs on as where addresses resolve', () => {
        vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} });
        const target = document.createElement('div');
        document.body.appendChild(target);
        const app = mount(BrowserView, { target, props: { browserId: BROWSER_ID } });
        flushSync();
        const field = target.querySelector<HTMLInputElement>('.bv-address')!;
        const note = (): HTMLElement | null => target.querySelector('[data-browser-where]');

        expect(note()).toBeNull();
        expect(field.getAttribute('title')).toBe(t('browser.address.where'));
        expect(t('browser.address.where')).toContain('localhost is that computer');

        field.focus();
        field.dispatchEvent(new FocusEvent('focus'));
        flushSync();
        expect(note()!.textContent).toBe(t('browser.address.where'));
        expect(field.getAttribute('aria-describedby')).toBe(note()!.id);

        field.blur();
        field.dispatchEvent(new FocusEvent('blur'));
        flushSync();
        expect(note()).toBeNull();
        unmount(app);
        vi.unstubAllGlobals();
    });
});
