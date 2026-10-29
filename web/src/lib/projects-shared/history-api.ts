import { authFetch } from '../../opscenter/api/auth.svelte';
import { listingRows } from '../../opscenter/api/poll.svelte';
import { packApi, type PackApi } from './pack-api';
import type { PackStorage } from './pack-model';
import { sleepSession, wakeOrPick } from '../../opscenter/api/asleep.svelte';
import { newSession, openBlueprints, openSession, startNewProject, startNewSessionInProject } from '../../opscenter/api/host';
import {
    createCompany,
    deleteCompany,
    listCompanies,
    regenerateCompanyImage,
    regenerateProjectImage,
    removeCompanyImage,
    removeProjectImage,
    renameCompany,
    setProjectCompany,
    uploadCompanyImage,
    uploadProjectImage,
    type Company,
} from '../companies/api';
import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';

export interface HistorySession {
    readonly session_uuid: string;
    readonly row_id: number | null;
    readonly title: string;
    readonly label: string | null;
    readonly tmux_name: string | null;
    readonly host_key: string;
    readonly host_label?: string | null;
    readonly state: HistoryState;
    readonly lifecycle: string | null;
    readonly lifecycle_source: string | null;
    readonly archived_at: string | null;
    readonly agent_type: string | null;
    readonly agent_family: string | null;
    readonly claude_session_uuid: string | null;
    readonly has_transcript: boolean;
    readonly created_at: string | null;
    readonly last_seen_running_at: string | null;
    readonly last_work_at: string | null;
    readonly last_activity_at: string | null;
    readonly working_dir: string | null;
    readonly origin: string | null;
    readonly kind: string | null;
    readonly fork_kind: string | null;
    readonly live_session_id: string | null;
}

export type HistoryState = 'running' | 'asleep' | 'closed' | 'removed' | 'unknown';
export const HISTORY_STATES: readonly HistoryState[] = ['running', 'asleep', 'closed', 'removed', 'unknown'];

export interface HistoryProject {
    readonly id: number | null;
    readonly name: string;
    readonly root: string | null;
    readonly description: string | null;
    readonly archived_at: string | null;
    readonly last_opened_at: string | null;
    readonly created_at: string | null;
    readonly default_theme: string | null;
    readonly company_id?: number | null;
    readonly company_name?: string | null;
    readonly has_image?: boolean;
    readonly image_rev?: string | null;
    readonly new_sessions_join_swarm?: boolean;
    readonly storage?: PackStorage | null;
    readonly pack_state?: string | null;
    readonly moved_to_label?: string | null;
}

export interface HistoryGroup {
    readonly key: string;
    readonly project: HistoryProject | null;
    readonly session_total: number;
    readonly counts: Readonly<Record<string, number>>;
    readonly automated_counts?: Readonly<Record<string, number>>;
    readonly activity_days?: readonly number[];
    readonly last_activity_at: string | null;
    readonly sessions: readonly HistorySession[];
    readonly host_label?: string | null;
}

export interface HistoryPage {
    readonly state: 'ok' | 'no_datastore' | string;
    readonly total: number;
    readonly offset: number;
    readonly limit: number;
    readonly next_offset: number | null;
    readonly groups: readonly HistoryGroup[];
    readonly peer_groups?: readonly HistoryGroup[];
    readonly peer_unavailable?: readonly { readonly host_label: string }[];
    readonly facets: { readonly agents: readonly string[]; readonly states: Readonly<Record<string, number>> };
}

export const HISTORY_ROUTE = '/projects/history';

export interface HistoryApi {
    list(query: string): Promise<HistoryPage>;
    removeFromLists(sessionUuid: string): Promise<unknown>;
    restoreToLists(sessionUuid: string): Promise<unknown>;
    renameSession(sessionKey: string, label: string): Promise<unknown>;
    renameProject(name: string, newName: string): Promise<unknown>;
    setProjectColor(name: string, color: string): Promise<unknown>;
    archiveProject(name: string): Promise<unknown>;
    unarchiveProject(name: string): Promise<unknown>;
    deleteProject?(name: string): Promise<unknown>;
    pack?: PackApi;
    sleep(sessionUuid: string): Promise<{ status: string; detail: string }>;
    wake(session: HistorySession): Promise<{ status: string; detail: string } | null>;
    open(session: HistorySession): boolean;
    resume(session: HistorySession): Promise<boolean>;
    newSession(project: HistoryProject): boolean;
    openBlueprints(): boolean;
    copyText(text: string): Promise<void>;
    prompt(options: PromptOptions): Promise<string | null>;
    liveListing?(): Promise<readonly unknown[] | null>;
    createSession?(): boolean;
    createProject?(): boolean;
    listCompanies?(): Promise<Company[]>;
    createCompany?(name: string): Promise<Company>;
    turnOnAgent?(projectId: number): Promise<{ readonly display_name: string }>;
    setNewSessionsJoin?(projectId: number, on: boolean): Promise<unknown>;
    renameCompany?(id: number, name: string): Promise<unknown>;
    deleteCompany?(id: number): Promise<unknown>;
    setProjectCompany?(projectName: string, companyId: number | null): Promise<unknown>;
    setCompanyImage?(id: number, file: Blob): Promise<unknown>;
    removeCompanyImage?(id: number): Promise<unknown>;
    setProjectImage?(projectName: string, file: Blob): Promise<unknown>;
    removeProjectImage?(projectName: string): Promise<unknown>;
    regenerateCompanyImage?(id: number): Promise<unknown>;
    regenerateProjectImage?(projectName: string): Promise<unknown>;
    confirm?(options: ConfirmOptions): Promise<boolean>;
}

