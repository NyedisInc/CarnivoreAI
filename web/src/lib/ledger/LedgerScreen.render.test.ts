/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import LedgerScreen from './LedgerScreen.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { LedgerHost } from './ledger-host';
import type { ProviderLedger } from './ledger-model';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const NOW = Date.parse('2026-09-17T12:00:00Z');
const at = (seconds: number) => new Date(NOW + seconds * 1000).toISOString();

const LEDGER: ProviderLedger = {
    accounts: [
        {
            id: 'codex-1',
            name: 'work',
            provider: 'codex',
            plan: 'plus',
            identity: 'acme',
            credential_state: 'ok',
            fetched_at: at(-12),
            next_poll_at: at(48),
            error: null,
            windows: [
                {
                    kind: 'primary',
                    label: '5h',
                    used_pct: 0,
                    window_seconds: 18000,
                    resets_at: at(2 * 3600 + 14 * 60),
                },
                {
                    kind: 'secondary',
                    label: '7d',
                    used_pct: null,
                    window_seconds: 604800,
                    resets_at: null,
                },
            ],
        },
        {
            id: 'claude-1',
            name: 'main',
            provider: 'claude',
            plan: 'max 20x',
            identity: 'acme',
            credential_state: 'rate_limited',
            fetched_at: at(-90),
            next_poll_at: at(300),
            error: 'http 429',
            windows: [
                {
                    kind: 'five_hour',
                    label: '5h',
                    used_pct: 93.4,
                    window_seconds: 18000,
                    resets_at: at(30 * 60),
                },
            ],
        },
    ],
    total: {
        accounts: 2,
        windows: [
            { kind: 'five_hour', label: '5h', used_pct: 46.7, resets_at: at(30 * 60), accounts: 2 },
        ],
    },
    loop: { alive: true, last_pass_at: at(-12) },
};

function hostFor(answer: ProviderLedger | Error): LedgerHost {
    return {
        providerLedger: () =>
            answer instanceof Error ? Promise.reject(answer) : Promise.resolve(answer),
        listAccounts: () => Promise.resolve([]),
        saveAccount: () => Promise.reject(new Error('not used by these cases')),
        removeAccount: () => Promise.reject(new Error('not used by these cases')),
        loginProviderAccount: () => Promise.reject(new Error('not used by these cases')),
        openSession: () => Promise.reject(new Error('not used by these cases')),
    };
}

let screen: Record<string, unknown> | null = null;

async function paint(answer: ProviderLedger | Error, account?: string): Promise<void> {
    const target = document.createElement('div');
    document.body.appendChild(target);
    screen = mount(LedgerScreen, {
        target,
        props: { host: hostFor(answer), t, nowMs: () => NOW },
    }) as never;
    (screen as unknown as { show(account?: string): void }).show(account);
    await new Promise((resolve) => setTimeout(resolve, 0));
}

function rowText(): string[] {
    return [...document.querySelectorAll('[data-ledger="row"]')].map((node) => node.textContent ?? '');
}

afterEach(() => {
    if (screen) unmount(screen as never);
    screen = null;
    document.body.innerHTML = '';
});

