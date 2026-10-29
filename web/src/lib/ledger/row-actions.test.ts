import { describe, expect, test } from 'vitest';

import { removeRow, saveRowEdit, startLogin, type RowActionDeps } from './row-actions';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { LedgerHost, LoginStarted } from './ledger-host';
import type { AccountBody, StoredAccount } from './accounts-model';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const STORED: StoredAccount = {
    id: 'claude-one',
    name: 'claude one',
    provider: 'claude',
    claude_config_dir: '/Users/a/.carnivore/accounts/claude-one',
    codex_home: '~/.codex',
    managed: true,
    color: null,
};

function refusal(status: number, detail: unknown): Error {
    const error = new Error('refused') as Error & { status: number; detail: unknown };
    error.status = status;
    error.detail = detail;
    return error;
}

interface Answers {
    login?: LoginStarted | Error;
    save?: Error;
    remove?: Error;
    removeAnswer?: unknown;
    stored?: StoredAccount | null;
    stale?: boolean;
}

interface Recorder {
    deps: RowActionDeps;
    calls: string[];
    saved: Array<{ id: string; body: AccountBody }>;
    entered: string[];
    notices: Array<{ id: string; message: string | null }>;
    busy: Array<{ kind: string; id: string | null }>;
    closed: number;
}

function recorder(answers: Answers = {}): Recorder {
    const calls: string[] = [];
    const saved: Array<{ id: string; body: AccountBody }> = [];
    const entered: string[] = [];
    const notices: Array<{ id: string; message: string | null }> = [];
    const busy: Array<{ kind: string; id: string | null }> = [];
    const state = { closed: 0 };
    const host = {
        providerLedger: () => Promise.reject(new Error('not used here')),
        listAccounts: () => Promise.reject(new Error('not used here')),
        saveAccount: (id: string, body: AccountBody) => {
            calls.push('save');
            saved.push({ id, body });
            return answers.save ? Promise.reject(answers.save) : Promise.resolve({ id });
        },
        removeAccount: (id: string) => {
            calls.push('remove:' + id);
            if (answers.remove) return Promise.reject(answers.remove);
            return Promise.resolve(
                answers.removeAnswer ?? { removed: id, logout: 'ok', directory: 'removed' },
            );
        },
        loginProviderAccount: (id: string) => {
            calls.push('login:' + id);
            const answer = answers.login ?? { session_id: 'ses_new', tmux_session: 'cloude_x' };
            return answer instanceof Error
                ? Promise.reject(answer)
                : Promise.resolve(answer as LoginStarted);
        },
        openSession: (sessionId: string) => {
            calls.push('open:' + sessionId);
            entered.push(sessionId);
            return Promise.resolve();
        },
    } as LedgerHost;
    const deps: RowActionDeps = {
        host,
        t,
        stored: () => ('stored' in answers ? (answers.stored ?? null) : STORED),
        busy: (kind, id) => busy.push({ kind, id }),
        isBusy: () => false,
        notice: (id, message) => notices.push({ id, message }),
        reread: () => {
            calls.push('reread');
            return Promise.resolve();
        },
        close: () => {
            calls.push('close');
            state.closed += 1;
        },
        begin: () => 'token',
        keep: () => !answers.stale,
    };
    return {
        deps,
        calls,
        saved,
        entered,
        notices,
        busy,
        get closed() {
            return state.closed;
        },
    };
}

describe('starting a login from a row', () => {
    test('it asks the server for this account and no other', async () => {
        const spy = recorder();
        await startLogin('claude-one', spy.deps);
        expect(spy.calls).toContain('login:claude-one');
    });

    test('THE SCREEN COMES DOWN BEFORE THE SESSION IS ENTERED', async () => {
        const spy = recorder();
        await startLogin('claude-one', spy.deps);
        expect(spy.calls.indexOf('close')).toBeLessThan(spy.calls.indexOf('open:ses_new'));
    });

    test('the session the server opened is the one entered', async () => {
        const spy = recorder();
        await startLogin('claude-one', spy.deps);
        expect(spy.entered).toEqual(['ses_new']);
    });

    test('A STALE NAVIGATION DISCARDS SILENTLY: no screen change, no error', async () => {
        const spy = recorder({ stale: true });
        await startLogin('claude-one', spy.deps);
        expect(spy.entered).toEqual([]);
        expect(spy.closed).toBe(0);
        expect(spy.notices.filter((entry) => entry.message !== null)).toEqual([]);
    });

    test('the row is marked busy while the request is out, and cleared after', async () => {
        const spy = recorder();
        await startLogin('claude-one', spy.deps);
        expect(spy.busy).toEqual([
            { kind: 'login', id: 'claude-one' },
            { kind: 'login', id: null },
        ]);
    });

    test('a second press while one is in flight asks for nothing', async () => {
        const spy = recorder();
        spy.deps.isBusy = () => true;
        await startLogin('claude-one', spy.deps);
        expect(spy.calls).toEqual([]);
    });
});

