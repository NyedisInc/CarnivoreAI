/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import LedgerScreen from './LedgerScreen.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { LedgerHost } from './ledger-host';
import type { ProviderLedger } from './ledger-model';
import type { AccountBody } from './accounts-model';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const ONE: ProviderLedger = {
    accounts: [
        {
            id: 'main',
            name: 'main',
            provider: 'claude',
            plan: 'max 20x',
            identity: 'acme',
            credential_state: 'ok',
            fetched_at: null,
            next_poll_at: null,
            error: null,
            windows: [],
        },
    ],
    total: { accounts: 1, windows: [] },
    loop: { alive: true, last_pass_at: null },
};

function ledgerWith(extra: Record<string, unknown>): ProviderLedger {
    const row = ONE.accounts?.[0] as unknown as Record<string, unknown>;
    return {
        accounts: [{ ...row, ...extra } as never],
        total: { accounts: 1, windows: [] },
        loop: { alive: true, last_pass_at: null },
    };
}

const NONE: ProviderLedger = {
    accounts: [],
    total: { accounts: 0, windows: [] },
    loop: { alive: true, last_pass_at: null },
};

interface Recorder {
    host: LedgerHost;
    calls: string[];
    saved: Array<{ id: string; body: AccountBody }>;
    removed: string[];
    entered: string[];
    renamed: Array<string | null>;
}

interface Answers {
    ledger?: ProviderLedger;
    accounts?: unknown;
    saveRejects?: unknown;
    removeRejects?: unknown;
    loginRejects?: unknown;
    saveHangs?: boolean;
}

function recorder(answers: Answers = {}): Recorder {
    const calls: string[] = [];
    const saved: Array<{ id: string; body: AccountBody }> = [];
    const removed: string[] = [];
    const entered: string[] = [];
    const renamed: Array<string | null> = [];
    const host: LedgerHost = {
        providerLedger: () => {
            calls.push('ledger');
            return Promise.resolve(answers.ledger ?? NONE);
        },
        listAccounts: () => {
            calls.push('accounts');
            return Promise.resolve(answers.accounts ?? []);
        },
        saveAccount: (id, body) => {
            calls.push('save');
            saved.push({ id, body });
            if (answers.saveHangs) return new Promise<never>(() => {});
            return answers.saveRejects
                ? Promise.reject(answers.saveRejects)
                : Promise.resolve({ id, ...body });
        },
        removeAccount: (id) => {
            calls.push('remove');
            removed.push(id);
            return answers.removeRejects
                ? Promise.reject(answers.removeRejects)
                : Promise.resolve({ removed: id });
        },
        loginProviderAccount: (id) => {
            calls.push('login');
            return answers.loginRejects
                ? Promise.reject(answers.loginRejects)
                : Promise.resolve({ session_id: 'ses_' + id, tmux_session: 'cloude_' + id });
        },
        renameBuiltInLogin: (label) => {
            calls.push('rename');
            renamed.push(label);
            return Promise.resolve();
        },
        openSession: (sessionId) => {
            calls.push('open');
            entered.push(sessionId);
            return Promise.resolve();
        },
    };
    return { host, calls, saved, removed, entered, renamed };
}

let screen: Record<string, unknown> | null = null;

const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

async function paint(host: LedgerHost): Promise<void> {
    const target = document.createElement('div');
    document.body.appendChild(target);
    screen = mount(LedgerScreen, {
        target,
        props: { host, t, nowMs: () => Date.parse('2026-09-17T12:00:00Z') },
    }) as never;
    (screen as unknown as { show(): void }).show();
    await settle();
}

function editorOpen(): boolean {
    return one('[data-ledger="editor"]').getAttribute('data-open') === 'true';
}

function one<T extends Element>(selector: string): T {
    const node = document.querySelector<T>(selector);
    if (!node) throw new Error(`nothing matched ${selector}`);
    return node;
}

async function openPicker(scope: string): Promise<void> {
    await press(`${scope} [data-ledger="color-chip"]`);
}

function type(selector: string, value: string): void {
    const field = one<HTMLInputElement>(selector);
    field.value = value;
    field.dispatchEvent(new Event('input', { bubbles: true }));
}

async function press(selector: string): Promise<void> {
    one<HTMLButtonElement>(selector).click();
    await settle();
}

async function fillAdvancedClaude(name: string, dir: string): Promise<void> {
    type('#ledger-account-name', name);
    await press('[data-ledger="advanced"] [data-btn="row"]');
    type('#ledger-account-path', dir);
}

afterEach(() => {
    if (screen) unmount(screen as never);
    screen = null;
    document.body.innerHTML = '';
});

describe('the form is on this screen, not in settings', () => {
    test('an install with nothing configured paints the form open', async () => {
        const spy = recorder();
        await paint(spy.host);
        expect(document.querySelector('#ledger-account-name')).not.toBeNull();
        expect(editorOpen()).toBe(true);
    });

    test('the empty sentence points at the form below it, not at settings', async () => {
        const spy = recorder();
        await paint(spy.host);
        const empty = one('[data-ledger="empty"]').textContent ?? '';
        expect(empty).toContain(t('ledger.empty.body'));
        expect(empty).not.toContain('settings');
    });

    test('an install that already has a row keeps the form folded away', async () => {
        const spy = recorder({ ledger: ONE });
        await paint(spy.host);
        expect(editorOpen()).toBe(false);
    });

    test("THE HEADER'S ADD ACCOUNT OPENS THE FORM and puts the caret in its name", async () => {
        const spy = recorder({ ledger: ONE });
        await paint(spy.host);
        const add = one<HTMLButtonElement>('.oc-titlebar [data-ledger="add"]');
        expect(one<HTMLElement>('[data-ledger="editor"]').hidden).toBe(true);
        await press('.oc-titlebar [data-ledger="add"]');
        expect(editorOpen()).toBe(true);
        expect(one<HTMLElement>('[data-ledger="editor"]').hidden).toBe(false);
        expect(add.getAttribute('aria-expanded')).toBe('true');
        expect(document.activeElement?.id).toBe('ledger-account-name');
        await press('.oc-titlebar [data-ledger="add"]');
        expect(editorOpen()).toBe(false);
    });

    test('the configured accounts are read when the screen opens', async () => {
        const spy = recorder();
        await paint(spy.host);
        expect(spy.calls).toContain('accounts');
    });
});

