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
            getCatalogSession: async () => ({ signed_in: true, login: 'acme@example.com', email: 'acme@example.com', provider: 'github' }),
            getPublishAccount: async () => ({ provider: 'github', login: '', handle: '' }),
        };
        await loadCatalogAccount();
        expect(catalogAccount.facts?.login).toBe('acme@example.com');
        expect(accountChip.identity).toEqual({ kind: 'member', name: 'acme', provider: 'github' });
    });
});

describe('the provider is how THIS machine signed in (#1200)', () => {
    test.each(['github', 'google', 'email'])('a %s session reads %s although the hosted account is email-backed', async (provider) => {
        g.API = {
            getCatalogSession: async () => ({ signed_in: true, login: 'acme@example.com', email: 'acme@example.com', provider }),
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
                return { signed_in: true, login: 'acme@example.com', email: 'acme@example.com', provider: 'github' };
            },
            getPublishAccount: async () => ({ provider: 'github', login: '', handle: '' }),
        };
        const stop = followCatalogAccount();
        await vi.waitFor(() => expect(accountChip.identity).toBeNull());
        up = true;
        fire('visibilitychange');
        await vi.waitFor(() => expect(accountChip.identity).toEqual({ kind: 'member', name: 'acme', provider: 'github' }));
        stop();
    });

    test('a page restored from the back-forward cache reads again too', async () => {
        const fire = stubDom();
        let signedIn = false;
        g.API = { getCatalogSession: async () => ({ signed_in: signedIn, login: 'acme@example.com', provider: 'github' }), getPublishAccount: async () => ({ handle: 'acme' }) };
        const stop = followCatalogAccount();
        await vi.waitFor(() => expect(accountChip.identity?.kind).toBe('lurker'));
        signedIn = true;
        fire('pageshow');
        await vi.waitFor(() => expect(accountChip.identity?.kind).toBe('member'));
        stop();
    });
});