describe('a login that is already running', () => {
    const inProgress = refusal(409, {
        code: 'login_in_progress',
        detail: 'a login for claude-one is already running',
        session_id: 'ses_live',
        tmux_session: 'cloude_login_claude_one',
    });

    test('IT NAVIGATES TO THE PANE THAT IS ALREADY OPEN', async () => {
        const spy = recorder({ login: inProgress });
        await startLogin('claude-one', spy.deps);
        expect(spy.entered).toEqual(['ses_live']);
    });

    test('it takes the screen down first, exactly as a fresh login does', async () => {
        const spy = recorder({ login: inProgress });
        await startLogin('claude-one', spy.deps);
        expect(spy.calls.indexOf('close')).toBeLessThan(spy.calls.indexOf('open:ses_live'));
    });

    test('IT IS NOT REPORTED AS A FAILURE, because nothing failed', async () => {
        const spy = recorder({ login: inProgress });
        await startLogin('claude-one', spy.deps);
        expect(spy.notices.filter((entry) => entry.message !== null)).toEqual([]);
    });

    test('a 409 with no session to go to is reported rather than swallowed', async () => {
        const spy = recorder({
            login: refusal(409, { code: 'login_in_progress', detail: 'already running' }),
        });
        await startLogin('claude-one', spy.deps);
        expect(spy.entered).toEqual([]);
        expect(spy.notices.at(-1)?.message).toContain(t('ledger.login.in_progress'));
    });
});

describe('a login that could not start', () => {
    test('a directory that could not be made says so, on the row', async () => {
        const spy = recorder({
            login: refusal(409, {
                code: 'managed_dir_unavailable',
                detail: 'permission denied',
            }),
        });
        await startLogin('claude-one', spy.deps);
        expect(spy.entered).toEqual([]);
        expect(spy.notices.at(-1)).toEqual({
            id: 'claude-one',
            message: t('ledger.login.dir_unavailable', { reason: 'permission denied' }),
        });
    });

    test('an account the server does not hold says so, on the row', async () => {
        const spy = recorder({
            login: refusal(404, { code: 'not_found', detail: 'no provider account' }),
        });
        await startLogin('claude-one', spy.deps);
        expect(spy.notices.at(-1)?.message).toBe(
            t('ledger.login.failed', { reason: 'no provider account' }),
        );
    });

    test('the busy mark is cleared even when the request threw', async () => {
        const spy = recorder({ login: refusal(500, 'boom') });
        await startLogin('claude-one', spy.deps);
        expect(spy.busy.at(-1)).toEqual({ kind: 'login', id: null });
    });

    test('an old notice is cleared before a new attempt is made', async () => {
        const spy = recorder();
        await startLogin('claude-one', spy.deps);
        expect(spy.notices[0]).toEqual({ id: 'claude-one', message: null });
    });
});