export interface ConfirmOptions {
    readonly title: string;
    readonly message: string;
    readonly detail: string;
    readonly confirmLabel: string;
    readonly cancelLabel: string;
}

export interface PromptOptions {
    readonly title: string;
    readonly label: string;
    readonly defaultValue: string;
    readonly confirmLabel: string;
    readonly cancelLabel: string;
}

async function promptText(options: PromptOptions): Promise<string | null> {
    const modal = (globalThis as { TextPromptModal?: { open?: (o: PromptOptions) => Promise<string | null> } })
        .TextPromptModal;
    if (typeof modal?.open !== 'function') {
        console.error('CloudeOpscenter: window.TextPromptModal is not available, the rename did nothing');
        return null;
    }
    return modal.open(options);
}

async function confirmDestructive(options: ConfirmOptions): Promise<boolean> {
    const app = (globalThis as { App?: { showConfirmModal?: (...a: unknown[]) => Promise<boolean> } }).App;
    if (typeof app?.showConfirmModal !== 'function') {
        console.error('CloudeOpscenter: App.showConfirmModal is not available, the delete did nothing');
        return false;
    }
    return Boolean(await app.showConfirmModal(options.title, options.message, options.detail, options.confirmLabel, options.cancelLabel, 'danger'));
}

type RestartFlow = (opts: Record<string, unknown>) => Promise<void>;

async function resumeAwaited(s: HistorySession): Promise<boolean> {
    const web = (globalThis as { CloudeWeb?: { launchpad?: { restartRecentSession?: RestartFlow } } }).CloudeWeb;
    const restart = web?.launchpad?.restartRecentSession;
    if (typeof restart !== 'function') {
        console.error('CloudeOpscenter: CloudeWeb.launchpad.restartRecentSession is not available, the action did nothing');
        return false;
    }
    await restart({
        sessionUuid: s.session_uuid,
        title: (s.title ?? '').trim(),
        workingDir: s.working_dir ?? '',
        agentType: s.agent_type ?? '',
    });
    return true;
}

export function launchInProject(p: HistoryProject): boolean {
    let created = false;
    const mark = (): void => {
        created = true;
    };
    globalThis.addEventListener('session-created', mark);
    const flow = startNewSessionInProject({ id: p.id, name: p.name, path: p.root, root: p.root });
    if (!flow) {
        globalThis.removeEventListener('session-created', mark);
        return false;
    }
    void flow.finally(() => {
        globalThis.removeEventListener('session-created', mark);
        if (created) sidebarTabs.select('agents');
    });
    return true;
}

const seg = (value: string): string => encodeURIComponent(value);

export const historyApi: HistoryApi = {
    list: (query) => authFetch<HistoryPage>(`${HISTORY_ROUTE}${query ? `?${query}` : ''}`),
    removeFromLists: (uuid) => authFetch(`/sessions/records/${seg(uuid)}`, { method: 'DELETE' }),
    restoreToLists: (uuid) => authFetch(`/sessions/records/${seg(uuid)}/unarchive`, { method: 'POST' }),
    renameSession: (key, label) =>
        authFetch(`/sessions/${seg(key)}/name`, { method: 'PATCH', body: JSON.stringify({ new_name: label }) }),
    renameProject: (name, newName) =>
        authFetch(`/projects/${seg(name)}`, { method: 'PATCH', body: JSON.stringify({ new_name: newName }) }),
    setProjectColor: (name, color) =>
        authFetch(`/projects/${seg(name)}`, { method: 'PATCH', body: JSON.stringify({ color }) }),
    archiveProject: (name) => authFetch(`/projects/${seg(name)}/archive`, { method: 'POST' }),
    unarchiveProject: (name) => authFetch(`/projects/${seg(name)}/unarchive`, { method: 'POST' }),
    deleteProject: (name) => authFetch(`/projects/${seg(name)}`, { method: 'DELETE' }),
    pack: packApi,
    sleep: (uuid) => sleepSession(uuid),
    wake: (s) => wakeOrPick(s.session_uuid, s.tmux_name ?? '', s.title),
    open: (s) => openSession(s.live_session_id, s.tmux_name),
    resume: (s) => resumeAwaited(s),
    newSession: launchInProject,
    openBlueprints: () => openBlueprints(),
    copyText: (text) => navigator.clipboard.writeText(text),
    prompt: (options) => promptText(options),
    liveListing: async () => {
        return listingRows<unknown>('list', '/sessions/list');
    },
    createSession: () => newSession(null),
    createProject: () => startNewProject(),
    listCompanies: () => listCompanies(),
    createCompany: (name) => createCompany(name),
    setNewSessionsJoin: (projectId, on) =>
        authFetch(`/swarm/projects/${projectId}/membership`, { method: 'PUT', body: JSON.stringify({ new_sessions_join_swarm: on }) }),
    turnOnAgent: (projectId) => authFetch<{ display_name: string }>(`/swarm/projects/${projectId}/agent`, { method: 'POST' }),
    renameCompany: (id, name) => renameCompany(id, name),
    deleteCompany: (id) => deleteCompany(id),
    setProjectCompany: (name, companyId) => setProjectCompany(name, companyId),
    setCompanyImage: (id, file) => uploadCompanyImage(id, file),
    removeCompanyImage: (id) => removeCompanyImage(id),
    setProjectImage: (name, file) => uploadProjectImage(name, file),
    removeProjectImage: (name) => removeProjectImage(name),
    regenerateCompanyImage: (id) => regenerateCompanyImage(id),
    regenerateProjectImage: (name) => regenerateProjectImage(name),
    confirm: (options) => confirmDestructive(options),
};
