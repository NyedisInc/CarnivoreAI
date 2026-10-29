import {
    RUNNING_SESSION_KEYS,
    rowActionFailed,
} from '../../../../client/js/labels/running-session.js';
import { sessionDisplayLabel } from '../sessions/session-label';
import type { RunningSessionRow, Translate } from '../sessions/types';
import { ApiUnavailableError, type RunningHost } from './running-host';

export const ACTION_CLOSE = 'close';
export const ACTION_REMOVE = 'remove';
export const ACTION_RESTART = 'restart';

/* a network failure */
export function reasonFrom(error: unknown, t: Translate): string {
    if (error instanceof ApiUnavailableError) {
        return t(RUNNING_SESSION_KEYS.apiUnavailable);
    }
    if (error && typeof error === 'object' && 'message' in error) {
        const message = (error as { message?: unknown }).message;
        if (typeof message === 'string' && message.trim()) return message;
    }
    if (typeof error === 'string' && error.trim()) return error;
    return t(RUNNING_SESSION_KEYS.serverUnreachable);
}

export async function runRowAction(
    row: RunningSessionRow,
    action: string,
    host: RunningHost,
    t: Translate,
): Promise<void> {
    const tmuxName = row && row.name;
    if (!tmuxName) return;
    const display = sessionDisplayLabel(row);
    if (action === ACTION_RESTART) {
        await restartSession(row, host, t);
        return;
    }
    if (host.requiresConfirm(action)) {
        const confirmed = await host.confirmAction(action, display);
        if (!confirmed) return;
    }
    try {
        const sid = row.session_id || (await host.resolveSessionId(tmuxName));
        if (sid) {
            await host.destroySession(sid);
        } else {
            await host.destroyExternalSession(tmuxName);
        }
    } catch (error) {
        host.showError(rowActionFailed(
            host.actionLabel(action), reasonFrom(error, t), t,
        ));
    }
    await host.refresh();
}

/* could not be read */
export async function restartSession(
    row: RunningSessionRow,
    host: RunningHost,
    t: Translate,
): Promise<void> {
    const tmuxName = row.name;
    const display = sessionDisplayLabel(row);
    const choice = await host.openRestartPicker(
        tmuxName, display, row.status ?? null,
    );
    if (!choice) {
        const why = host.restartPickerError();
        if (why) {
            host.showError(t(RUNNING_SESSION_KEYS.respawnUnpredictable, {
                name: display, reason: why,
            }));
        } else if (!host.hasRestartPicker()) {
            host.showError(t(RUNNING_SESSION_KEYS.respawnNoPicker, {
                name: display,
            }));
        }
        return;
    }

    let result: RespawnLike = null;
    try {
        result = await host.respawnSession(
            tmuxName, choice.agentType ?? null, choice.confirmRestartLive === true,
        );
    } catch (error) {
        host.showError(t(RUNNING_SESSION_KEYS.respawnFailed, {
            name: display, reason: reasonFrom(error, t),
        }));
        await host.refresh();
        return;
    }
    if (!result || result.ok !== true) {
        host.showError(t(RUNNING_SESSION_KEYS.respawnFailed, {
            name: display,
            reason: (result && result.detail)
                || t(RUNNING_SESSION_KEYS.respawnNoReason),
        }));
        await host.refresh();
        return;
    }
    if (choice.agentType && result.agent_type_persisted === false) {
        host.showError(t(RUNNING_SESSION_KEYS.respawnChoiceUnsaved, {
            name: display, agent: choice.agentType,
        }));
    }
    const back = await host.reopenAfterRestart(result);
    if (back.status === 'reopened') return;
    if (back.detail) host.showError(back.detail);
    else if (back.status === 'not_reopened') {
        host.showError(t(RUNNING_SESSION_KEYS.respawnNoReopen));
    }
    await host.refresh();
}

type RespawnLike = { ok?: boolean; detail?: string | null;
    agent_type_persisted?: boolean } | null;

export interface RenameOutcome {
    state: 'saved' | 'unchanged' | 'refused';
    reason: string | null;
}

export async function saveRename(
    sessionId: string,
    raw: string,
    seed: string,
    host: RunningHost,
    t: Translate,
): Promise<RenameOutcome> {
    const typed = (raw || '').trim();
    if (!typed || typed === seed) {
        return { state: 'unchanged', reason: null };
    }
    const verdict = host.validateLabel(typed);
    if (!verdict.ok) {
        return {
            state: 'refused',
            reason: verdict.reason
                || t(RUNNING_SESSION_KEYS.renameRuleUnavailable),
        };
    }
    try {
        await host.renameSession(sessionId, verdict.value ?? typed);
    } catch (error) {
        return { state: 'refused', reason: renameFailureText(error, t) };
    }
    await host.refresh();
    return { state: 'saved', reason: null };
}

export function renameFailureText(error: unknown, t: Translate): string {
    const message = reasonFrom(error, t);
    if (/409/.test(message) || /already in use/i.test(message)) {
        return t(RUNNING_SESSION_KEYS.renameFailedInUse);
    }
    if (/400/.test(message) || /Invalid session name/i.test(message)) {
        return t(RUNNING_SESSION_KEYS.renameFailedInvalid);
    }
    if (/404/.test(message)) {
        return t(RUNNING_SESSION_KEYS.renameFailedMissing);
    }
    return message || t(RUNNING_SESSION_KEYS.renameFailed);
}