describe('editing a row that already exists', () => {
    test('THE STORED ROW GOES BACK WHOLE, with only the name and the colour changed', async () => {
        const spy = recorder();
        await saveRowEdit('claude-one', { name: 'day job', color: '#818cf8' }, spy.deps);
        expect(spy.saved).toEqual([
            {
                id: 'claude-one',
                body: {
                    name: 'day job',
                    provider: 'claude',
                    managed: true,
                    color: '#818cf8',
                },
            },
        ]);
    });

    test('THE WRITE IS ADDRESSED AT THE STORED ID EVEN WHEN THE NAME CHANGES', async () => {
        const spy = recorder();
        await saveRowEdit('claude-one', { name: 'day job', color: null }, spy.deps);
        expect(spy.saved[0]?.id).toBe('claude-one');
        expect(spy.saved[0]?.id).not.toBe('day-job');
    });

    test('an unmanaged row keeps both pointers exactly as stored', async () => {
        const spy = recorder({
            stored: {
                id: 'work',
                name: 'work',
                provider: 'claude',
                claude_config_dir: '~/.claude-work',
                codex_home: '~/.codex-side',
                managed: false,
                color: null,
            },
        });
        await saveRowEdit('work', { name: 'work', color: '#f472b6' }, spy.deps);
        expect(spy.saved[0]?.body).toEqual({
            name: 'work',
            provider: 'claude',
            managed: false,
            color: '#f472b6',
            claude_config_dir: '~/.claude-work',
            codex_home: '~/.codex-side',
        });
    });

    test('the table is re-read once the write lands', async () => {
        const spy = recorder();
        await saveRowEdit('claude-one', { name: 'claude one', color: '#818cf8' }, spy.deps);
        expect(spy.calls).toEqual(['save', 'reread']);
    });

    test('a colour can be taken back off', async () => {
        const spy = recorder();
        await saveRowEdit('claude-one', { name: 'claude one', color: null }, spy.deps);
        expect(spy.saved[0]?.body.color).toBeNull();
    });

    test('a colour the palette never offered still goes on the wire', async () => {
        const spy = recorder();
        await saveRowEdit('claude-one', { name: 'claude one', color: '#123456' }, spy.deps);
        expect(spy.saved[0]?.body.color).toBe('#123456');
    });

    test('IT ANSWERS WHETHER THE WRITE LANDED, so the form knows to close', async () => {
        const spy = recorder();
        expect(
            await saveRowEdit('claude-one', { name: 'day job', color: null }, spy.deps),
        ).toBe(true);
    });

    test('A ROW THAT IS NOT IN THE CONFIGURED LIST IS NOT WRITTEN AT ALL', async () => {
        const spy = recorder({ stored: null });
        expect(await saveRowEdit('ghost', { name: 'ghost', color: '#818cf8' }, spy.deps)).toBe(
            false,
        );
        expect(spy.calls).toEqual([]);
        expect(spy.notices.at(-1)?.message).toBe(t('ledger.edit.no_row'));
    });

    test('A BLANK NAME IS NOT WRITTEN AND THE FORM STAYS OPEN', async () => {
        const spy = recorder();
        expect(await saveRowEdit('claude-one', { name: '  ', color: null }, spy.deps)).toBe(false);
        expect(spy.calls).toEqual([]);
        expect(spy.notices.at(-1)?.message).toBe(t('ledger.editor.name_blank'));
    });

    test('a refused write says so on the row and answers false', async () => {
        const spy = recorder({ save: refusal(422, 'color must be lowercase six digit hex') });
        expect(
            await saveRowEdit('claude-one', { name: 'claude one', color: '#818cf8' }, spy.deps),
        ).toBe(false);
        expect(spy.notices.at(-1)?.message).toBe(
            t('ledger.edit.failed', { reason: 'color must be lowercase six digit hex' }),
        );
    });

    test('the row is marked busy while the write is in flight and freed after', async () => {
        const spy = recorder();
        await saveRowEdit('claude-one', { name: 'day job', color: null }, spy.deps);
        expect(spy.busy).toEqual([
            { kind: 'edit', id: 'claude-one' },
            { kind: 'edit', id: null },
        ]);
    });
});

describe('removing a row, which moved here with the other two', () => {
    test('it asks the server to forget this account, then re-reads', async () => {
        const spy = recorder();
        await removeRow('claude-one', spy.deps);
        expect(spy.calls).toEqual(['remove:claude-one', 'reread']);
    });

    test('A REFUSED REMOVE LEAVES THE ROW, and says why on it', async () => {
        const spy = recorder({ remove: refusal(500, 'config.json is not writable') });
        await removeRow('claude-one', spy.deps);
        expect(spy.calls).toEqual(['remove:claude-one']);
        expect(spy.notices.at(-1)?.message).toBe(
            t('ledger.editor.remove_failed', { reason: 'config.json is not writable' }),
        );
    });

    test('a second press while one is in flight asks for nothing', async () => {
        const spy = recorder();
        spy.deps.isBusy = () => true;
        await removeRow('claude-one', spy.deps);
        expect(spy.calls).toEqual([]);
    });

    test('an ordinary removal says nothing beyond clearing the row', async () => {
        const spy = recorder();
        await removeRow('claude-one', spy.deps);
        expect(spy.notices).toEqual([{ id: 'claude-one', message: null }]);
    });

    test('an unmanaged removal, whose directory is kept, also says nothing', async () => {
        const spy = recorder({
            removeAnswer: { removed: 'claude-one', logout: 'skipped', directory: 'kept' },
        });
        await removeRow('claude-one', spy.deps);
        expect(spy.notices).toEqual([{ id: 'claude-one', message: null }]);
    });

    test('A LOGIN AREA THE SERVER WOULD NOT DELETE IS SAID OUT LOUD', async () => {
        const spy = recorder({
            removeAnswer: { removed: 'claude-one', logout: 'ok', directory: 'refused' },
        });
        await removeRow('claude-one', spy.deps);
        expect(spy.notices.at(-1)?.message).toBe(t('ledger.editor.remove_dir_refused'));
    });

    test('and the row stays up, because a sentence on a row nobody can see is no sentence', async () => {
        const spy = recorder({
            removeAnswer: { removed: 'claude-one', logout: 'ok', directory: 'refused' },
        });
        await removeRow('claude-one', spy.deps);
        expect(spy.calls).toEqual(['remove:claude-one']);
    });

    test('a failed logout alone is not worth a sentence: the account is gone', async () => {
        const spy = recorder({
            removeAnswer: { removed: 'claude-one', logout: 'failed', directory: 'removed' },
        });
        await removeRow('claude-one', spy.deps);
        expect(spy.notices).toEqual([{ id: 'claude-one', message: null }]);
    });
});