describe('adding a claude account', () => {
    test('the id is derived from the name and shown before anything is sent', async () => {
        const spy = recorder();
        await paint(spy.host);
        type('#ledger-account-name', 'Work Max');
        await settle();
        expect(one<HTMLInputElement>('#ledger-account-id').value).toBe('work-max');
        expect(spy.saved).toHaveLength(0);
    });

    test('an advanced write lands on the derived id with the stated pointer', async () => {
        const spy = recorder();
        await paint(spy.host);
        await fillAdvancedClaude('Work Max', '~/.claude-work');
        await press('[data-ledger="editor-submit"]');
        expect(spy.saved).toEqual([
            {
                id: 'work-max',
                body: {
                    name: 'Work Max',
                    provider: 'claude',
                    managed: false,
                    color: null,
                    claude_config_dir: '~/.claude-work',
                    codex_home: '~/.codex',
                },
            },
        ]);
    });

    test('THE LEDGER IS RE-READ STRAIGHT AFTER THE WRITE, not on the next tick', async () => {
        const spy = recorder();
        await paint(spy.host);
        await fillAdvancedClaude('Work Max', '~/.claude-work');
        await press('[data-ledger="editor-submit"]');
        const write = spy.calls.indexOf('save');
        expect(write).toBeGreaterThanOrEqual(0);
        expect(spy.calls.slice(write).includes('ledger')).toBe(true);
    });

    test('a written account clears the form, so the next one starts empty', async () => {
        const spy = recorder();
        await paint(spy.host);
        await fillAdvancedClaude('Work Max', '~/.claude-work');
        await press('[data-ledger="editor-submit"]');
        expect(one<HTMLInputElement>('#ledger-account-name').value).toBe('');
    });

    test('the advanced field defaults to the config dir and says what a profile is', async () => {
        const spy = recorder();
        await paint(spy.host);
        await fillAdvancedClaude('Work Max', '~/.claude');
        expect(one<HTMLInputElement>('#ledger-account-path').value).toBe('~/.claude');
        expect(one('[data-ledger="editor"]').textContent ?? '').toContain(
            t('ledger.editor.claude_dir_help'),
        );
    });
});

describe('switching the provider switches the one path field', () => {
    test('choosing codex swaps the label, the default and the sentence', async () => {
        const spy = recorder();
        await paint(spy.host);
        await fillAdvancedClaude('side', '~/.claude');
        const select = one<HTMLSelectElement>('#ledger-account-provider');
        select.value = 'codex';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        await settle();
        expect(one<HTMLInputElement>('#ledger-account-path').value).toBe('~/.codex');
        const text = one('[data-ledger="editor"]').textContent ?? '';
        expect(text).toContain(t('ledger.editor.codex_home_label'));
        expect(text).toContain(t('ledger.editor.codex_home_help'));
        expect(text).not.toContain(t('ledger.editor.claude_dir_help'));
    });

    test('a codex account writes the codex home and the default claude dir', async () => {
        const spy = recorder();
        await paint(spy.host);
        await fillAdvancedClaude('side', '~/.claude');
        const select = one<HTMLSelectElement>('#ledger-account-provider');
        select.value = 'codex';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        await settle();
        type('#ledger-account-path', '~/.codex-side');
        await press('[data-ledger="editor-submit"]');
        expect(spy.saved[0]?.body).toEqual({
            name: 'side',
            provider: 'codex',
            managed: false,
            color: null,
            claude_config_dir: '~/.claude',
            codex_home: '~/.codex-side',
        });
    });
});

