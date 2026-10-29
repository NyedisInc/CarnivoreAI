import type { ProjectRow } from '../sessions/types';
import { sessionDisplayLabel } from '../sessions/session-label';
import { t } from '../i18n/index.svelte';
import type { TreeSessionRow } from './project-groups';
import { browserCreateHost } from './create-host';
import { browserModals } from './modals';
import {
    archiveProjectFlow,
    editProjectFlow,
    unarchiveProjectFlow,
} from './project-actions';
import { attachRunningSession, returnToActiveSession } from './navigation';
import { browserNavHost } from './nav-host';
import { explainRefusedProject, type PresenceRow } from './status-report';

interface LegacyLaunchpad {
    selectProject?: (project: ProjectRow) => unknown;
    _returnToActiveRunningSession?: (sessionId: string | null) => Promise<unknown>;
    _handleAttachRunningSession?: (name: string) => Promise<unknown>;
    loadProjects?: () => Promise<unknown>;
}

export interface ProjectTreeHost {
    selectProject(project: ProjectRow): void;
    /* CANNOT DETERMINE */
    explainRefused(project: ProjectRow, el: Element | null): void;
    editProject(project: ProjectRow): void;
    archiveProject(name: string): Promise<void>;
    unarchiveProject(name: string): Promise<void>;
    returnToActive(sessionId: string | null): Promise<void>;
    attachSession(name: string): Promise<void>;
    restartEnded(row: TreeSessionRow): Promise<void>;
    archiveRecord(sessionUuid: string | null): Promise<void>;
    displayLabel(row: TreeSessionRow): string;
    reloadProjects(): Promise<void>;
}

interface WebNamespace {
    launchpad?: {
        restartRecentSession?: (opts: unknown) => Promise<unknown>;
        archiveSessionRecord?: (uuid: string | null) => Promise<unknown>;
        loadProjects?: (includeArchived: boolean) => Promise<unknown>;
        sessions?: { projectPresence?: Map<string, PresenceRow> };
    };
}

function win(): (Window & typeof globalThis) | undefined {
    return typeof window === 'undefined' ? undefined : window;
}

function legacy(): LegacyLaunchpad | null {
    const w = win() as unknown as { Launchpad?: LegacyLaunchpad } | undefined;
    return (w && w.Launchpad) || null;
}

function web(): WebNamespace | null {
    const w = win() as unknown as { CloudeWeb?: WebNamespace } | undefined;
    return (w && w.CloudeWeb) || null;
}

function missing(what: string): void {
    if (typeof console !== 'undefined' && typeof console.error === 'function') {
        console.error('CloudeWeb: the project tree could not reach', what);
    }
}

export function browserProjectTreeHost(): ProjectTreeHost {
    return {
        selectProject(project: ProjectRow): void {
            const lp = legacy();
            if (!lp || typeof lp.selectProject !== 'function') {
                missing('selectProject');
                return;
            }
            lp.selectProject(project);
        },
        explainRefused(project: ProjectRow): void {
            const presence = web()?.launchpad?.sessions?.projectPresence;
            const row =
                (project.root ? presence?.get(String(project.root)) : undefined) ||
                (project.path ? presence?.get(String(project.path)) : undefined) ||
                null;
            explainRefusedProject(project, row, t);
        },
        editProject(project: ProjectRow): void {
            void editProjectFlow(browserCreateHost(), browserModals(), t, project);
        },
        async archiveProject(name: string): Promise<void> {
            await archiveProjectFlow(browserCreateHost(), t, name);
        },
        async unarchiveProject(name: string): Promise<void> {
            await unarchiveProjectFlow(browserCreateHost(), t, name);
        },
        async returnToActive(sessionId: string | null): Promise<void> {
            await returnToActiveSession(sessionId, browserNavHost(), t);
        },
        async attachSession(name: string): Promise<void> {
            await attachRunningSession(name, browserNavHost(), t);
        },
        async restartEnded(row: TreeSessionRow): Promise<void> {
            const w = web();
            const fn = w && w.launchpad && w.launchpad.restartRecentSession;
            if (typeof fn !== 'function') {
                missing('restartRecentSession');
                return;
            }
            await fn({
                sessionUuid: row.session_uuid || null,
                title: (row.title && String(row.title).trim()) || '',
                workingDir: row.working_dir || '',
                agentType: row.agent_type || '',
            });
        },
        async archiveRecord(sessionUuid: string | null): Promise<void> {
            const w = web();
            const fn = w && w.launchpad && w.launchpad.archiveSessionRecord;
            if (typeof fn !== 'function') {
                missing('archiveSessionRecord');
                return;
            }
            await fn(sessionUuid);
        },
        displayLabel(row: TreeSessionRow): string {
            return sessionDisplayLabel(row);
        },
        async reloadProjects(): Promise<void> {
            const lp = legacy();
            if (!lp || typeof lp.loadProjects !== 'function') {
                missing('loadProjects');
                return;
            }
            await lp.loadProjects();
        },
    };
}
