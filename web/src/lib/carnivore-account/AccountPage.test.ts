/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import AccountPage from './AccountPage.svelte';
import { catalogAccount } from '../drawer-hud/catalog-account.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { CatalogHost } from '../catalog/catalog';
import type { AccountPageHost } from './account-page-host';
import { avatarHtml } from '../drawer/avatar';
import { accountChip } from '../drawer-hud/account-menu.svelte';
import { accountIdentity } from '../drawer-hud/account-identity';

const openSignInModal = vi.fn(async (_request: unknown) => undefined);
vi.mock('./open-signin', () => ({ openSignInModal: (r: unknown) => openSignInModal(r) }));

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);
const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 10));

let panel: Record<string, unknown> | null = null;

function page(account: AccountPageHost) {
    const host = {
        getCatalogAccountSessions: async () => ({ sessions: [] }),
        signOutOfCatalog: async () => ({ signed_in: false, login: null }),
        exportCatalogAccount: async () => ({}),
    } as unknown as CatalogHost;
    const target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(AccountPage, { target, props: { host, account, t, embedded: true } as never }) as never;
    flushSync();
}

beforeEach(() => openSignInModal.mockClear());
afterEach(() => {
    if (panel) unmount(panel as never);
    panel = null;
    document.body.innerHTML = '';
    catalogAccount.facts = null;
});

describe('signed in', () => {
    it('shows handle, email and provider, and the news switch posts the new value', async () => {
        catalogAccount.facts = { signedIn: true, handle: 'ada-lovelace', login: 'ada@example.test', email: 'ada@example.test', provider: 'google' };
        const setNews = vi.fn(async (next: boolean) => next);
        page({ readNews: async () => false, setNews });
        await settle();
        expect(document.querySelector('[data-account-handle]')?.textContent).toBe('ada-lovelace');
        expect(document.querySelector('[data-account-email]')?.textContent).toBe('ada@example.test');
        expect(document.querySelector('[data-account-provider]')?.textContent).toBe('signed in with google');
        const toggle = document.querySelector<HTMLButtonElement>('[data-account-news]')!;
        expect(toggle.getAttribute('aria-checked')).toBe('false');
        toggle.click();
        await settle();
        expect(setNews).toHaveBeenCalledWith(true);
        expect(document.querySelector('[data-account-signout]')).not.toBeNull();
    });

    it('offers pick your handle when there is none', async () => {
        catalogAccount.facts = { signedIn: true, handle: '', login: 'ada@example.test', email: 'ada@example.test', provider: 'email' };
        page({ readNews: async () => true, setNews: async (n) => n });
        await settle();
        expect(document.querySelector('[data-account-pick-handle]')).not.toBeNull();
        expect(document.querySelector('#catalog-account-handle-change')).toBeNull();
    });

    it('offers change handle, and not pick your handle, once there is one', async () => {
        catalogAccount.facts = { signedIn: true, handle: 'ada', login: 'ada@example.test', email: 'ada@example.test', provider: 'email' };
        page({ readNews: async () => true, setNews: async (n) => n });
        await settle();
        expect(document.querySelector('[data-account-pick-handle]')).toBeNull();
        expect(document.querySelector('#catalog-account-handle-change')).not.toBeNull();
    });

    it('draws the same avatar as the drawer chip for the same account, handle or not (#1200)', async () => {
        for (const handle of ['', 'ada-lovelace']) {
            const facts = { signedIn: true, handle, login: 'acme@example.net', email: 'acme@example.net', provider: 'email' };
            catalogAccount.facts = facts;
            accountChip.identity = accountIdentity(facts);
            page({ readNews: async () => true, setNews: async (n) => n });
            await settle();
            const chip = document.createElement('div');
            chip.innerHTML = avatarHtml(accountChip.identity);
            const shape = (svg: Element | null) =>
                `${svg?.getAttribute('data-tone')}|${[...(svg?.querySelectorAll('rect') ?? [])].map((r) => `${r.getAttribute('x')},${r.getAttribute('y')}`).join(' ')}`;
            const onPage = document.querySelector('.acctpage__who svg.ident');
            expect(onPage?.classList.contains(`ident--${onPage?.getAttribute('data-tone')}`)).toBe(true);
            expect(onPage, handle).not.toBeNull();
            expect(shape(onPage), handle).toBe(shape(chip.querySelector('svg.ident')));
            unmount(panel as never);
            panel = null;
            document.body.innerHTML = '';
        }
    });
});

describe('signed out', () => {
    it('lists what the account unlocks and opens the sign-in modal with src account_page', async () => {
        catalogAccount.facts = null;
        page({ readNews: async () => null, setNews: async (n) => n });
        await settle();
        expect(document.querySelectorAll('[data-account-benefits] li').length).toBe(3);
        expect(document.querySelector('[data-account-news]')).toBeNull();
        (document.querySelector('[data-account-signin]') as HTMLElement).click();
        expect(openSignInModal).toHaveBeenCalledWith(expect.objectContaining({ src: 'account_page' }));
    });
});