describe('a refusal renders under the form and never leaves the screen', () => {
    test("the server's validation list names the field it refused", async () => {
        const spy = recorder({
            saveRejects: Object.assign(new Error('HTTP 422'), {
                status: 422,
                detail: [{ loc: ['body', 'name'], msg: 'name must not be empty' }],
            }),
        });
        await paint(spy.host);
        await fillAdvancedClaude('Work Max', '~/.claude-work');
        await press('[data-ledger="editor-submit"]');
        const refusal = one('[data-ledger="editor-refusal"]').textContent ?? '';
        expect(refusal).toContain('name must not be empty');
        expect(refusal).not.toContain('[object Object]');
    });

    test('a refused write KEEPS WHAT WAS TYPED, so it can be corrected', async () => {
        const spy = recorder({
            saveRejects: Object.assign(new Error('HTTP 422'), { detail: 'that id is not a slug' }),
        });
        await paint(spy.host);
        await fillAdvancedClaude('Work Max', '~/.claude-work');
        await press('[data-ledger="editor-submit"]');
        expect(one<HTMLInputElement>('#ledger-account-name').value).toBe('Work Max');
    });

    test('a name with no letters or digits is refused before the server is asked', async () => {
        const spy = recorder();
        await paint(spy.host);
        await fillAdvancedClaude('###', '~/.claude-work');
        await press('[data-ledger="editor-submit"]');
        expect(spy.saved).toHaveLength(0);
        expect(one('[data-ledger="editor-refusal"]').textContent ?? '').toContain(
            t('ledger.editor.id_blank'),
        );
    });

    test('AN ID ALREADY CONFIGURED IS REFUSED, because the write is an upsert', async () => {
        const spy = recorder({ ledger: ONE, accounts: [{ id: 'main', name: 'main' }] });
        await paint(spy.host);
        await press('.oc-titlebar [data-ledger="add"]');
        await fillAdvancedClaude('main', '~/.claude-two');
        await press('[data-ledger="editor-submit"]');
        expect(spy.saved).toHaveLength(0);
        expect(one('[data-ledger="editor-refusal"]').textContent ?? '').toContain(
            t('ledger.editor.id_taken', { id: 'main' }),
        );
    });

    test('A DUPLICATE-ID REFUSAL CLEARS AS SOON AS THE NAME IS RETYPED, not on the next submit', async () => {
        const spy = recorder({ ledger: ONE, accounts: [{ id: 'main', name: 'main' }] });
        await paint(spy.host);
        await press('.oc-titlebar [data-ledger="add"]');
        await fillAdvancedClaude('main', '~/.claude-two');
        await press('[data-ledger="editor-submit"]');
        expect(one('[data-ledger="editor-refusal"]').textContent ?? '').toContain(
            t('ledger.editor.id_taken', { id: 'main' }),
        );
        type('#ledger-account-name', 'second');
        await settle();
        expect(document.querySelector('[data-ledger="editor-refusal"]')).toBeNull();
    });

    test('A SERVER REFUSAL CLEARS WHEN THE NAME CHANGES, because it no longer describes the form', async () => {
        const spy = recorder({
            saveRejects: Object.assign(new Error('HTTP 409'), {
                status: 409,
                detail: { code: 'managed_dir_unavailable', detail: 'permission denied' },
            }),
        });
        await paint(spy.host);
        type('#ledger-account-name', 'claude one');
        await press('[data-ledger="editor-submit"]');
        expect(one('[data-ledger="editor-refusal"]').textContent ?? '').toContain('permission denied');
        type('#ledger-account-name', 'claude two');
        await settle();
        expect(document.querySelector('[data-ledger="editor-refusal"]')).toBeNull();
    });
});

describe('the built-in login', () => {
    test('its card says built-in login and draws no edit, log in or remove control', async () => {
        const spy = recorder({ ledger: ledgerWith({ id: 'auto-claude-default' }) });
        await paint(spy.host);
        expect(one('[data-ledger="row"] .ledger-card__tags').textContent ?? '').toContain(t('ledger.account.built_in_login'));
        expect(document.querySelector('[data-ledger="remove"]')).toBeNull();
        expect(document.querySelector('[data-ledger="login"]')).toBeNull();
        expect(document.querySelector('[data-ledger="edit-start"]')).toBeNull();
    });
});

describe('renaming the built-in login', () => {
    test('typing a name and saving sends only the label, and the card shows it at once', async () => {
        const spy = recorder({ ledger: ledgerWith({ id: 'auto-claude-default' }) });
        await paint(spy.host);
        await press('[data-ledger="rename-start"]');
        const input = one<HTMLInputElement>('[data-ledger="rename-input"]');
        input.value = 'work laptop';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await press('[data-ledger="rename-save"]');
        expect(spy.renamed).toEqual(['work laptop']);
        expect(spy.saved).toEqual([]);
        expect(one('[data-ledger="row"] .oc-card__title').textContent ?? '').toContain('work laptop');
    });

    test('a blank name sends null so the card returns to its default', async () => {
        const spy = recorder({ ledger: ledgerWith({ id: 'auto-claude-default' }) });
        await paint(spy.host);
        await press('[data-ledger="rename-start"]');
        const input = one<HTMLInputElement>('[data-ledger="rename-input"]');
        input.value = '   ';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await press('[data-ledger="rename-save"]');
        expect(spy.renamed).toEqual([null]);
    });

    test('a managed account card has no rename control', async () => {
        const spy = recorder({ ledger: ONE, accounts: [{ id: 'main', name: 'main' }] });
        await paint(spy.host);
        expect(document.querySelector('[data-ledger="rename-start"]')).toBeNull();
    });
});

describe('removing an account', () => {
    test('THE FIRST PRESS ASKS AND SENDS NOTHING', async () => {
        const spy = recorder({ ledger: ONE });
        await paint(spy.host);
        await press('[data-ledger="remove"]');
        expect(spy.removed).toHaveLength(0);
        expect(one('[data-ledger="confirm"]').textContent ?? '').toContain(
            t('ledger.editor.remove_confirm', { name: 'main' }),
        );
    });

    test('confirming deletes that id and re-reads the ledger', async () => {
        const spy = recorder({ ledger: ONE });
        await paint(spy.host);
        await press('[data-ledger="remove"]');
        await press('[data-ledger="confirm-yes"]');
        expect(spy.removed).toEqual(['main']);
        const call = spy.calls.indexOf('remove');
        expect(spy.calls.slice(call).includes('ledger')).toBe(true);
    });

    test('keeping it sends nothing and puts the row back as it was', async () => {
        const spy = recorder({ ledger: ONE });
        await paint(spy.host);
        await press('[data-ledger="remove"]');
        await press('[data-ledger="confirm-no"]');
        expect(spy.removed).toHaveLength(0);
        expect(document.querySelector('[data-ledger="confirm"]')).toBeNull();
        expect(document.querySelector('[data-ledger="remove"]')).not.toBeNull();
    });

    test('a refused delete says so and the row stays on screen', async () => {
        const spy = recorder({
            ledger: ONE,
            removeRejects: Object.assign(new Error('HTTP 404'), { status: 404 }),
        });
        await paint(spy.host);
        await press('[data-ledger="remove"]');
        await press('[data-ledger="confirm-yes"]');
        expect(one('[data-ledger="row"]').textContent ?? '').toContain('HTTP 404');
        expect(document.querySelectorAll('[data-ledger="row"]')).toHaveLength(1);
    });
});

