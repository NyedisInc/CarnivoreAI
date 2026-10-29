/* CANNOT BE DETERMINED */
import { t } from '../i18n/index.svelte';
import { relativeAge } from '../../../../client/js/labels/running-session.js';

/* could not */
export interface UnattributedSession {
    tmux_name: string;
    /* could not */
    epoch?: number | null;
    label?: string | null;
    hints?: string[];
    reason?: string;
}

export interface SessionAttributionPrompt {
    state: string;
    sessions?: UnattributedSession[];
    notice?: string | null;
}

export interface AttributionDeclineResponse {
    declined?: string[];
    not_eligible?: string[];
    unknown?: string[];
}

export interface AttributionRow {
    tmuxName: string;
    shown: string;
    started: string;
    why: string;
    reason: string;
    hints: string[];
}

export type AttributionView =
    | { kind: 'nothing' }
    | { kind: 'unavailable'; notice: string }
    | { kind: 'pending'; notice: string; rows: AttributionRow[] };

export interface AttributionHost {
    fetchPrompt(): Promise<SessionAttributionPrompt>;
    adoptSession(tmuxName: string): Promise<unknown>;
    declineAttribution(tmuxNames: string[]): Promise<AttributionDeclineResponse>;
    showError(message: string): void;
    /* running sessions */
    refreshRunningSessions(): void;
    formatRelativeTime(epochSeconds: number): string;
    resolveLabel(session: UnattributedSession): string | null;
}

/* CANNOT BE DETERMINED could not be read */
export const UNAVAILABLE_FALLBACK_NOTICE = 'session attribution CANNOT BE DETERMINED';

const WHY_BY_REASON: Record<string, string> = {
    could_not_evaluate: 'we could not complete the check for this one',
};

const WHY_DEFAULT = 'we found no record either way';

let closed = false;

export function isClosed(): boolean {
    return closed;
}

export function close(): void {
    closed = true;
}

export function resetClosedForTests(): void {
    closed = false;
}

export function describeRow(
    session: UnattributedSession,
    host: AttributionHost,
): AttributionRow {
    const tmuxName = session.tmux_name || '';
    const reason = session.reason || '';
    return {
        tmuxName,
        shown: host.resolveLabel(session) || tmuxName,
        started: session.epoch
            ? host.formatRelativeTime(session.epoch)
            : 'start time unknown',
        why: WHY_BY_REASON[reason] ?? WHY_DEFAULT,
        reason,
        hints: session.hints || [],
    };
}

/* CANNOT BE DETERMINED */
export function viewFor(
    prompt: SessionAttributionPrompt | null | undefined,
    host: AttributionHost,
    hasClosed: boolean,
): AttributionView {
    if (!prompt || hasClosed) return { kind: 'nothing' };
    if (prompt.state === 'unavailable') {
        return {
            kind: 'unavailable',
            notice: prompt.notice || UNAVAILABLE_FALLBACK_NOTICE,
        };
    }
    if (
        prompt.state !== 'pending'
        || !Array.isArray(prompt.sessions)
        || prompt.sessions.length === 0
    ) {
        return { kind: 'nothing' };
    }
    return {
        kind: 'pending',
        notice: prompt.notice || '',
        rows: prompt.sessions.map((s) => describeRow(s, host)),
    };
}

export async function loadPrompt(
    host: AttributionHost,
): Promise<SessionAttributionPrompt | null> {
    try {
        return await host.fetchPrompt();
    } catch (error) {
        console.error('Launchpad: attribution prompt fetch failed:', error);
        return null;
    }
}

/* running sessions */
export async function adoptAttributed(
    tmuxNames: readonly string[],
    host: AttributionHost,
): Promise<string[]> {
    if (!tmuxNames || tmuxNames.length === 0) return [];
    const failed: string[] = [];
    for (const name of tmuxNames) {
        try {
            await host.adoptSession(name);
        } catch (error) {
            failed.push(name);
            console.error('Launchpad: adopt failed for', name, error);
        }
    }
    if (failed.length) host.showError('could not adopt: ' + failed.join(', '));
    return failed;
}

/* running sessions */
export async function declineAttributed(
    tmuxNames: readonly string[],
    host: AttributionHost,
): Promise<string[]> {
    if (!tmuxNames || tmuxNames.length === 0) return [];
    try {
        const out = await host.declineAttribution([...tmuxNames]);
        const stuck = [...(out.not_eligible || []), ...(out.unknown || [])];
        if (stuck.length) host.showError('not recorded for: ' + stuck.join(', '));
        return stuck;
    } catch (error) {
        console.error('Launchpad: decline failed:', error);
        const message = error instanceof Error ? error.message : String(error);
        host.showError('that answer was NOT recorded: ' + message);
        return [...tmuxNames];
    }
}

interface LegacyApi {
    getSessionAttributionPrompt(): Promise<SessionAttributionPrompt>;
    adoptSession(sessionName: string, confirmDetach?: boolean): Promise<unknown>;
    declineSessionAttribution(tmuxNames: string[]): Promise<AttributionDeclineResponse>;
}

interface LegacyLaunchpad {
    showError(message: string): void;
    loadRunningSessions(): unknown;
}

interface LegacySessionLabel {
    resolve(
        row: { label?: string | null; name?: string | null },
        options?: { stripPrefix?: boolean },
    ): string | null;
}

declare global {
    interface Window {
        API?: LegacyApi;
        Launchpad?: LegacyLaunchpad;
        SessionLabel?: LegacySessionLabel;
    }
}

export function browserHost(): AttributionHost {
    const api = (): LegacyApi => {
        const value = window.API;
        if (!value) throw new Error('window.API is not loaded');
        return value;
    };
    const launchpad = (): LegacyLaunchpad => {
        const value = window.Launchpad;
        if (!value) throw new Error('window.Launchpad is not loaded');
        return value;
    };
    return {
        fetchPrompt: () => api().getSessionAttributionPrompt(),
        adoptSession: (tmuxName) => api().adoptSession(tmuxName),
        declineAttribution: (tmuxNames) => api().declineSessionAttribution(tmuxNames),
        showError: (message) => launchpad().showError(message),
        refreshRunningSessions: () => {
            launchpad().loadRunningSessions();
        },
        formatRelativeTime: (epochSeconds) => relativeAge(epochSeconds, t),
        resolveLabel: (session) => {
            const resolver = window.SessionLabel;
            if (!resolver) return null;
            return resolver.resolve(
                { label: session.label, name: session.tmux_name },
                { stripPrefix: false },
            );
        },
    };
}