describe('two accounts and a total', () => {
    test('one card per account, and the total is a panel of its own', async () => {
        await paint(LEDGER);
        expect(rowText()).toHaveLength(2);
        expect(document.querySelectorAll('[data-ledger="total"]')).toHaveLength(1);
    });

    test('the total is never one more account: it sits outside the card grid', async () => {
        await paint(LEDGER);
        const total = document.querySelector('[data-ledger="total"]');
        expect(total?.closest('.ledger-grid')).toBeNull();
        expect(total?.matches('[data-ledger="row"]')).toBe(false);
        expect(document.querySelectorAll('.ledger-grid [data-ledger="row"]')).toHaveLength(2);
    });

    test('every measured window is a named meter, drawn as the shared limit gauge', async () => {
        await paint(LEDGER);
        const meters = [...document.querySelectorAll('[data-ledger="row"] .oc-gauge[role="img"]')];
        expect(meters).toHaveLength(2);
        const names = meters.map((node) => node.getAttribute('aria-label'));
        expect(names.filter((name) => /^5h window, \d+ percent used/.test(name ?? ''))).toHaveLength(2);
    });

    test('an unreadable window draws a decorative bar, never a bogus meter', async () => {
        await paint(LEDGER);
        const decorative = [...document.querySelectorAll('[data-ledger="row"] .oc-gauge[aria-hidden="true"]')];
        expect(decorative.length).toBeGreaterThanOrEqual(1);
        for (const bar of decorative) {
            expect(bar.getAttribute('role')).toBeNull();
            expect(bar.getAttribute('aria-label')).toBeNull();
        }
    });

    test('the add account control is always in the header', async () => {
        await paint(LEDGER);
        const add = document.querySelector<HTMLButtonElement>('.oc-titlebar [data-ledger="add"]');
        expect(add?.textContent ?? '').toContain(t('ledger.editor.summary'));
        expect(add?.getAttribute('aria-expanded')).toBe('false');
    });

    test('the rows are ordered by provider, so claude sits above codex', async () => {
        await paint(LEDGER);
        expect(rowText()[0]).toContain('main');
        expect(rowText()[1]).toContain('work');
    });

    test('name, provider, plan and identity all reach the row', async () => {
        await paint(LEDGER);
        const claude = rowText()[0] ?? '';
        expect(claude).toContain('main');
        expect(document.querySelector('[data-ledger="row"] [data-ledger="provider-mark"]')?.getAttribute('aria-label')).toBeTruthy();
        expect(claude).toContain('max 20x');
        expect(claude).toContain('acme');
    });

    test('A MEASURED NOUGHT PRINTS AS 0%, and is not swallowed as falsy', async () => {
        await paint(LEDGER);
        expect(rowText()[1]).toContain('0%');
    });

    test('a window nobody could read prints the unknown word, not a blank', async () => {
        await paint(LEDGER);
        expect(rowText()[1]).toContain(t('ledger.headroom.not_measured'));
    });

    test('THE HEADROOM STRIP RANKS BY WORST WINDOW AND THE CARDS DO NOT MOVE', async () => {
        await paint(LEDGER);
        const strip = [...document.querySelectorAll('.ledger-headroom__item')].map((el) => el.getAttribute('data-name'));
        expect(strip).toEqual(['main', 'work']);
        expect([...document.querySelectorAll('[data-ledger="row"]')].map((el) => el.getAttribute('data-account-id'))).toEqual(['claude-1', 'codex-1']);
    });

    test('THE STATUS CHIP IS IN THE TITLE STRIP AND THE SWITCH SLOT IS IN THE FOOTER', async () => {
        await paint(LEDGER);
        for (const row of document.querySelectorAll('[data-ledger="row"]')) {
            expect(row.querySelector('[data-ledger="chip"]')).not.toBeNull();
            expect(row.querySelector('.oc-card__head [data-ledger="chip"]')).not.toBeNull();
            expect(row.querySelector('.oc-card__body [data-ledger="chip"]')).toBeNull();
            expect(row.querySelector('.oc-card__foot')).not.toBeNull();
            expect(row.querySelector('.oc-card__head [data-asw]')).toBeNull();
        }
    });

    test('every window draws a bar, and the fill never exceeds its own cells', async () => {
        await paint(LEDGER);
        const bars = [...document.querySelectorAll('[data-ledger="row"] .seg-bar')] as HTMLElement[];
        expect(bars.length).toBeGreaterThanOrEqual(3);
        for (const bar of bars) {
            const cells = bar.querySelectorAll('.seg-bar__cell');
            const lit = bar.querySelectorAll('.seg-bar__cell[data-on="1"]');
            expect(lit.length).toBeLessThanOrEqual(cells.length);
        }
    });

    test('a percent past the high threshold takes the top colour step', async () => {
        await paint(LEDGER);
        expect(document.querySelectorAll('[data-ledger="row"] .seg-bar[data-scale="5"]')).toHaveLength(1);
    });

    test('the reset time reads as a phrase and not as a timestamp', async () => {
        await paint(LEDGER);
        expect(rowText()[1]).toContain('in 2h 14m');
        expect(rowText()[1]).not.toContain('2026-09-17T');
    });

    test('the credential state is a chip whose words come from the catalog', async () => {
        await paint(LEDGER);
        const chips = [...document.querySelectorAll('[data-ledger="chip"]')].map(
            (node) => node.textContent?.trim() ?? '',
        );
        expect(chips).toContain(t('ledger.credential.ok'));
        expect(chips).toContain(t('ledger.credential.rate_limited'));
    });

    test('a throttled credential warns rather than reading as healthy', async () => {
        await paint(LEDGER);
        expect(document.querySelectorAll('[data-ledger="chip"][data-tone="warn"]')).toHaveLength(1);
        expect(document.querySelectorAll('[data-ledger="chip"][data-tone="ok"]')).toHaveLength(1);
    });

    test('the last fetch is an age, not a stamp', async () => {
        await paint(LEDGER);
        expect(rowText()[1]).toContain('12s ago');
        expect(rowText()[0]).toContain('1m ago');
    });

    test("an account's own failure is reported in the server's words", async () => {
        await paint(LEDGER);
        expect(rowText()[0]).toContain('http 429');
    });

    test('the total line names how many accounts it is a mean of', async () => {
        await paint(LEDGER);
        const total = document.querySelector('[data-ledger="total"]')?.textContent ?? '';
        expect(total).toContain(t('ledger.total.label'));
        expect(total).toContain(t('ledger.total.accounts', { count: 2 }));
    });

    test('THE LOOP IS ITS OWN LINE, because alive is not the same as current', async () => {
        await paint(LEDGER);
        const loop = document.querySelector('[data-ledger="loop"]');
        expect(loop?.textContent ?? '').toContain(t('ledger.loop.alive', { age: '12s ago' }));
        expect(loop?.closest('.ledger-foot')).not.toBeNull();
    });

    test('a stopped loop says so rather than going quiet', async () => {
        await paint({ ...LEDGER, loop: { alive: false, last_pass_at: at(-12) } });
        const loop = document.querySelector('[data-ledger="loop"]');
        expect(loop?.textContent ?? '').toContain(t('ledger.loop.stopped', { age: '12s ago' }));
        expect(loop?.closest('.ledger-foot')).toBeNull();
        expect(document.querySelectorAll('[data-ledger="loop"]')).toHaveLength(1);
    });

    test('the screen scrolls inside its own container, so a phone never scrolls the page', async () => {
        await paint(LEDGER);
        expect(document.querySelectorAll('.oc-page__scroll')).toHaveLength(1);
    });
});