describe('the fold belongs to the reader, and typing never takes it away', () => {
    test('TYPING DOES NOT SLAM THE FORM SHUT, at any row count', async () => {
        const spy = recorder({
            ledger: ONE,
            accounts: [{ id: 'main', name: 'main', provider: 'claude' }],
        });
        await paint(spy.host);
        expect(editorOpen()).toBe(false);

        await press('.oc-titlebar [data-ledger="add"]');
        expect(editorOpen()).toBe(true);

        const field = one<HTMLInputElement>('#ledger-account-name');
        field.focus();
        for (const typed of ['a', 'ab', 'abc']) {
            field.value = typed;
            field.dispatchEvent(new Event('input', { bubbles: true }));
            await settle();
            expect(editorOpen()).toBe(true);
        }
        expect(document.activeElement).toBe(field);
        expect(one<HTMLInputElement>('#ledger-account-id').value).toBe('abc');
    });

    test('a reader who folds it away keeps it folded while they type', async () => {
        const spy = recorder();
        await paint(spy.host);
        expect(editorOpen()).toBe(true);
        await press('[data-ledger="editor"] .oc-card__toggle');
        expect(editorOpen()).toBe(false);
        type('#ledger-account-name', 'work');
        await settle();
        expect(editorOpen()).toBe(false);
    });
});

describe('an account is on the table the moment it is configured', () => {
    test('a configured account nobody has measured paints a row, not an empty screen', async () => {
        const spy = recorder({
            ledger: NONE,
            accounts: [{ id: 'work-max', name: 'Work Max', provider: 'claude' }],
        });
        await paint(spy.host);
        const rows = document.querySelectorAll('[data-ledger="row"]');
        expect(rows).toHaveLength(1);
        const text = rows[0]?.textContent ?? '';
        expect(text).toContain('Work Max');
        expect(text).toContain(t('ledger.credential.unknown'));
        expect(text).toContain(t('ledger.windows.none'));
        expect(document.querySelector('[data-ledger="empty"]')).toBeNull();
    });

    test('the measured reading replaces it once the poller has one', async () => {
        const spy = recorder({
            ledger: ONE,
            accounts: [{ id: 'main', name: 'main', provider: 'claude' }],
        });
        await paint(spy.host);
        const rows = document.querySelectorAll('[data-ledger="row"]');
        expect(rows).toHaveLength(1);
        const text = rows[0]?.textContent ?? '';
        expect(text).toContain('max 20x');
        expect(text).toContain(t('ledger.credential.ok'));
    });

    test('THE ROW IS THERE STRAIGHT AFTER THE WRITE, before anything has polled', async () => {
        let written = false;
        const host: LedgerHost = {
            providerLedger: () => Promise.resolve(NONE),
            listAccounts: () =>
                Promise.resolve(
                    written ? [{ id: 'work-max', name: 'Work Max', provider: 'claude' }] : [],
                ),
            saveAccount: (id, body) => {
                written = true;
                return Promise.resolve({ id, ...body });
            },
            removeAccount: () => Promise.reject(new Error('not used by this case')),
            loginProviderAccount: () => Promise.reject(new Error('not used by this case')),
            openSession: () => Promise.reject(new Error('not used by this case')),
        };
        await paint(host);
        await fillAdvancedClaude('Work Max', '~/.claude-work');
        await press('[data-ledger="editor-submit"]');
        const rows = document.querySelectorAll('[data-ledger="row"]');
        expect(rows).toHaveLength(1);
        expect(rows[0]?.textContent ?? '').toContain('Work Max');
        expect(document.querySelector('[data-ledger="empty"]')).toBeNull();
    });

    test('a configured list that could not be read paints what was measured', async () => {
        const spy = recorder({ ledger: ONE, accounts: 'not a list' });
        await paint(spy.host);
        expect(document.querySelectorAll('[data-ledger="row"]')).toHaveLength(1);
    });
});

const pageCss = readFileSync(`${process.cwd()}/src/opscenter/page.css`, 'utf8');

describe('the docked conversations drawer', () => {
    test('THE ROOT CARRIES `oc-page`, which is the class the page frame\'s dock rule keys on', async () => {
        const spy = recorder();
        await paint(spy.host);
        const root = one('.oc-page');
        expect(root.classList.contains('oc-page')).toBe(true);
        expect(pageCss).toContain('body.session-sidebar-pinned .oc-page');
        expect(root.classList.contains('pledger')).toBe(true);
        expect(root.classList.contains('active')).toBe(false);
    });
});

