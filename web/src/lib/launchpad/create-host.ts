import { hostWindow } from '../sessions/env';
import { withNav, type NavToken } from './nav-generation';
import { t } from '../i18n/index.svelte';
import { browserNavHost } from './nav-host';
import { detachAndCreateNew, selectProject } from './navigation';
import { showError, updateStatus } from './status-report';
import { authFetch } from '../../opscenter/api/auth.svelte';
import { HOSTS_ROUTE, LOCAL_HOST_KEY, type HostRow, type HostsListResponse } from '../hosts-page/hosts-adapter';
import type { ProjectRow } from '../sessions/types';
import type { ClonedProject, FolderPickerSource, RemoteFolderAnswer } from './modal-types';

export { LOCAL_HOST_KEY };

export type HostChoice = HostRow;

export interface ProviderChoice {
    wrapperId?: string | null;
    agentType?: string | null;
    farLauncher?: boolean;
    model?: string | null;
    accountId?: string | null;
    pinAccount?: boolean;
    name?: string | null;
    pinned?: boolean;
    [key: string]: unknown;
}

export type CreatePayload = Record<string, unknown>;

export interface CreatedSession {
    working_dir?: string | null;
    [key: string]: unknown;
}

export interface CreateHost {
    chooseProvider(remote?: { key: string; label: string } | null, goLabel?: string | null): Promise<ProviderChoice | null>;
    listHosts(): Promise<HostChoice[]>;
    createSession(payload: CreatePayload): Promise<CreatedSession>;
    createProject(row: {
        name: string;
        path: string;
        description?: string | null;
    }): Promise<unknown>;
    checkProjectRoot(path: string): Promise<unknown>;
    updateProject(name: string, fields: Record<string, unknown>): Promise<unknown>;
    archiveProject(name: string): Promise<unknown>;
    unarchiveProject(name: string): Promise<unknown>;
    cloneProject(payload: {
        repoUrl: string;
        parentDir: string;
        description?: string;
    }): Promise<ClonedProject>;
    defaultParentDir(): Promise<string | null>;
    folderPicker(source?: FolderPickerSource): (() => Promise<string | null>) | null;
    remoteFolders(hostKey: string, path: string | null): Promise<RemoteFolderAnswer>;
    reloadProjects(): Promise<unknown>;
    projects(): ProjectRow[];
    projectsListingOk(): boolean | null;
    presenceFor(project: ProjectRow): Record<string, unknown> | null;
    selectProject(project: ProjectRow, choice: ProviderChoice | null): Promise<unknown>;
    detachAndCreateNew(agentType: string | null): unknown;
    terminalDims(): Record<string, unknown>;
    updateStatus(message: string): void;
    showError(message: string): void;
    confirm(
        title: string,
        message: string,
        details: string | null,
        primaryLabel: string,
        secondaryLabel: string,
    ): Promise<boolean>;
    announceSessionCreated(session: CreatedSession, nav?: NavToken): void;
}

interface LegacyApi {
    createSession(payload: CreatePayload): Promise<CreatedSession>;
    createProject(row: Record<string, unknown>): Promise<unknown>;
    checkProjectRoot(path: string): Promise<unknown>;
    updateProject(name: string, fields: Record<string, unknown>): Promise<unknown>;
    archiveProject(name: string): Promise<unknown>;
    unarchiveProject(name: string): Promise<unknown>;
    cloneProjectFromGithub(payload: Record<string, unknown>): Promise<ClonedProject>;
    browseDirectory(path?: string): Promise<{ path?: string | null }>;
}

interface LegacyLaunchpad {
    showProviderModal(opts?: { projectDefault?: string | null; remote?: { key: string; label: string } | null; goLabel?: string | null }): Promise<ProviderChoice | null>;
}