describe('the states that are not rows', () => {
    test('no accounts says where accounts are added', async () => {
        await paint({ accounts: [], total: { accounts: 0, windows: [] }, loop: { alive: true, last_pass_at: null } });
        expect(rowText()).toHaveLength(0);
        const empty = document.querySelector('[data-ledger="empty"]')?.textContent ?? '';
        expect(empty).toContain(t('ledger.empty.title'));
        expect(empty).toContain(t('ledger.empty.body'));
    });

    test('a route that is not served paints a failure, never an empty table', async () => {
        await paint(new Error('HTTP 404'));
        expect(document.querySelector('[data-ledger="empty"]')).toBe(null);
        const failure = document.querySelector('[data-ledger="unavailable"]')?.textContent ?? '';
        expect(failure).toContain('404');
    });

    test('an account carrying no windows says so rather than drawing nothing', async () => {
        await paint({
            accounts: [
                {
                    id: 'x',
                    name: 'bare',
                    provider: 'claude',
                    plan: null,
                    identity: null,
                    credential_state: 'missing',
                    fetched_at: null,
                    next_poll_at: null,
                    error: null,
                    windows: [],
                },
            ],
            total: { accounts: 0, windows: [] },
            loop: { alive: true, last_pass_at: null },
        });
        expect(rowText()[0]).toContain(t('ledger.windows.none'));
        expect(document.querySelectorAll('[data-ledger="chip"][data-tone="high"]')).toHaveLength(1);
    });

    test('NEGATIVE CONTROL: a closed screen paints nothing at all', async () => {
        const target = document.createElement('div');
        document.body.appendChild(target);
        screen = mount(LedgerScreen, {
            target,
            props: { host: hostFor(LEDGER), t, nowMs: () => NOW },
        }) as never;
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(document.querySelectorAll('[data-ledger="row"]')).toHaveLength(0);
        expect(document.querySelector('.oc-page')).toBe(null);
    });
});

describe('opened on one account (the agents drawer re-add link)', () => {
    test('marks that row and focuses its log in, without pressing it', async () => {
        await paint(LEDGER, 'codex-1');
        await new Promise((resolve) => setTimeout(resolve, 0));
        const marked = [...document.querySelectorAll<HTMLElement>('[data-ledger="row"][data-landed]')];
        expect(marked.map((row) => row.dataset.accountId)).toEqual(['codex-1']);
        const focused = document.activeElement as HTMLElement | null;
        expect(focused?.matches('[data-ledger="login"]')).toBe(true);
        expect(focused?.closest('[data-ledger="row"]')?.getAttribute('data-account-id')).toBe('codex-1');
    });

    test('NEGATIVE CONTROL: a plain open marks no row', async () => {
        await paint(LEDGER);
        expect(document.querySelectorAll('[data-ledger="row"][data-landed]')).toHaveLength(0);
        expect(document.querySelectorAll('[data-ledger="row"][data-account-id]')).toHaveLength(2);
    });
});