describe('adding an account asks for a name, a type and a colour', () => {
    test('THERE IS NO DIRECTORY FIELD ON SCREEN, because the app makes one', async () => {
        const spy = recorder();
        await paint(spy.host);
        expect(one('[data-ledger="advanced"] [data-btn="row"]').getAttribute('aria-expanded')).toBe('false');
    });

    test('it says where a managed login is going to live', async () => {
        const spy = recorder();
        await paint(spy.host);
        expect(one('[data-ledger="editor"]').textContent ?? '').toContain(
            t('ledger.editor.managed_help'),
        );
    });

    test('the sorted terminal colours open from one chip and none is chosen to begin with', async () => {
        const spy = recorder();
        await paint(spy.host);
        expect(document.querySelectorAll('[data-ledger="editor"] .ledger-tcell')).toHaveLength(0);
        await openPicker('[data-ledger="editor"]');
        const swatches = document.querySelectorAll('[data-ledger="editor"] .ledger-tcell');
        expect(swatches).toHaveLength(249);
        expect(
            [...swatches].filter((node) => node.getAttribute('aria-pressed') === 'true'),
        ).toHaveLength(0);
    });

    test('A HEX FIELD REACHES ANY COLOUR, with no library and no native input', async () => {
        const spy = recorder();
        await paint(spy.host);
        await openPicker('[data-ledger="editor"]');
        const hex = one<HTMLInputElement>('[data-ledger="editor"] [data-ledger="color-hex"]');
        expect(hex.getAttribute('type')).toBe('text');
        expect(hex.getAttribute('aria-label')).toBe(t('ledger.color.hex_label'));
    });

    test('A COLOUR THE PALETTE NEVER OFFERED RIDES ON THE WIRE, lowercased', async () => {
        const spy = recorder();
        await paint(spy.host);
        type('#ledger-account-name', 'claude one');
        await openPicker('[data-ledger="editor"]');
        const custom = one<HTMLInputElement>('[data-ledger="editor"] [data-ledger="color-hex"]');
        custom.value = '#123456';
        custom.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        await press('[data-ledger="editor-submit"]');
        expect(spy.saved[0]?.body.color).toBe('#123456');
    });

    test('every swatch is a real button, so the keyboard reaches it', async () => {
        const spy = recorder();
        await paint(spy.host);
        await openPicker('[data-ledger="editor"]');
        for (const node of document.querySelectorAll('[data-ledger="editor"] .ledger-tcell')) {
            expect(node.tagName).toBe('BUTTON');
            expect(node.getAttribute('aria-label')).toBeTruthy();
        }
    });

    test('A MANAGED WRITE STATES NO POINTER AT ALL', async () => {
        const spy = recorder();
        await paint(spy.host);
        type('#ledger-account-name', 'claude one');
        await press('[data-ledger="editor-submit"]');
        expect(spy.saved).toEqual([
            {
                id: 'claude-one',
                body: { name: 'claude one', provider: 'claude', managed: true, color: null },
            },
        ]);
    });

    test('a managed write is not refused for the directory nobody was asked for', async () => {
        const spy = recorder();
        await paint(spy.host);
        type('#ledger-account-name', 'claude one');
        await press('[data-ledger="editor-submit"]');
        expect(document.querySelector('[data-ledger="editor-refusal"]')).toBeNull();
    });

    test('the chosen swatch rides on the wire and shows as chosen first', async () => {
        const spy = recorder();
        await paint(spy.host);
        type('#ledger-account-name', 'claude one');
        await openPicker('[data-ledger="editor"]');
        one<HTMLButtonElement>('[data-ledger="editor"] .ledger-tcell').click();
        await settle();
        await openPicker('[data-ledger="editor"]');
        expect(one<HTMLButtonElement>('[data-ledger="editor"] .ledger-tcell[aria-pressed="true"]')).toBeTruthy();
        await press('[data-ledger="editor-submit"]');
        expect(spy.saved[0]?.body.color).toBe('#ffffff');
    });

    test('OPENING THE ADVANCED FOLD IS WHAT MAKES A ROW UNMANAGED', async () => {
        const spy = recorder();
        await paint(spy.host);
        await fillAdvancedClaude('work', '~/.claude-work');
        await press('[data-ledger="editor-submit"]');
        expect(spy.saved[0]?.body.managed).toBe(false);
    });

    test('a written account leaves no colour selected for the next one', async () => {
        const spy = recorder();
        await paint(spy.host);
        type('#ledger-account-name', 'claude one');
        await openPicker('[data-ledger="editor"]');
        one<HTMLButtonElement>('[data-ledger="editor"] .ledger-tcell').click();
        await settle();
        await press('[data-ledger="editor-submit"]');
        await openPicker('[data-ledger="editor"]');
        expect(
            one<HTMLButtonElement>('[data-ledger="editor"] .ledger-tcell').getAttribute('aria-pressed'),
        ).toBe('false');
    });

    test('a refused managed write says so under the form, not as a toast', async () => {
        const spy = recorder({
            saveRejects: Object.assign(new Error('HTTP 409'), {
                status: 409,
                detail: { code: 'managed_dir_unavailable', detail: 'permission denied' },
            }),
        });
        await paint(spy.host);
        type('#ledger-account-name', 'claude one');
        await press('[data-ledger="editor-submit"]');
        expect(one('[data-ledger="editor-refusal"]').textContent ?? '').toContain('permission denied');
    });
});

describe('the mark in front of a row', () => {
    const COLOURED = ledgerWith({ color: '#a3e635', managed: true });

    test('a row with a colour paints it', async () => {
        const spy = recorder({
            ledger: COLOURED,
            accounts: [{ id: 'main', name: 'main', provider: 'claude', color: '#a3e635' }],
        });
        await paint(spy.host);
        expect(one('[data-ledger="row"] .ledger-mark').getAttribute('style')).toContain('#a3e635');
    });

    test('A ROW WITH NO COLOUR PAINTS AN EMPTY OUTLINE, never a default hue', async () => {
        const spy = recorder({ ledger: ONE, accounts: [{ id: 'main', name: 'main' }] });
        await paint(spy.host);
        const mark = one('[data-ledger="row"] .ledger-mark');
        expect(mark.classList.contains('ledger-mark--none')).toBe(true);
        expect(mark.getAttribute('style')).toContain('transparent');
    });

    test('PRESSING THE MARK OPENS THE EDITOR, which is the one place a colour is set', async () => {
        const spy = recorder({ ledger: ONE, accounts: [{ id: 'main', name: 'main' }] });
        await paint(spy.host);
        expect(document.querySelector('[data-ledger="edit"]')).toBeNull();
        await press('[data-ledger="row"] .ledger-mark');
        expect(document.querySelector('[data-ledger="edit"]')).not.toBeNull();
    });

    test('there is no picker that writes a colour on its own any more', async () => {
        const spy = recorder({ ledger: ONE, accounts: [{ id: 'main', name: 'main' }] });
        await paint(spy.host);
        await press('[data-ledger="row"] .ledger-mark');
        expect(document.querySelector('.ledger-mark__picker')).toBeNull();
        expect(spy.saved).toEqual([]);
    });
});

