/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import LedgerScreen from './LedgerScreen.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { LedgerHost } from './ledger-host';
import type { ProviderLedger } from './ledger-model';
import type { ProviderSession } from './ledger-sessions';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const account = (id: string, name: string, provider: string) => ({
    id,
    name,
    provider,
    plan: null,
    identity: null,
    credential_state: 'ok',
    fetched_at: null,
    next_poll_at: null,
    error: null,
    windows: [],
});

const LEDGER = {
    accounts: [account('claude-1', 'main', 'claude'), account('codex-1', 'work', 'codex')],
    total: null,
    loop: { alive: true, last_pass_at: null },
} as unknown as ProviderLedger;

const host: LedgerHost = {
    providerLedger: () => Promise.resolve(LEDGER),
    listAccounts: () => Promise.resolve([]),
    saveAccount: () => Promise.reject(new Error('unused')),
    removeAccount: () => Promise.reject(new Error('unused')),
    loginProviderAccount: () => Promise.reject(new Error('unused')),
    openSession: () => Promise.reject(new Error('unused')),
};

const row = (id: string, name: string, account_id: string | null): ProviderSession => ({
    session: { id } as ProviderSession['session'],
    tmux_session: name,
    label: null,
    account_id,
    activity_status: 'working',
});

let screen: Record<string, unknown> | null = null;

async function paint(rows: ProviderSession[], opened: string[] = []): Promise<void> {
    const target = document.createElement('div');
    document.body.appendChild(target);
    screen = mount(LedgerScreen, {
        target,
        props: { host, t, sessionRows: () => rows, openRow: (r: ProviderSession) => void opened.push(r.session.id) },
    }) as never;
    (screen as unknown as { show(): void }).show();
    await new Promise((resolve) => setTimeout(resolve, 0));
}

const names = (card: string): string[] =>
    [...document.querySelectorAll(`[data-account-id="${card}"] .ledger-sessions__name`)].map((n) => n.textContent ?? '');

afterEach(() => {
    if (screen) unmount(screen as never);
    screen = null;
    document.body.innerHTML = '';
});

describe('open sessions on the providers page', () => {
    test('each card lists its own account sessions, by account id', async () => {
        await paint([row('1', 'alpha', 'claude-1'), row('2', 'beta', 'codex-1'), row('3', 'gamma', 'claude-1')]);
        expect(names('claude-1')).toEqual(['alpha', 'gamma']);
        expect(names('codex-1')).toEqual(['beta']);
        expect(document.querySelector('[data-account-id="claude-1"] [data-session-id="1"]')).not.toBeNull();
    });

    test('an account with none says so quietly, and there is no unknown group', async () => {
        await paint([row('1', 'alpha', 'claude-1')]);
        const card = document.querySelector('[data-account-id="codex-1"]');
        expect(card?.textContent).toContain(t('ledger.sessions.none'));
        expect(document.body.textContent).not.toContain(t('ledger.sessions.unknown'));
    });

    test('sessions with no known provider get an unknown group', async () => {
        await paint([row('1', 'alpha', null), row('2', 'beta', 'ghost')]);
        expect(document.body.textContent).toContain(t('ledger.sessions.unknown'));
        const unknown = [...document.querySelectorAll('[data-ledger="sessions"]')].find((el) => !el.closest('[data-ledger="row"]'));
        expect([...(unknown?.querySelectorAll('.ledger-sessions__name') ?? [])].map((n) => n.textContent)).toEqual(['alpha', 'beta']);
    });

    test('clicking a session opens it', async () => {
        const opened: string[] = [];
        await paint([row('7', 'alpha', 'claude-1')], opened);
        document.querySelector<HTMLButtonElement>('[data-session-id="7"]')?.click();
        expect(opened).toEqual(['7']);
    });
});
