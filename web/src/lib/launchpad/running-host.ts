import { contextFromRow, triggerHtml } from '../item-menu/row-context';
import { hostWindow } from '../sessions/env';
import { t } from '../i18n/index.svelte';
import { attachRunningSession, returnToActiveSession } from './navigation';
import { browserNavHost } from './nav-host';

export interface RowActionDescriptor {
    id: string;
    glyph: string;
    labelKey: string;
    extraClass: string;
}

export interface RestartChoice {
    agentType?: string | null;
    confirmRestartLive?: boolean;
}

export interface RespawnResult {
    ok?: boolean;
    detail?: string | null;
    agent_type_persisted?: boolean;
    [key: string]: unknown;
}

export interface ReopenResult {
    status: string;
    detail?: string | null;
}

export class ApiUnavailableError extends Error {
    constructor() {
        super('api_unavailable');
        this.name = 'ApiUnavailableError';
    }
}

export interface LabelVerdict {
    ok: boolean;
    reason?: string;
    value?: string;
}

export interface CardAction {
    id: string;
    label: string;
    order: number;
}

export interface ThemeColors {
    accent: string;
    label: string;
}

export interface RunningHost {
    actionsFor(status: string | null | undefined): RowActionDescriptor[];
    rowMenuTrigger(
        row: object, rename: { renameable: boolean; reason: string },
    ): string | null;
    cardActions(name: string, unread: boolean, status?: string | null): CardAction[];
    runCardAction(id: string, name: string, unread: boolean): Promise<boolean>;
    themeColors(themeId: string): ThemeColors | null;
    transportFor(name: string): string | undefined;
    labelMaxChars(): number;
    validateLabel(value: string): LabelVerdict;

    confirmAction(action: string, displayName: string): Promise<boolean>;
    requiresConfirm(action: string): boolean;
    actionLabel(action: string): string;
    renameSession(sessionId: string, label: string): Promise<unknown>;
    destroySession(sessionId: string): Promise<unknown>;
    destroyExternalSession(name: string): Promise<unknown>;
    resolveSessionId(tmuxName: string): Promise<string | null>;
    openRestartPicker(
        tmuxName: string,
        display: string,
        status: string | null,
    ): Promise<RestartChoice | null>;
    restartPickerError(): string | null;
    /* failed to load */
    hasRestartPicker(): boolean;
    respawnSession(
        tmuxName: string,
        agentType: string | null,
        confirmLive: boolean,
    ): Promise<RespawnResult>;
    reopenAfterRestart(result: RespawnResult): Promise<ReopenResult>;
    forkSession(tmuxName: string): Promise<void>;
    returnToActive(sessionId: string | null): Promise<void>;
    attachSession(name: string): Promise<void>;
    refresh(): Promise<void>;
    showError(message: string): void;
}

interface LegacyRowActions {
    ACTION_CLOSE: string;
    ACTION_REMOVE: string;
    ACTION_RESTART: string;
    actionsFor(status: string | null | undefined): string[];
    offersMenu?(status: string | null | undefined): boolean;
    labelFor(action: string): string;
    requiresConfirm(action: string): boolean;
    confirm(action: string, displayName: string): Promise<boolean>;
}

interface LegacyWindow {
    SessionRowActions?: LegacyRowActions;
    SessionThemeTint?: { colorsFor(id: string): ThemeColors | null };
    SessionTransport?: { stateFor(name: string): string | undefined };
    SessionLabel?: { LABEL_MAX_CHARS?: number; validate?(v: string): LabelVerdict };
    SessionRestartPicker?: {
        open(n: string, d: string, s: string | null): Promise<RestartChoice | null>;
        lastError(): string | null;
    };
    SessionRestartReturn?: { reopen(r: RespawnResult): Promise<ReopenResult> };
    UIFlags?: { showMarkUnreadControl(): boolean };
    API?: {
        renameSession(id: string, label: string): Promise<unknown>;
        destroySession(id: string): Promise<unknown>;
        destroyExternalSession(name: string): Promise<unknown>;
        listSessions?(): Promise<unknown[]>;
        respawnSession(
            name: string, agentType: string | null, confirmLive: boolean,
        ): Promise<RespawnResult>;
    };
    Launchpad?: {
        showError?(message: string): void;
        _returnToActiveRunningSession?(id: string | null): Promise<void>;
        _handleAttachRunningSession?(name: string): Promise<void>;
    };
    CloudeWeb?: {
        launchpad?: {
            forkSession?(name: string | null): Promise<void>;
            loadRunningSessions?(): Promise<void>;
        };
        sessionCardMenuItems?(row: unknown, ctx: unknown): CardAction[];
        runSessionCardAction?(
            id: string, row: unknown, ctx: unknown,
        ): Promise<boolean>;
    };
}