describe('editing an account that already exists', () => {
    const STORED_NAMED = {
        id: 'main',
        name: 'main',
        provider: 'claude',
        claude_config_dir: '~/.claude-main',
        codex_home: '~/.codex',
        managed: false,
        color: '#a3e635',
    };

    const STORED_MANAGED = {
        id: 'main',
        name: 'main',
        provider: 'claude',
        claude_config_dir: '/Users/a/.carnivore/accounts/main',
        codex_home: '~/.codex',
        managed: true,
        color: null,
    };

    async function openEditor(accounts: unknown[], answers: Answers = {}): Promise<Recorder> {
        const spy = recorder({ ledger: ONE, accounts, ...answers });
        await paint(spy.host);
        await press('[data-ledger="row"] [data-ledger="edit-start"]');
        return spy;
    }

    test('THE CONTROL IS IN THE ROW, beside log in and remove', async () => {
        const spy = recorder({ ledger: ONE, accounts: [STORED_NAMED] });
        await paint(spy.host);
        const actions = one('[data-ledger="row"] [data-ledger="actions"]');
        expect(actions.querySelector('[data-ledger="edit-start"]')).not.toBeNull();
        expect(actions.querySelector('[data-ledger="login"]')).not.toBeNull();
        expect(actions.querySelector('[data-ledger="remove"]')).not.toBeNull();
        expect(one('[data-ledger="row"] [data-ledger="edit-start"]').textContent ?? '').toContain(
            t('ledger.edit.start'),
        );
    });

    test('the editor opens INSIDE its own card, and the card takes the whole row', async () => {
        await openEditor([STORED_NAMED]);
        const card = one('[data-ledger="edit"]').closest('[data-ledger="row"]');
        expect(card?.getAttribute('data-account-id')).toBe('main');
        expect(card?.parentElement?.classList.contains('ledger-cell--wide')).toBe(true);
    });

    test('IT OPENS PRE-FILLED WITH THE NAME AND THE COLOUR THE ROW ALREADY HAS', async () => {
        await openEditor([STORED_NAMED]);
        expect(one<HTMLInputElement>('#ledger-edit-name').value).toBe('main');
        await openPicker('[data-ledger="edit"]');
        expect(one<HTMLInputElement>('[data-ledger="edit"] [data-ledger="color-hex"]').value).toBe('a3e635');
    });

    const editorValues = (): (string | undefined)[] =>
        [...document.querySelectorAll('[data-ledger="edit"] dd')].map((d) => d.textContent?.trim());

    test('THE ID, THE PROVIDER, THE LOGIN AREA AND THE PATH ARE SHOWN AS PLAIN TEXT, NOT INPUTS', async () => {
        await openEditor([STORED_NAMED]);
        for (const gone of ['id', 'provider', 'managed', 'path']) {
            expect([gone, document.getElementById(`ledger-edit-${gone}`)]).toEqual([gone, null]);
        }
        expect(document.querySelectorAll('[data-ledger="edit"] input[readonly]')).toHaveLength(0);
        const values = editorValues();
        expect(values).toContain('main');
        expect(values).toContain('claude');
        expect(values).toContain('~/.claude-main');
    });

    test('a managed row says the app owns its login area and shows the derived path', async () => {
        await openEditor([STORED_MANAGED]);
        const values = editorValues();
        expect(values).toContain(t('ledger.edit.managed_yes'));
        expect(values).toContain('/Users/a/.carnivore/accounts/main');
    });

    test('THE HELPER COPY SAYS WHAT CANNOT BE CHANGED HERE', async () => {
        await openEditor([STORED_NAMED]);
        expect(one('[data-ledger="edit"]').textContent ?? '').toContain(t('ledger.edit.immutable_help'));
    });

    test('SAVING SENDS THE STORED ROW BACK WHOLE, with only the name and colour changed', async () => {
        const spy = await openEditor([STORED_NAMED]);
        type('#ledger-edit-name', 'day job');
        await openPicker('[data-ledger="edit"]');
        one<HTMLButtonElement>('[data-ledger="edit"] .ledger-tcell[data-idx="200"]').click();
        await settle();
        await press('[data-ledger="edit-save"]');
        expect(spy.saved).toEqual([
            {
                id: 'main',
                body: {
                    name: 'day job',
                    provider: 'claude',
                    managed: false,
                    color: '#ff00d7',
                    short_name: '',
                    claude_config_dir: '~/.claude-main',
                    codex_home: '~/.codex',
                },
            },
        ]);
    });

    test('THE ID DOES NOT MOVE WHEN THE NAME DOES', async () => {
        const spy = await openEditor([STORED_MANAGED]);
        type('#ledger-edit-name', 'day job');
        await press('[data-ledger="edit-save"]');
        expect(spy.saved[0]?.id).toBe('main');
    });

    test('a managed row still sends no pointer at all', async () => {
        const spy = await openEditor([STORED_MANAGED]);
        type('#ledger-edit-name', 'day job');
        await press('[data-ledger="edit-save"]');
        expect(spy.saved[0]?.body).toEqual({
            name: 'day job',
            provider: 'claude',
            managed: true,
            color: null,
            short_name: '',
        });
    });

    test('THE SHORT NAME IS PRE-FILLED, EDITABLE, AND SENT (EMPTY CLEARS IT)', async () => {
        const spy = await openEditor([{ ...STORED_NAMED, short_name: 'mn' }]);
        expect(one<HTMLInputElement>('#ledger-edit-short-name').value).toBe('mn');
        type('#ledger-edit-short-name', ' m2 ');
        await press('[data-ledger="edit-save"]');
        expect(spy.saved[0]?.body.short_name).toBe('m2');
    });

    test('a colour can be taken back off through the editor', async () => {
        const spy = await openEditor([STORED_NAMED]);
        await openPicker('[data-ledger="edit"]');
        await press('[data-ledger="edit"] [data-ledger="color-none"]');
        await press('[data-ledger="edit-save"]');
        expect(spy.saved[0]?.body.color).toBeNull();
    });

    test('a freely picked colour reaches the wire lowercased', async () => {
        const spy = await openEditor([STORED_NAMED]);
        await openPicker('[data-ledger="edit"]');
        const custom = one<HTMLInputElement>('[data-ledger="edit"] [data-ledger="color-hex"]');
        custom.value = '#ABCDEF';
        custom.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        await press('[data-ledger="edit-save"]');
        expect(spy.saved[0]?.body.color).toBe('#abcdef');
    });

    test('BOTH LISTS ARE RE-READ ONCE THE WRITE LANDS', async () => {
        const spy = await openEditor([STORED_NAMED]);
        type('#ledger-edit-name', 'day job');
        await press('[data-ledger="edit-save"]');
        const write = spy.calls.indexOf('save');
        expect(write).toBeGreaterThanOrEqual(0);
        expect(spy.calls.slice(write)).toContain('ledger');
        expect(spy.calls.slice(write)).toContain('accounts');
    });

    test('a write that landed closes the form', async () => {
        await openEditor([STORED_NAMED]);
        type('#ledger-edit-name', 'day job');
        await press('[data-ledger="edit-save"]');
        expect(document.querySelector('[data-ledger="edit"]')).toBeNull();
    });

    test('CANCEL WRITES NOTHING AND THROWS THE TYPING AWAY', async () => {
        const spy = await openEditor([STORED_NAMED]);
        type('#ledger-edit-name', 'day job');
        await openPicker('[data-ledger="edit"]');
        await press('[data-ledger="edit"] [data-ledger="color-none"]');
        await press('[data-ledger="edit-cancel"]');
        expect(spy.saved).toEqual([]);
        expect(document.querySelector('[data-ledger="edit"]')).toBeNull();
        await press('[data-ledger="row"] [data-ledger="edit-start"]');
        expect(one<HTMLInputElement>('#ledger-edit-name').value).toBe('main');
        await openPicker('[data-ledger="edit"]');
        expect(one<HTMLInputElement>('[data-ledger="edit"] [data-ledger="color-hex"]').value).toBe('a3e635');
    });

    test('A BLANK NAME IS REFUSED INLINE AND THE FORM STAYS OPEN', async () => {
        const spy = await openEditor([STORED_NAMED]);
        type('#ledger-edit-name', '   ');
        await press('[data-ledger="edit-save"]');
        expect(spy.saved).toEqual([]);
        expect(one('[data-ledger="edit-refusal"]').textContent ?? '').toContain(
            t('ledger.editor.name_blank'),
        );
        expect(document.querySelector('[data-ledger="edit"]')).not.toBeNull();
    });

    test('A REFUSED WRITE RENDERS UNDER THE FORM AND KEEPS WHAT WAS TYPED', async () => {
        const spy = await openEditor([STORED_NAMED], {
            saveRejects: Object.assign(new Error('HTTP 422'), {
                status: 422,
                detail: [{ loc: ['body', 'name'], msg: 'name must not be empty' }],
            }),
        });
        type('#ledger-edit-name', 'day job');
        await press('[data-ledger="edit-save"]');
        expect(one('[data-ledger="edit-refusal"]').textContent ?? '').toContain('name must not be empty');
        expect(one<HTMLInputElement>('#ledger-edit-name').value).toBe('day job');
    });

    test('A REFUSAL IS PAINTED ONCE, IN THE FORM, and not again under the name', async () => {
        const spy = await openEditor([STORED_NAMED]);
        type('#ledger-edit-name', '   ');
        await press('[data-ledger="edit-save"]');
        expect(document.querySelectorAll('[data-ledger="edit-refusal"]')).toHaveLength(1);
        expect(document.querySelectorAll('[data-ledger="row"] [data-ledger="error"]')).toHaveLength(0);
        await press('[data-ledger="edit-cancel"]');
        expect(document.querySelectorAll('[data-ledger="row"] [data-ledger="error"]')).toHaveLength(1);
    });

    test('EVERY CONTROL IS DISABLED WHILE THE WRITE IS IN FLIGHT', async () => {
        const spy = await openEditor([STORED_NAMED], { saveHangs: true });
        type('#ledger-edit-name', 'day job');
        one<HTMLButtonElement>('[data-ledger="edit-save"]').click();
        await settle();
        expect(one<HTMLButtonElement>('[data-ledger="edit-save"]').disabled).toBe(true);
        expect(one<HTMLButtonElement>('[data-ledger="edit-cancel"]').disabled).toBe(true);
        expect(one<HTMLInputElement>('#ledger-edit-name').disabled).toBe(true);
        expect(one<HTMLButtonElement>('[data-ledger="edit"] [data-ledger="color-chip"]').disabled).toBe(true);
        expect(one('[data-ledger="edit-save"]').textContent ?? '').toContain(t('ledger.edit.saving'));
    });

    test('ONE ROW AT A TIME: opening a second editor closes the first', async () => {
        const first = ONE.accounts?.[0] as unknown as Record<string, unknown>;
        const two: ProviderLedger = {
            accounts: [
                { ...first } as never,
                { ...first, id: 'side', name: 'side' } as never,
            ],
            total: { accounts: 2, windows: [] },
            loop: { alive: true, last_pass_at: null },
        };
        const spy = recorder({
            ledger: two,
            accounts: [STORED_NAMED, { ...STORED_NAMED, id: 'side', name: 'side' }],
        });
        await paint(spy.host);
        await press('[data-ledger="row"] [data-ledger="edit-start"]');
        expect(document.querySelectorAll('[data-ledger="edit"]')).toHaveLength(1);
        const controls = document.querySelectorAll<HTMLButtonElement>('[data-ledger="edit-start"]');
        controls[controls.length - 1]?.click();
        await settle();
        expect(document.querySelectorAll('[data-ledger="edit"]')).toHaveLength(1);
        expect(one<HTMLInputElement>('#ledger-edit-name').value).toBe('side');
    });

    test('A ROW THE CONFIGURED LIST DOES NOT HOLD CANNOT BE EDITED AT ALL', async () => {
        const spy = recorder({ ledger: ONE, accounts: [] });
        await paint(spy.host);
        expect(document.querySelector('[data-ledger="row"] [data-ledger="edit-start"]')).toBeNull();
    });
});

