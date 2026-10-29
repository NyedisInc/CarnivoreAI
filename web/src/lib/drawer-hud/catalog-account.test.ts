import { afterEach, describe, expect, test, vi } from 'vitest';
import { accountChip } from './account-menu.svelte';
import { catalogAccount, followCatalogAccount, loadCatalogAccount } from './catalog-account.svelte';

const g = globalThis as { API?: unknown };

afterEach(() => {
    delete g.API;
    accountChip.identity = null;
});

describe('loadCatalogAccount with an empty hosted login', () => {
    test('the session login names the member when /catalog/handle answers an empty login and no handle', async () => {
        g.API = {
            getCatalogSession: async () => ({ signed_in: true, login: 'alex@example.com', email: 'alex@example.com', provider: 'github' }),
            getPublishAccount: async () => ({ provider: 'github', login: '', handle: '' }),
        };
        await loadCatalogAccount();
        expect(catalogAccount.facts?.login).toBe('alex@example.com');
        expect(accountChip.identity).toEqual({ kind: 'member', name: 'alex', provider: 'github' });
    });
});

describe('the provider is how THIS machine signed in (#1200)', () => {
    test.each(['github', 'google', 'email'])('a %s session reads %s although the hosted account is email-backed', async (provider) => {
        g.API = {
            getCatalogSession: async () => ({ signed_in: true, login: 'alex@example.com', email: 'alex@example.com', provider }),
            getPublishAccount: async () => ({ provider: 'email', login: '', handle: '' }),
        };
        await loadCatalogAccount();
        expect(catalogAccount.facts?.provider).toBe(provider);
    });

    test('a session that names no provider takes the hosted account provider', async () => {
        g.API = {
            getCatalogSession: async () => ({ signed_in: true, login: 'octocat', provider: null }),
            getPublishAccount: async () => ({ provider: 'github', login: 'octocat', handle: 'octocat' }),
        };
        await loadCatalogAccount();
        expect(catalogAccount.facts?.provider).toBe('github');
    });
});

describe('a phone tab that comes back reads the account again', () => {
    function stubDom() {
        const listeners: Record<string, Array<() => void>> = {};
        const target = {
            addEventListener: (type: string, fn: () => void) => void (listeners[type] ??= []).push(fn),
            removeEventListener: (type: string, fn: () => void) => void (listeners[type] = (listeners[type] ?? []).filter((f) => f !== fn)),
        };
        vi.stubGlobal('window', target);
        vi.stubGlobal('document', { ...target, visibilityState: 'visible' });
        return (type: string) => (listeners[type] ?? []).forEach((fn) => fn());
    }

    afterEach(() => vi.unstubAllGlobals());

    test('a first read that failed no longer leaves the chip on sign in: the next resume names the member', async () => {
        const fire = stubDom();
        let up = false;
        g.API = {
            getCatalogSession: async () => {
                if (!up) throw new Error('network');
                return { signed_in: true, login: 'alex@example.com', email: 'alex@example.com', provider: 'github' };
            },
            getPublishAccount: async () => ({ provider: 'github', login: '', handle: '' }),
        };
        const stop = followCatalogAccount();
        await vi.waitFor(() => expect(accountChip.identity).toBeNull());
        up = true;
        fire('visibilitychange');
        await vi.waitFor(() => expect(accountChip.identity).toEqual({ kind: 'member', name: 'alex', provider: 'github' }));
        stop();
    });

    test('a page restored from the back-forward cache reads again too', async () => {
        const fire = stubDom();
        let signedIn = false;
        g.API = { getCatalogSession: async () => ({ signed_in: signedIn, login: 'alex@example.com', provider: 'github' }), getPublishAccount: async () => ({ handle: 'alex' }) };
        const stop = followCatalogAccount();
        await vi.waitFor(() => expect(accountChip.identity?.kind).toBe('lurker'));
        signedIn = true;
        fire('pageshow');
        await vi.waitFor(() => expect(accountChip.identity?.kind).toBe('member'));
        stop();
    });
});

describe('a read that began before a sign out cannot bring the member back (u136-03)', () => {
    afterEach(() => vi.unstubAllGlobals());

    test('a pushed signed_in:false discards the read still in flight', async () => {
        let frameHandler: ((f: { type?: string; signed_in?: boolean }) => void) | null = null;
        const target = { addEventListener: () => {}, removeEventListener: () => {} };
        vi.stubGlobal('window', target);
        vi.stubGlobal('document', { ...target, visibilityState: 'visible' });
        let release!: () => void;
        const slow = new Promise<void>((r) => (release = r));
        g.API = {
            getCatalogSession: async () => {
                await slow;
                return { signed_in: true, login: 'alex@example.com', provider: 'github' };
            },
        };
        (globalThis as { AppEvents?: unknown }).AppEvents = { subscribe: (h: typeof frameHandler) => ((frameHandler = h), () => {}) };
        const stop = followCatalogAccount();
        frameHandler!({ type: 'account.session', signed_in: false });
        expect(catalogAccount.facts).toBeNull();
        release();
        await new Promise((r) => setTimeout(r, 0));
        expect(catalogAccount.facts).toBeNull();
        expect(accountChip.identity?.kind).not.toBe('member');
        stop();
        delete (globalThis as { AppEvents?: unknown }).AppEvents;
    });

    test('of two reads the one that began last wins even if it answers first', async () => {
        const answers = [new Promise<unknown>((r) => setTimeout(() => r({ signed_in: false }), 20)), Promise.resolve({ signed_in: true, login: 'alex@example.com', provider: 'github' })];
        let call = 0;
        g.API = { getCatalogSession: () => answers[call++] };
        await Promise.all([loadCatalogAccount(), loadCatalogAccount()]);
        expect(catalogAccount.facts?.signedIn).toBe(true);
    });
});
