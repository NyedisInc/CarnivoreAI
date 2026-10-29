import type {
    CardAction,
    LabelVerdict,
    ReopenResult,
    RespawnResult,
    RestartChoice,
    RowActionDescriptor,
    RunningHost,
    ThemeColors,
} from './running-host';
import type { RunningSessionRow } from '../sessions/types';

export interface HostCall {
    method: string;
    args: unknown[];
}

export interface HostAnswers {
    actionsFor?: (status: string | null | undefined) => RowActionDescriptor[];
    cardActions?: CardAction[];
    rowMenuTrigger?: string | null;
    themeColors?: (id: string) => ThemeColors | null;
    transport?: string | undefined;
    confirm?: boolean;
    validateLabel?: (value: string) => LabelVerdict;
    restartChoice?: RestartChoice | null;
    restartError?: string | null;
    hasRestartPicker?: boolean;
    respawn?: RespawnResult | (() => never);
    reopen?: ReopenResult;
    renameSession?: (id: string, label: string) => Promise<unknown>;
    resolveSessionId?: string | null;
}

export interface RecordingHost extends RunningHost {
    calls: HostCall[];
    errors: string[];
}

export function defaultActionsFor(
    status: string | null | undefined,
): RowActionDescriptor[] {
    const key = (status || 'unknown').toLowerCase();
    const make = (id: string): RowActionDescriptor => ({
        id,
        glyph: id === 'remove' ? 'trash' : (id === 'restart' ? 'restart' : 'close'),
        labelKey: `session.action.${id}`,
        extraClass: id === 'restart' ? 'session-row-action-restart' : '',
    });
    if (key === 'dead') return [make('restart'), make('remove')];
    const live = ['working', 'working_subagent', 'question', 'notice',
        'finished_unread', 'idle', 'running'];
    if (live.indexOf(key) !== -1) return [make('close'), make('restart')];
    return [make('close')];
}

export function recordingHost(answers: HostAnswers = {}): RecordingHost {
    const calls: HostCall[] = [];
    const errors: string[] = [];
    const note = (method: string, ...args: unknown[]) => {
        calls.push({ method, args });
    };
    return {
        calls,
        errors,
        actionsFor: answers.actionsFor || defaultActionsFor,
        rowMenuTrigger(): string | null {
            return answers.rowMenuTrigger ?? null;
        },
        cardActions(name: string, unread: boolean): CardAction[] {
            note('cardActions', name, unread);
            return answers.cardActions === undefined
                ? [{ id: 'mark-unread', order: 200,
                    label: unread ? 'clear unread' : 'mark unread' }]
                : answers.cardActions;
        },
        async runCardAction(id: string, name: string, unread: boolean) {
            note('runCardAction', id, name, unread);
            return true;
        },
        themeColors(themeId: string): ThemeColors | null {
            return answers.themeColors ? answers.themeColors(themeId) : null;
        },
        transportFor(): string | undefined {
            return answers.transport;
        },
        labelMaxChars(): number {
            return 200;
        },
        validateLabel(value: string): LabelVerdict {
            note('validateLabel', value);
            if (answers.validateLabel) return answers.validateLabel(value);
            return { ok: true, value };
        },
        async confirmAction(action: string, displayName: string) {
            note('confirmAction', action, displayName);
            return answers.confirm !== false;
        },
        requiresConfirm(action: string): boolean {
            return action !== 'restart';
        },
        actionLabel(action: string): string {
            return `${action} session`;
        },
        async renameSession(sessionId: string, label: string) {
            note('renameSession', sessionId, label);
            if (answers.renameSession) return answers.renameSession(sessionId, label);
            return undefined;
        },
        async destroySession(sessionId: string) {
            note('destroySession', sessionId);
            return undefined;
        },
        async destroyExternalSession(name: string) {
            note('destroyExternalSession', name);
            return undefined;
        },
        async resolveSessionId(tmuxName: string) {
            note('resolveSessionId', tmuxName);
            return answers.resolveSessionId ?? null;
        },
        async openRestartPicker(name: string, display: string, status: string | null) {
            note('openRestartPicker', name, display, status);
            return answers.restartChoice ?? null;
        },
        restartPickerError(): string | null {
            return answers.restartError ?? null;
        },
        hasRestartPicker(): boolean {
            return answers.hasRestartPicker !== false;
        },
        async respawnSession(name: string, agentType: string | null, live: boolean) {
            note('respawnSession', name, agentType, live);
            const answer = answers.respawn;
            if (typeof answer === 'function') return answer();
            return answer ?? { ok: true };
        },
        async reopenAfterRestart(result: RespawnResult): Promise<ReopenResult> {
            note('reopenAfterRestart', result);
            return answers.reopen ?? { status: 'not_reopened', detail: null };
        },
        async forkSession(name: string) {
            note('forkSession', name);
        },
        async returnToActive(sessionId: string | null) {
            note('returnToActive', sessionId);
        },
        async attachSession(name: string) {
            note('attachSession', name);
        },
        async refresh() {
            note('refresh');
        },
        showError(message: string): void {
            errors.push(message);
        },
    };
}

export function testTranslate(
    key: string,
    params?: Record<string, unknown> | null,
): string {
    const values = params ? Object.values(params) : [];
    return values.length ? `${key} ${values.join(' ')}` : key;
}

export function row(
    name: string,
    patch: Partial<RunningSessionRow> = {},
): RunningSessionRow {
    return {
        name,
        label: null,
        created_by_cloude: true,
        created_at_epoch: 1_700_000_000,
        window_count: 1,
        agent_type: 'claude',
        agent_family: 'claude',
        agent_family_source: 'wrapper',
        agent_wrapper_label: null,
        pinned_theme: null,
        session_row_id: 7,
        parent_session_id: null,
        status: 'idle',
        unread: false,
        listing_ok: true,
        listing_reason: null,
        is_active: false,
        session_id: null,
        startup_gate: 'ready',
        status_source: 'hook',
        ...patch,
    };
}
