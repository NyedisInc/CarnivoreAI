import { beginNav, keepNav } from '../launchpad/nav-generation';
import { LEDGER_KEYS } from './ledger-model';
import {
    refusalText,
    storedAccountBody,
    type AccountEdit,
    type StoredAccount,
} from './accounts-model';
import { showToast } from '../widgets-page/undo-toast';
import type { LedgerHost } from './ledger-host';
import type { Translate } from '../sessions/types';

export type RowBusyKind = 'login' | 'edit' | 'remove';

export interface RowActionDeps {
    host: LedgerHost;
    t: Translate;
    stored(id: string): StoredAccount | null;
    busy(kind: RowBusyKind, id: string | null): void;
    isBusy(kind: RowBusyKind): boolean;
    notice(id: string, message: string | null): void;
    reread(): Promise<void>;
    close(): void;
    begin?(target: string): unknown;
    keep?(token: unknown, what: string): boolean;
}

type LoginRefusal =
    | { kind: 'in_progress'; sessionId: string }
    | { kind: 'in_progress_unnamed' }
    | { kind: 'dir_unavailable' }
    | { kind: 'other' };

function loginRefusal(error: unknown): LoginRefusal {
    const detail = (error as { detail?: unknown } | null)?.detail;
    if (!detail || typeof detail !== 'object') return { kind: 'other' };
    const code = (detail as { code?: unknown }).code;
    if (code === 'managed_dir_unavailable') return { kind: 'dir_unavailable' };
    if (code !== 'login_in_progress') return { kind: 'other' };
    const sessionId = (detail as { session_id?: unknown }).session_id;
    if (typeof sessionId === 'string' && sessionId) return { kind: 'in_progress', sessionId };
    return { kind: 'in_progress_unnamed' };
}

async function enterSession(
    sessionId: string,
    token: unknown,
    deps: RowActionDeps,
): Promise<void> {
    const keep = deps.keep ?? keepNav;
    if (!keep(token, 'ledger login')) return;
    deps.close();
    await deps.host.openSession(sessionId);
}

export async function startLogin(accountId: string, deps: RowActionDeps): Promise<void> {
    if (deps.isBusy('login')) return;
    const token = (deps.begin ?? beginNav)('ledger-login:' + accountId);
    deps.busy('login', accountId);
    deps.notice(accountId, null);
    try {
        const started = await deps.host.loginProviderAccount(accountId);
        if (started.device_auth) {
            showToast({
                kind: 'saved',
                text: deps.t(LEDGER_KEYS.loginDeviceAuth),
                surface: deps.t(LEDGER_KEYS.loginStart),
                ms: 20000,
            });
        }
        await enterSession(started.session_id, token, deps);
    } catch (error) {
        const refused = loginRefusal(error);
        if (refused.kind === 'in_progress') {
            await enterSession(refused.sessionId, token, deps);
        } else if (refused.kind === 'in_progress_unnamed') {
            deps.notice(accountId, deps.t(LEDGER_KEYS.loginInProgress));
        } else if (refused.kind === 'dir_unavailable') {
            deps.notice(
                accountId,
                deps.t(LEDGER_KEYS.loginDirUnavailable, {
                    reason: refusalText(error, deps.t),
                }),
            );
        } else {
            deps.notice(
                accountId,
                deps.t(LEDGER_KEYS.loginFailed, { reason: refusalText(error, deps.t) }),
            );
        }
    } finally {
        deps.busy('login', null);
    }
}

export async function saveRowEdit(
    accountId: string,
    edit: AccountEdit,
    deps: RowActionDeps,
): Promise<boolean> {
    if (deps.isBusy('edit')) return false;
    const stored = deps.stored(accountId);
    if (!edit.name.trim()) {
        deps.notice(accountId, deps.t(LEDGER_KEYS.editorNameBlank));
        return false;
    }
    const body = stored === null ? null : storedAccountBody(stored, edit);
    if (body === null) {
        deps.notice(accountId, deps.t(LEDGER_KEYS.editNoRow));
        return false;
    }
    deps.busy('edit', accountId);
    deps.notice(accountId, null);
    try {
        await deps.host.saveAccount(accountId, body);
        await deps.reread();
        return true;
    } catch (error) {
        deps.notice(
            accountId,
            deps.t(LEDGER_KEYS.editFailed, { reason: refusalText(error, deps.t) }),
        );
        return false;
    } finally {
        deps.busy('edit', null);
    }
}

/* the built-in login */
export async function renameBuiltInLogin(
    accountId: string,
    label: string,
    deps: RowActionDeps,
): Promise<boolean> {
    const rename = deps.host.renameBuiltInLogin;
    if (!rename || deps.isBusy('edit')) return false;
    deps.busy('edit', accountId);
    deps.notice(accountId, null);
    try {
        await rename.call(deps.host, label.trim() === '' ? null : label.trim());
        await deps.reread();
        return true;
    } catch (error) {
        deps.notice(
            accountId,
            deps.t(LEDGER_KEYS.editFailed, { reason: refusalText(error, deps.t) }),
        );
        return false;
    } finally {
        deps.busy('edit', null);
    }
}

function directoryWasRefused(answer: unknown): boolean {
    if (!answer || typeof answer !== 'object') return false;
    return (answer as { directory?: unknown }).directory === 'refused';
}

export async function removeRow(accountId: string, deps: RowActionDeps): Promise<void> {
    if (deps.isBusy('remove')) return;
    deps.busy('remove', accountId);
    deps.notice(accountId, null);
    try {
        const answer = await deps.host.removeAccount(accountId);
        if (directoryWasRefused(answer)) {
            deps.notice(accountId, deps.t(LEDGER_KEYS.editorRemoveDirRefused));
            return;
        }
        await deps.reread();
    } catch (error) {
        deps.notice(
            accountId,
            deps.t(LEDGER_KEYS.editorRemoveFailed, { reason: refusalText(error, deps.t) }),
        );
    } finally {
        deps.busy('remove', null);
    }
}
