import {
    forkFailureNotice,
    RECENT_KEYS,
    restartNotice,
    unidentifiedRestartNotice,
} from '../../../../client/js/labels/recent-session.js';
import { reasonOf } from './failure-reason';
import {
    restartPlan,
    type RestartPlan,
    type RecentSessionsPayload,
    type RestartOptions,
    type Translate,
} from './recent';
import type { LiveSession } from './recent-visibility';
import { openStatusKey, recentOpenStatus } from './recent-open-status.svelte';
import { openedSession, openToast, raiseToast, type OpenStep } from './recent-open-feedback';

export interface ForkResponse {
    lineage_recorded?: boolean;
    detail?: string | null;
}

export interface RestartResponse {
    conversation?: string | null;
    title_carried?: string | null;
    row_reused?: boolean;
    detail?: string | null;
}

export interface RecentHost {
    fetchRecent(includeArchived: boolean): Promise<RecentSessionsPayload>;
    archiveRecord(sessionUuid: string): Promise<unknown>;
    fork(tmuxName: string): Promise<ForkResponse>;
    restart(sessionUuid: string): Promise<RestartResponse>;
    createSession(payload: Record<string, string>): Promise<unknown>;
    showError(message: string): void;
    refreshRecent(): Promise<void>;
    refreshRunningSessions(): Promise<void>;
    refreshAttribution(): Promise<void>;
    refreshProjectList(): void;
    liveSessions(): LiveSession[];
    deriveDisplayName(tmuxName: string): string | null;
    toast?(record: Record<string, unknown>): void;
    openSession?(sessionId: string, tmuxName: string): Promise<void>;
}

export async function archiveSessionRecord(
    sessionUuid: string | null | undefined,
    host: RecentHost,
    t: Translate,
): Promise<void> {
    if (!sessionUuid) {
        host.showError(t(RECENT_KEYS.archiveFailedNoId));
        return;
    }
    try {
        await host.archiveRecord(sessionUuid);
    } catch (error) {
        console.error('CloudeWeb: archive of session record failed:', error);
        host.showError(t(RECENT_KEYS.archiveFailed, { reason: reasonOf(error, t) }));
        return;
    }
    await host.refreshAttribution();
    await host.refreshRecent();
    host.refreshProjectList();
}

export async function forkSession(
    tmuxName: string | null | undefined,
    host: RecentHost,
    t: Translate,
): Promise<void> {
    if (!tmuxName) {
        host.showError(t(RECENT_KEYS.forkFailedNoName));
        return;
    }
    let result: ForkResponse;
    try {
        result = await host.fork(tmuxName);
    } catch (error) {
        console.error('CloudeWeb: fork failed:', error);
        host.showError(forkFailureNotice(error, t));
        return;
    }
    if (result && result.lineage_recorded === false) {
        const detail = typeof result.detail === 'string' ? result.detail.trim() : '';
        host.showError(detail || t(RECENT_KEYS.forkLineageUnrecorded));
    }
    await host.refreshAttribution();
    await host.refreshRecent();
    host.refreshProjectList();
}

export async function restartRecentSession(
    opts: Partial<RestartOptions> | null | undefined,
    host: RecentHost,
    t: Translate,
): Promise<void> {
    const plan = restartPlan(opts);
    const key = restartKey(plan, opts);
    if (RESTARTS_IN_FLIGHT.has(key)) return;
    RESTARTS_IN_FLIGHT.add(key);
    const rowKey = openStatusKey(opts && opts.sessionUuid, opts && opts.title);
    const name = ((opts && opts.title) || '').trim() || t(RECENT_KEYS.nameFallback);
    const say = (step: OpenStep, reason = ''): void => {
        recentOpenStatus.set(rowKey, { phase: step, reason });
        if (host.toast) host.toast(openToast(step, name, reason, t));
    };
    say('opening');
    let result: unknown;
    try {
        if (plan.mode === 'restart') {
            result = await host.restart(plan.sessionUuid);
            const notice = restartNotice(result as RestartResponse, t);
            if (notice) host.showError(notice);
        } else {
            result = await host.createSession(plan.payload || {});
            if (plan.mustExplain) {
                host.showError(unidentifiedRestartNotice((opts && opts.title) || '', t));
            }
        }
    } catch (error) {
        console.error('CloudeWeb: restart of recent session failed:', error);
        const reason = reasonOf(error, t);
        say('failed', reason);
        host.showError(t(RECENT_KEYS.restartFailed, { reason }));
        RESTARTS_IN_FLIGHT.delete(key);
        return;
    }
    try {
        say('opened');
        const opened = openedSession(result);
        await followUp('refreshRunning', () => host.refreshRunningSessions());
        if (opened && host.openSession) await followUp('openSession', () => host.openSession!(opened.id, opened.tmuxName));
        await followUp('refreshRecent', () => host.refreshRecent());
    } finally {
        RESTARTS_IN_FLIGHT.delete(key);
    }
}

