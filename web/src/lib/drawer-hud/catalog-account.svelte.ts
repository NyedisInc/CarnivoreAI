import { accountIdentity, type CatalogAccountFacts } from './account-identity';
import { accountChip } from './account-menu.svelte';

export const catalogAccount: { loaded: boolean; facts: CatalogAccountFacts | null; guest: boolean; viaLink: boolean } = $state({ loaded: false, facts: null, guest: false, viaLink: false });

const changeListeners = new Set<() => void>();

export function onCatalogAccountChange(fn: () => void): () => void {
    changeListeners.add(fn);
    return () => void changeListeners.delete(fn);
}

function publish(facts: CatalogAccountFacts | null): void {
    catalogAccount.facts = facts;
    if (facts) catalogAccount.guest = false;
    catalogAccount.loaded = true;
    accountChip.identity = accountIdentity(facts);
    for (const fn of [...changeListeners]) fn();
}

function emailOf(email: string | null | undefined, login: string | null | undefined): string | null {
    if (email) return email;
    return login && login.includes('@') ? login : null;
}

export const CATALOG_SESSION_EVENT = 'cloude:catalog-session';

interface CatalogApi {
    getCatalogSession?: () => Promise<{ client?: { via_link?: boolean } | null; signed_in?: boolean | null; kind?: string | null; login?: string | null; email?: string | null; provider?: string | null }>;
    getPublishAccount?: () => Promise<{ handle?: string; login?: string | null; email?: string | null; provider?: string | null }>;
}

let readGeneration = 0;

const PASSIVE_RELOAD_COOLDOWN_MS = 60_000;
let lastSignedInOkAt = 0;

export async function loadCatalogAccount(): Promise<void> {
    const api = (globalThis as { API?: CatalogApi }).API;
    if (!api || typeof api.getCatalogSession !== 'function') return;
    const mine = ++readGeneration;
    let facts: CatalogAccountFacts | null = null;
    let guest = false;
    let viaLink = false;
    let handleOk = false;
    try {
        const session = await api.getCatalogSession();
        viaLink = session?.client?.via_link === true;
        guest = session?.signed_in !== true && session?.kind === 'guest';
        if (session?.signed_in === true) {
            facts = {
                signedIn: true,
                handle: '',
                login: session.login ?? null,
                email: emailOf(session.email, session.login),
                provider: session.provider ?? null,
            };
            if (typeof api.getPublishAccount === 'function') {
                try {
                    const account = await api.getPublishAccount();
                    handleOk = true;
                    facts = {
                        signedIn: true,
                        handle: account?.handle ?? '',
                        login: account?.login || facts.login,
                        email: emailOf(account?.email, account?.login) ?? facts.email ?? null,
                        provider: facts.provider || account?.provider || null,
                    };
                } catch (err) {
                    console.warn('[catalog-account] handle unavailable', err);
                }
            } else {
                handleOk = true;
            }
        }
    } catch (err) {
        console.warn('[catalog-account] session unavailable', err);
        return;
    }
    if (mine !== readGeneration) return;
    if (facts?.signedIn && handleOk) {
        lastSignedInOkAt = Date.now();
    } else {
        lastSignedInOkAt = 0;
    }
    catalogAccount.guest = guest;
    catalogAccount.viaLink = viaLink;
    publish(facts);
}

const ACCOUNT_SESSION_FRAME = 'account.session';

interface HostEvents {
    subscribe(handler: (frame: { type?: string; signed_in?: boolean }) => void): () => void;
}

export function followCatalogAccount(): () => void {
    lastSignedInOkAt = 0;
    void loadCatalogAccount();
    const again = () => {
        lastSignedInOkAt = 0;
        void loadCatalogAccount();
    };
    const againVisible = () => {
        if (lastSignedInOkAt > 0 && Date.now() - lastSignedInOkAt < PASSIVE_RELOAD_COOLDOWN_MS) return;
        void loadCatalogAccount();
    };
    const onVisible = () => {
        if (document.visibilityState === 'visible') againVisible();
    };
    window.addEventListener(CATALOG_SESSION_EVENT, again);
    window.addEventListener('pageshow', again);
    document.addEventListener('visibilitychange', onVisible);
    const events = (globalThis as { AppEvents?: HostEvents }).AppEvents;
    const stopPush = events?.subscribe?.((frame) => {
        if (frame?.type === 'events.hello') {
            againVisible();
            return;
        }
        if (frame?.type !== ACCOUNT_SESSION_FRAME) return;
        again();
    });
    return () => {
        window.removeEventListener(CATALOG_SESSION_EVENT, again);
        window.removeEventListener('pageshow', again);
        document.removeEventListener('visibilitychange', onVisible);
        stopPush?.();
    };
}