describe('logging in from a row', () => {
    test('every row carries the control, not only a broken one', async () => {
        const spy = recorder({ ledger: ONE, accounts: [{ id: 'main', name: 'main' }] });
        await paint(spy.host);
        const login = one<HTMLButtonElement>('[data-ledger="row"] [data-ledger="login"]');
        expect(login.textContent ?? '').toContain(t('ledger.login.again'));
        expect(login.hasAttribute('data-urgent')).toBe(false);
    });

    test('A MISSING CREDENTIAL MAKES IT THE PROMINENT CONTROL', async () => {
        const missing = ledgerWith({ credential_state: 'missing' });
        const spy = recorder({ ledger: missing, accounts: [{ id: 'main', name: 'main' }] });
        await paint(spy.host);
        expect(one('[data-ledger="row"] [data-ledger="login"]').textContent ?? '').toContain(
            t('ledger.login.start'),
        );
        expect(
            one('[data-ledger="row"] [data-ledger="login"]').hasAttribute('data-urgent'),
        ).toBe(true);
    });

    test('AN UNMEASURED ROW IS NOT PROMINENT: unknown is not evidence of a fault', async () => {
        const spy = recorder({
            ledger: NONE,
            accounts: [{ id: 'claude-one', name: 'claude one', provider: 'claude' }],
        });
        await paint(spy.host);
        expect(
            one('[data-ledger="row"] [data-ledger="login"]').hasAttribute('data-urgent'),
        ).toBe(false);
    });

    test('an expired credential makes it the prominent control', async () => {
        const expired = ledgerWith({ credential_state: 'expired' });
        const spy = recorder({ ledger: expired, accounts: [{ id: 'main', name: 'main' }] });
        await paint(spy.host);
        expect(
            one('[data-ledger="row"] [data-ledger="login"]').hasAttribute('data-urgent'),
        ).toBe(true);
    });

    test('pressing it asks the server for this account and enters the pane', async () => {
        const spy = recorder({ ledger: ONE, accounts: [{ id: 'main', name: 'main' }] });
        await paint(spy.host);
        await press('[data-ledger="row"] [data-ledger="login"]');
        expect(spy.entered).toEqual(['ses_main']);
    });

    test('THE OVERLAY COMES DOWN, or it would paint over the pane', async () => {
        const spy = recorder({ ledger: ONE, accounts: [{ id: 'main', name: 'main' }] });
        await paint(spy.host);
        await press('[data-ledger="row"] [data-ledger="login"]');
        expect(document.querySelector('.oc-page')).toBeNull();
    });

    test('A LOGIN ALREADY RUNNING TAKES THE READER TO THAT PANE', async () => {
        const spy = recorder({
            ledger: ONE,
            accounts: [{ id: 'main', name: 'main' }],
            loginRejects: Object.assign(new Error('HTTP 409'), {
                status: 409,
                detail: {
                    code: 'login_in_progress',
                    detail: 'already running',
                    session_id: 'ses_live',
                },
            }),
        });
        await paint(spy.host);
        await press('[data-ledger="row"] [data-ledger="login"]');
        expect(spy.entered).toEqual(['ses_live']);
    });

    test('a directory that could not be made says so on the row, and stays put', async () => {
        const spy = recorder({
            ledger: ONE,
            accounts: [{ id: 'main', name: 'main' }],
            loginRejects: Object.assign(new Error('HTTP 409'), {
                status: 409,
                detail: { code: 'managed_dir_unavailable', detail: 'permission denied' },
            }),
        });
        await paint(spy.host);
        await press('[data-ledger="row"] [data-ledger="login"]');
        expect(spy.entered).toEqual([]);
        expect(one('[data-ledger="row"]').textContent ?? '').toContain('permission denied');
        expect(document.querySelector('.oc-page')).not.toBeNull();
    });

    test('an account the server does not hold says so on the row', async () => {
        const spy = recorder({
            ledger: ONE,
            accounts: [{ id: 'main', name: 'main' }],
            loginRejects: Object.assign(new Error('HTTP 404'), {
                status: 404,
                detail: { code: 'not_found', detail: 'no provider account with the id main' },
            }),
        });
        await paint(spy.host);
        await press('[data-ledger="row"] [data-ledger="login"]');
        expect(one('[data-ledger="row"]').textContent ?? '').toContain(
            'no provider account with the id main',
        );
    });
});