async function followUp(step: string, run: () => Promise<unknown>): Promise<void> {
    try {
        await run();
    } catch (error) {
        console.error(`CloudeWeb: restarted session, but follow-up step failed: ${step}`, error);
    }
}

const RESTARTS_IN_FLIGHT = new Set<string>();

function restartKey(plan: RestartPlan, opts: Partial<RestartOptions> | null | undefined): string {
    if (plan.sessionUuid) return `uuid:${plan.sessionUuid}`;
    const o = opts || {};
    return `create:${(o.title || '').trim()}\u0000${(o.workingDir || '').trim()}`;
}

export function isRestartInFlight(opts: Partial<RestartOptions> | null | undefined): boolean {
    return RESTARTS_IN_FLIGHT.has(restartKey(restartPlan(opts), opts));
}

interface LegacyApi {
    listRecentSessions(includeArchived?: boolean): Promise<RecentSessionsPayload>;
    deleteSessionRecord(sessionUuid: string): Promise<unknown>;
    forkSession(tmuxName: string): Promise<ForkResponse>;
    restartSession(sessionUuid: string): Promise<RestartResponse>;
    createSession(params?: Record<string, string>): Promise<unknown>;
}

interface LegacyLaunchpad {
    showError?(message: string): void;
    loadRunningSessions?(): Promise<void>;
    _deriveRunningSessionDisplayName?(tmuxName: string): string | null;
}

export function browserHost(refreshRecent: () => Promise<void>): RecentHost {
    const api = (): LegacyApi => (window as unknown as { API: LegacyApi }).API;
    const web = () =>
        (window as unknown as {
            CloudeWeb?: {
                launchpad?: {
                    loadSessionAttribution?: () => Promise<void>;
                    sessions?: { runningSessions?: unknown };
                };
            };
        }).CloudeWeb;
    const lp = (): LegacyLaunchpad =>
        (window as unknown as { Launchpad?: LegacyLaunchpad }).Launchpad || {};
    return {
        fetchRecent: (includeArchived) => api().listRecentSessions(includeArchived),
        archiveRecord: (uuid) => api().deleteSessionRecord(uuid),
        fork: (name) => api().forkSession(name),
        restart: (uuid) => api().restartSession(uuid),
        createSession: (payload) => api().createSession(payload),
        toast(record: Record<string, unknown>): void {
            raiseToast(record);
        },
        async openSession(sessionId: string, tmuxName: string): Promise<void> {
            const web = (window as unknown as {
                CloudeWeb?: { launchpad?: { openRunningSession?: (id: string, name: string) => Promise<void> } };
            }).CloudeWeb;
            const open = web?.launchpad?.openRunningSession;
            if (typeof open === 'function') await open(sessionId, tmuxName);
        },
        showError(message: string): void {
            const target = lp();
            if (typeof target.showError === 'function') {
                target.showError(message);
                return;
            }
            console.error('CloudeWeb: no error surface for:', message);
        },
        refreshRecent,
        async refreshRunningSessions(): Promise<void> {
            const target = lp();
            if (typeof target.loadRunningSessions === 'function') {
                await target.loadRunningSessions();
            }
        },
        async refreshAttribution(): Promise<void> {
            const load = web()?.launchpad?.loadSessionAttribution;
            if (typeof load === 'function') await load();
        },
        refreshProjectList(): void {},
        liveSessions(): LiveSession[] {
            const rows = web()?.launchpad?.sessions?.runningSessions;
            return Array.isArray(rows) ? (rows as LiveSession[]) : [];
        },
        deriveDisplayName(tmuxName: string): string | null {
            const target = lp();
            if (typeof target._deriveRunningSessionDisplayName === 'function') {
                return target._deriveRunningSessionDisplayName(tmuxName);
            }
            return null;
        },
    };
}
