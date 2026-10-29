import { createPoller, type Poller } from '../sessions/poller';
import { hostWindow } from '../sessions/env';
import { t } from '../i18n/index.svelte';
import { returnToActiveSession } from '../launchpad/navigation';
import { browserNavHost } from '../launchpad/nav-host';
import { authFetch } from '../../opscenter/api/auth.svelte';
import type { PeersLedger, ProviderLedger } from './ledger-model';
import type { AccountBody } from './accounts-model';

export interface LoginStarted {
    session_id: string;
    tmux_session?: string | null;
    device_auth?: boolean;
}

export const LEDGER_POLL_INTERVAL_MS = 30000;

export interface LedgerHost {
    providerLedger(): Promise<ProviderLedger>;

    peerLedger?(): Promise<PeersLedger | null>;

    listAccounts(): Promise<unknown>;

    saveAccount(id: string, body: AccountBody): Promise<unknown>;

    removeAccount(id: string): Promise<unknown>;

    loginProviderAccount(id: string): Promise<LoginStarted>;

    /* the built-in login */
    renameBuiltInLogin?(label: string | null): Promise<void>;

    openSession(sessionId: string): Promise<void>;
}

interface LegacyPreferences {
    set(name: string, value: unknown): Promise<{ status: string; detail?: string }>;
}

export const BUILTIN_RENAME_SETTLE_MS = 7000;

/* the built-in login */
export const BUILTIN_LOGIN_LABEL_FIELD = 'builtin_login_label';

interface LegacyApi {
    getProviderLedger(): Promise<ProviderLedger>;
    listProviderAccounts(): Promise<unknown>;
    saveProviderAccount(id: string, account: AccountBody): Promise<unknown>;
    deleteProviderAccount(id: string): Promise<unknown>;
    loginProviderAccount(id: string): Promise<LoginStarted>;
}

export function browserLedgerHost(): LedgerHost {
    const api = (): LegacyApi =>
        (hostWindow() as unknown as { API: LegacyApi } | undefined)?.API as LegacyApi;
    return {
        providerLedger: () => api().getProviderLedger(),
        peerLedger: () => authFetch<PeersLedger>('/provider-ledger/peers').catch(() => null),
        listAccounts: () => api().listProviderAccounts(),
        saveAccount: (id, body) => api().saveProviderAccount(id, body),
        removeAccount: (id) => api().deleteProviderAccount(id),
        loginProviderAccount: (id) => api().loginProviderAccount(id),
        renameBuiltInLogin: async (label) => {
            const prefs = (
                hostWindow() as unknown as { Preferences?: LegacyPreferences } | undefined
            )?.Preferences;
            if (!prefs) throw new Error(t('ledger.account.rename_unavailable'));
            const result = await prefs.set(BUILTIN_LOGIN_LABEL_FIELD, label);
            if (result.status !== 'committed' && result.status !== 'unchanged') {
                throw new Error(result.detail ?? result.status);
            }
        },
        openSession: (sessionId) => returnToActiveSession(sessionId, browserNavHost(), t),
    };
}

export interface LedgerPollerDeps {
    tick: () => Promise<unknown> | unknown;
    isVisible: () => boolean;
    isAuthenticated?: () => boolean;
    setIntervalFn?: (handler: () => void, ms: number) => unknown;
    clearIntervalFn?: (handle: unknown) => void;
    intervalMs?: number;
}

export function createLedgerPoller(deps: LedgerPollerDeps): Poller {
    return createPoller({
        tick: deps.tick,
        shouldPoll: deps.isVisible,
        isAuthenticated: deps.isAuthenticated,
        setIntervalFn: deps.setIntervalFn,
        clearIntervalFn: deps.clearIntervalFn,
        intervalMs: deps.intervalMs ?? LEDGER_POLL_INTERVAL_MS,
    });
}
