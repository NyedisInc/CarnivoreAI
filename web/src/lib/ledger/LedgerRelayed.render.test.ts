/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import LedgerScreen from './LedgerScreen.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { LedgerHost } from './ledger-host';
import type { ProviderLedger } from './ledger-model';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const RELAYED: ProviderLedger = {
    accounts: [
        {
            id: '0123456789ab-acme-relay',
            name: 'acme (relayed)',
            provider: 'claude',
            plan: 'max',
            credential_state: 'ok',
            windows: [],
            managed: true,
            setup_complete: true,
            relayed: true,
            relay_expires_at: '2026-09-17T15:00:00Z',
        },
    ],
    total: { accounts: 1, windows: [] },
    loop: { alive: true, last_pass_at: null },
};

let screen: Record<string, unknown> | null = null;
afterEach(() => {
    if (screen) void unmount(screen);
    screen = null;
    document.body.innerHTML = '';
});

test.each([
    ['claude', RELAYED],
    ['codex', { ...RELAYED, accounts: [{ ...RELAYED.accounts[0], id: '0123456789ab-acme-relay-codex', provider: 'codex', plan: 'plus' }] }],
] as const)('a relayed %s row is tagged, shows its copy lifetime and has no edit, login or remove control', async (_provider, ledger) => {
    const host = {
        providerLedger: () => Promise.resolve(ledger as ProviderLedger),
        listAccounts: () => Promise.resolve([]),
    } as unknown as LedgerHost;
    const target = document.createElement('div');
    document.body.appendChild(target);
    screen = mount(LedgerScreen, {
        target,
        props: { host, t, nowMs: () => Date.parse('2026-09-17T12:00:00Z') },
    }) as never;
    (screen as unknown as { show(): void }).show();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const row = document.querySelector('[data-ledger="row"]');
    expect(row).not.toBeNull();
    expect(row?.querySelector('[data-ledger="relayed-tag"]')?.textContent).toBe('relayed');
    expect(row?.querySelector('[data-ledger="relay-expiry"]')?.textContent).toBe('relayed copy lasts 3h');
    expect(row?.querySelector('[data-ledger="actions"]')).toBeNull();
});

test('a synced relayed row shows usage, the as-of label only when stale, and sessions on other computers (#2800)', async () => {
    const base = RELAYED.accounts![0]!;
    const win = [{ kind: 'five_hour', used_pct: 42, resets_at: '2026-09-17T14:00:00Z' }];
    const ledger = {
        ...RELAYED,
        accounts: [
            { ...base, id: 'fresh', windows: win, fetched_at: '2026-09-17T11:58:00Z', synced_at: '2026-09-17T11:58:00Z' },
            { ...base, id: 'stale', windows: win, fetched_at: '2026-09-17T10:00:00Z' },
            {
                ...base,
                id: 'elsewhere',
                windows: win,
                fetched_at: '2026-09-17T11:58:00Z',
                sessions_elsewhere: [
                    { computer: 'nostromo', name: 'api work', session_id: 'remote:peer-1:ses_9' },
                    { computer: 'studio', name: 'no id', session_id: null },
                ],
            },
        ],
    } as unknown as ProviderLedger;
    const host = {
        providerLedger: () => Promise.resolve(ledger),
        listAccounts: () => Promise.resolve([]),
    } as unknown as LedgerHost;
    const opened: string[] = [];
    const target = document.createElement('div');
    document.body.appendChild(target);
    screen = mount(LedgerScreen, {
        target,
        props: { host, t, nowMs: () => Date.parse('2026-09-17T12:00:00Z'), sessionRows: () => [], openRow: (r: { session: { id: string } }) => opened.push(r.session.id) },
    }) as never;
    (screen as unknown as { show(): void }).show();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const card = (id: string) => document.querySelector(`[data-account-id="${id}"]`) as HTMLElement;
    expect(card('fresh').textContent).toContain('42');
    expect(card('fresh').querySelector('[data-ledger="relay-as-of"]')).toBeNull();
    expect(card('stale').textContent).toContain('42');
    expect(card('stale').querySelector('[data-ledger="relay-as-of"]')?.textContent).toMatch(/^as of \d\d:\d\d$/);
    const rows = card('elsewhere').querySelectorAll('[data-ledger="session-elsewhere"]');
    expect(rows.length).toBe(2);
    expect(rows[0]?.textContent).toContain('nostromo');
    expect((rows[1] as HTMLButtonElement).disabled).toBe(true);
    (rows[0] as HTMLButtonElement).click();
    expect(opened).toEqual(['remote:peer-1:ses_9']);
});