const ACTION_GLYPHS: Record<string, string> = {
    close: 'close',
    remove: 'trash',
    restart: 'restart',
};

const ACTION_LABEL_KEYS: Record<string, string> = {
    close: 'session.action.close',
    remove: 'session.action.remove',
    restart: 'session.action.restart',
};

function legacy(): LegacyWindow {
    return (hostWindow() as unknown as LegacyWindow) || {};
}

/* that does nothing */
function missing(what: string): void {
    console.error('CloudeWeb: the running-sessions list could not reach', what);
}

function pluginFlags(): Record<string, boolean> {
    const flags = legacy().UIFlags;
    return {
        show_mark_unread_control: flags ? flags.showMarkUnreadControl() : true,
    };
}

export function browserRunningHost(): RunningHost {
    return {
        actionsFor(status: string | null | undefined): RowActionDescriptor[] {
            const mod = legacy().SessionRowActions;
            if (!mod || typeof mod.actionsFor !== 'function') {
                missing('SessionRowActions.actionsFor');
                // could not be read
                return [];
            }
            return mod.actionsFor(status).map((id) => ({
                id,
                glyph: ACTION_GLYPHS[id] ?? 'close',
                labelKey: ACTION_LABEL_KEYS[id] ?? ACTION_LABEL_KEYS.close!,
                extraClass: id === mod.ACTION_RESTART
                    ? 'session-row-action-restart'
                    : '',
            }));
        },
        rowMenuTrigger(row, rename) {
            const actions = legacy().SessionRowActions;
            if (!actions || typeof actions.offersMenu !== 'function') return null;
            const status = (row as { status?: string | null }).status;
            if (!actions.offersMenu(status)) return null;
            return triggerHtml(contextFromRow(row as Record<string, unknown>, {
                surface: 'home',
                renameable: rename.renameable,
                renameReason: rename.renameable ? '' : rename.reason,
            }));
        },
        cardActions(name: string, unread: boolean, status?: string | null): CardAction[] {
            const web = legacy().CloudeWeb;
            if (!web || typeof web.sessionCardMenuItems !== 'function') {
                // failed to load
                missing('CloudeWeb.sessionCardMenuItems');
                return [];
            }
            const items = web.sessionCardMenuItems(
                { name, unread },
                { flags: pluginFlags(), refresh: () => {} },
            );
            const working = status === 'working' || status === 'working_subagent';
            return working && !unread ? items.filter((a) => a.id !== 'mark-unread') : items;
        },
        async runCardAction(
            id: string, name: string, unread: boolean,
        ): Promise<boolean> {
            const web = legacy().CloudeWeb;
            if (!web || typeof web.runSessionCardAction !== 'function') {
                missing('CloudeWeb.runSessionCardAction');
                return false;
            }
            const refresh = async () => {
                await this.refresh();
            };
            return web.runSessionCardAction(
                id, { name, unread }, { flags: pluginFlags(), refresh },
            );
        },
        themeColors(themeId: string): ThemeColors | null {
            const tint = legacy().SessionThemeTint;
            if (!tint || typeof tint.colorsFor !== 'function') return null;
            return tint.colorsFor(themeId);
        },
        transportFor(name: string): string | undefined {
            const transport = legacy().SessionTransport;
            if (!transport || typeof transport.stateFor !== 'function') {
                return undefined;
            }
            return transport.stateFor(name);
        },
        labelMaxChars(): number {
            const mod = legacy().SessionLabel;
            return (mod && mod.LABEL_MAX_CHARS) || 200;
        },
        validateLabel(value: string): LabelVerdict {
            const mod = legacy().SessionLabel;
            if (!mod || typeof mod.validate !== 'function') {
                missing('SessionLabel.validate');
                return { ok: false };
            }
            return mod.validate(value);
        },
        async confirmAction(action: string, displayName: string): Promise<boolean> {
            const mod = legacy().SessionRowActions;
            if (!mod || typeof mod.confirm !== 'function') {
                // FAIL CLOSED. A destructive action must never proceed
                missing('SessionRowActions.confirm');
                return false;
            }
            return mod.confirm(action, displayName);
        },
        requiresConfirm(action: string): boolean {
            const mod = legacy().SessionRowActions;
            if (!mod || typeof mod.requiresConfirm !== 'function') return true;
            return mod.requiresConfirm(action);
        },
        actionLabel(action: string): string {
            const mod = legacy().SessionRowActions;
            if (!mod || typeof mod.labelFor !== 'function') return action;
            return mod.labelFor(action);
        },
        async renameSession(sessionId: string, label: string): Promise<unknown> {
            const api = legacy().API;
            if (!api) throw new ApiUnavailableError();
            return api.renameSession(sessionId, label);
        },
        async destroySession(sessionId: string): Promise<unknown> {
            const api = legacy().API;
            if (!api) throw new ApiUnavailableError();
            return api.destroySession(sessionId);
        },
        async destroyExternalSession(name: string): Promise<unknown> {
            const api = legacy().API;
            if (!api) throw new ApiUnavailableError();
            return api.destroyExternalSession(name);
        },
        async resolveSessionId(tmuxName: string): Promise<string | null> {
            const api = legacy().API;
            if (!api || typeof api.listSessions !== 'function') return null;
            const live = await api.listSessions();
            if (!Array.isArray(live)) return null;
            const match = live.find((row) => {
                const info = row as { tmux_session?: string };
                return info && info.tmux_session === tmuxName;
            }) as { session?: { id?: string }; id?: string } | undefined;
            if (!match) return null;
            return (match.session && match.session.id) || match.id || null;
        },
        async openRestartPicker(
            tmuxName: string, display: string, status: string | null,
        ): Promise<RestartChoice | null> {
            const picker = legacy().SessionRestartPicker;
            if (!picker || typeof picker.open !== 'function') return null;
            return picker.open(tmuxName, display, status);
        },
        hasRestartPicker(): boolean {
            const picker = legacy().SessionRestartPicker;
            return !!picker && typeof picker.open === 'function';
        },
        restartPickerError(): string | null {
            const picker = legacy().SessionRestartPicker;
            if (!picker || typeof picker.lastError !== 'function') return null;
            return picker.lastError();
        },
        async respawnSession(
            tmuxName: string, agentType: string | null, confirmLive: boolean,
        ): Promise<RespawnResult> {
            const api = legacy().API;
            if (!api) throw new ApiUnavailableError();
            return api.respawnSession(tmuxName, agentType, confirmLive);
        },
        async reopenAfterRestart(result: RespawnResult): Promise<ReopenResult> {
            const back = legacy().SessionRestartReturn;
            if (!back || typeof back.reopen !== 'function') {
                return { status: 'not_reopened', detail: null };
            }
            return back.reopen(result);
        },
        async forkSession(tmuxName: string): Promise<void> {
            const web = legacy().CloudeWeb;
            const fn = web && web.launchpad && web.launchpad.forkSession;
            if (typeof fn !== 'function') {
                missing('CloudeWeb.launchpad.forkSession');
                return;
            }
            await fn(tmuxName);
        },
        async returnToActive(sessionId: string | null): Promise<void> {
            await returnToActiveSession(sessionId, browserNavHost(), t);
        },
        async attachSession(name: string): Promise<void> {
            await attachRunningSession(name, browserNavHost(), t);
        },
        async refresh(): Promise<void> {
            const web = legacy().CloudeWeb;
            const fn = web && web.launchpad && web.launchpad.loadRunningSessions;
            if (typeof fn !== 'function') {
                missing('CloudeWeb.launchpad.loadRunningSessions');
                return;
            }
            await fn();
        },
        showError(message: string): void {
            const lp = legacy().Launchpad;
            if (!lp || typeof lp.showError !== 'function') {
                missing('Launchpad.showError');
                return;
            }
            lp.showError(message);
        },
    };
}