export function browserCreateHost(): CreateHost {
    const win = () => hostWindow() as unknown as Record<string, unknown> | undefined;
    const api = (): LegacyApi => (win()?.API as LegacyApi);
    const lp = (): LegacyLaunchpad => (win()?.Launchpad as LegacyLaunchpad);
    const store = () =>
        (win()?.CloudeWeb as { launchpad?: { sessions?: Record<string, unknown> } } | undefined)
            ?.launchpad?.sessions as
            | {
                  projects: ProjectRow[];
                  projectsListingOk: boolean | null;
                  projectPresence: Map<string, Record<string, unknown>>;
              }
            | undefined;

    return {
        chooseProvider: (remote, goLabel) => lp().showProviderModal(remote || goLabel ? { remote: remote ?? null, goLabel: goLabel ?? null } : undefined),
        async listHosts() {
            try {
                const body = await authFetch<HostsListResponse>(HOSTS_ROUTE);
                return body?.status === 'ok' ? [...body.hosts] : [];
            } catch (error) {
                console.warn('CloudeWeb: hosts unavailable for the launch picker:', error);
                return [];
            }
        },
        createSession: (payload) => api().createSession(payload),
        createProject: (row) => api().createProject(row),
        checkProjectRoot: (path) => api().checkProjectRoot(path),
        updateProject: (name, fields) => api().updateProject(name, fields),
        archiveProject: (name) => api().archiveProject(name),
        unarchiveProject: (name) => api().unarchiveProject(name),
        cloneProject: (payload) => api().cloneProjectFromGithub(payload),
        async defaultParentDir() {
            try {
                const res = await api().browseDirectory();
                return (res && res.path) || null;
            } catch (error) {
                console.warn('CloudeWeb: default project folder unavailable:', error);
                return null;
            }
        },
        async remoteFolders(hostKey, path) {
            const query = path === null ? '' : `?path=${encodeURIComponent(path)}`;
            try {
                return await authFetch<RemoteFolderAnswer>(`/filesystem/computer/${encodeURIComponent(hostKey)}/browse${query}`);
            } catch (error) {
                console.warn('CloudeWeb: a paired computer\'s folders are unavailable:', error);
                return { status: 'unavailable', reason: 'unreachable' };
            }
        },
        folderPicker(source) {
            const picker = win()?.FolderPickerModal as
                | { open(options?: Record<string, unknown>): Promise<string | null> }
                | undefined;
            if (!picker || typeof picker.open !== 'function') return null;
            return source
                ? () => picker.open({ list: source.list, title: source.title, truncatedText: source.truncatedText })
                : () => picker.open();
        },
        reloadProjects: () => {
            const web = win()?.CloudeWeb as
                | { launchpad?: { loadProjects?: (includeArchived?: boolean) => Promise<unknown> } }
                | undefined;
            const load = web?.launchpad?.loadProjects;
            return load ? load() : Promise.resolve();
        },
        projects: () => store()?.projects ?? [],
        projectsListingOk: () => store()?.projectsListingOk ?? null,
        presenceFor(project) {
            const presence = store()?.projectPresence;
            if (!presence) return null;
            const byRoot = project.root ? presence.get(String(project.root)) : undefined;
            const byPath = project.path ? presence.get(String(project.path)) : undefined;
            return (byRoot || byPath || null) as Record<string, unknown> | null;
        },
        selectProject: (project, choice) =>
            selectProject(project, browserNavHost(), t, choice),
        detachAndCreateNew: (agentType) => {
            const web = win()?.CloudeWeb as
                | { launchpad?: { createNewSession?: (a: string | null) => Promise<unknown> } }
                | undefined;
            const create = web?.launchpad?.createNewSession;
            return detachAndCreateNew(
                agentType,
                browserNavHost(),
                t,
                create ? (a) => create(a) : () => Promise.resolve(),
            );
        },
        terminalDims: () => browserNavHost().terminalDims(),
        updateStatus,
        showError: (message) => showError(message, t),
        confirm: (title, message, details, primaryLabel, secondaryLabel) => {
            const app = win()?.App as
                | {
                      showConfirmModal(
                          title: string,
                          message: string,
                          details: string | null,
                          primaryLabel: string,
                          secondaryLabel: string,
                      ): Promise<boolean>;
                  }
                | undefined;
            return app!.showConfirmModal(title, message, details, primaryLabel, secondaryLabel);
        },
        announceSessionCreated(session, nav) {
            const w = hostWindow() as unknown as Window | undefined;
            w?.dispatchEvent(
                new CustomEvent('session-created', { detail: withNav({ session }, nav ?? null) }),
            );
        },
    };
}
