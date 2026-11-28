import { authFetch } from '../../opscenter/api/auth.svelte';
import { createLaunchProfilesApi, type ProfileRow } from '../launch-profiles-page/api';
import type { CreatedSession } from '../launchpad/create-host';
import { refusedWith } from '../launchpad/refusal-shape';
import { UNIQUE_NAME_ATTEMPTS, type KeyedError } from '../launchpad/open-folder-flow';
import { PROJECT_CREATE_KEYS } from '../../../../client/js/labels/project-create.js';
import { filterProfilesForWizard, type WizardAccount, type WizardComputer, type WizardProject } from './model';

export interface BrowseEntry {
    name: string;
    path: string;
}

export interface BrowseResult {
    path: string;
    parent: string | null;
    entries: BrowseEntry[];
}

export interface WizardBootstrap {
    projects: WizardProject[];
    activeProjectRoots: Set<string>;
    profiles: ProfileRow[];
    computers: WizardComputer[];
    accounts: WizardAccount[];
    defaultDir: string;
    homeDir: string | null;
}

export interface ClonedProjectResult {
    name: string;
    path: string;
    description?: string | null;
}

export interface WizardApi {
    loadBootstrap(): Promise<WizardBootstrap>;
    browseFolder(path?: string): Promise<BrowseResult>;
    createFolder(path: string): Promise<BrowseResult>;
    probeWorktree(workingDir: string): Promise<{ isGit: boolean; suggestedBranch: string }>;
    createProject(row: { name: string; path: string; description?: string | null }): Promise<void>;
    saveProjectUnique?(row: { name: string; path: string; description?: string | null }): Promise<{ name: string; path: string }>;
    cloneProject?(payload: {
        repoUrl: string;
        parentDir?: string;
        projectName?: string;
        description?: string;
    }): Promise<ClonedProjectResult>;
    createSession(payload: Record<string, unknown>): Promise<CreatedSession>;
    loadRecentFolders(): string[];
    rememberRecentFolder(path: string): void;
}

const RECENT_STORAGE_KEY = 'carnivore.new_agent.recent_folders';
const MAX_RECENTS = 6;

interface RawProjectRow {
    id: number;
    name: string;
    path?: string;
    root?: string;
    default_launch_profile?: string | null;
    company_id?: number | null;
    color?: string | null;
    archived_at?: string | null;
}

interface RawSessionRow {
    session?: { working_dir?: string | null };
    working_dir?: string | null;
}

interface RawMachineRow {
    key?: string;
    host_key?: string;
    label?: string;
    name?: string;
    online?: boolean;
    status?: string;
}

interface RawAccountRow {
    id?: string;
    name?: string;
    provider?: string;
}

function inferHomeDir(path: string): string | null {
    const m = /^(\/Users\/[^/]+|\/home\/[^/]+)/.exec(path || '');
    return m ? (m[1] ?? null) : null;
}

export function loadRecentFolders(seed: readonly string[] = []): string[] {
    const out: string[] = [];
    const seen = new Set<string>();
    const add = (p: string) => {
        const norm = (p || '').trim().replace(/\/+$/, '') || '/';
        if (!norm || seen.has(norm)) return;
        seen.add(norm);
        out.push(norm);
    };
    try {
        const raw = localStorage.getItem(RECENT_STORAGE_KEY);
        if (raw) {
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed)) {
                for (const item of parsed) {
                    if (typeof item === 'string') add(item);
                }
            }
        }
    } catch {
    }
    for (const s of seed) add(s);
    add('/tmp');
    return out.slice(0, MAX_RECENTS);
}

export function rememberRecentFolder(path: string): void {
    const clean = (path || '').trim().replace(/\/+$/, '');
    if (!clean) return;
    const prev = loadRecentFolders().filter((p) => p !== clean);
    const next = [clean, ...prev].slice(0, MAX_RECENTS);
    try {
        localStorage.setItem(RECENT_STORAGE_KEY, JSON.stringify(next));
    } catch {
    }
}

export const liveWizardApi: WizardApi = {
    async loadBootstrap(): Promise<WizardBootstrap> {
        const profilesApi = createLaunchProfilesApi();
        const [projRes, sessRes, profRes, machRes, acctRes, browseRes] = await Promise.allSettled([
            authFetch<RawProjectRow[]>('/projects'),
            authFetch<RawSessionRow[]>('/sessions/list'),
            profilesApi.list(),
            authFetch<{ machines?: RawMachineRow[] } | RawMachineRow[]>('/pack/machines'),
            authFetch<RawAccountRow[]>('/provider-ledger/accounts'),
            authFetch<BrowseResult>('/filesystem/browse'),
        ]);

        const rawProjects = projRes.status === 'fulfilled' && Array.isArray(projRes.value) ? projRes.value : [];
        const projects: WizardProject[] = rawProjects
            .filter((p) => !p.archived_at)
            .map((p) => ({
                id: p.id,
                name: p.name,
                path: p.path || p.root || '',
                root: p.root || p.path || '',
                defaultLaunchProfile: p.default_launch_profile ?? null,
                companyId: p.company_id ?? null,
                color: p.color ?? null,
            }));

        const activeProjectRoots = new Set<string>();
        if (sessRes.status === 'fulfilled' && Array.isArray(sessRes.value)) {
            for (const row of sessRes.value) {
                const wd = (row.session?.working_dir || row.working_dir || '').replace(/\/+$/, '');
                if (wd) activeProjectRoots.add(wd);
            }
        }

        const allProfiles = profRes.status === 'fulfilled' ? profRes.value.profiles : [];
        const profiles = filterProfilesForWizard(allProfiles);

        const computers: WizardComputer[] = [{ key: 'local', label: '', online: true }];
        if (machRes.status === 'fulfilled') {
            const list = Array.isArray(machRes.value) ? machRes.value : (machRes.value?.machines ?? []);
            for (const m of list) {
                const key = m.key || m.host_key || '';
                if (!key || key === 'local') continue;
                const online = m.online !== undefined ? m.online : m.status === 'online' || m.status === 'up';
                computers.push({ key, label: m.label || m.name || key, online });
            }
        }

        const accounts: WizardAccount[] = [];
        if (acctRes.status === 'fulfilled' && Array.isArray(acctRes.value)) {
            for (const a of acctRes.value) {
                if (a.id && a.name) {
                    accounts.push({ id: a.id, name: a.name, provider: a.provider || 'claude' });
                }
            }
        }

        const defaultDir = browseRes.status === 'fulfilled' && browseRes.value?.path ? browseRes.value.path : '/tmp';
        const homeDir = inferHomeDir(defaultDir);

        return { projects, activeProjectRoots, profiles, computers, accounts, defaultDir, homeDir };
    },

    browseFolder(path?: string): Promise<BrowseResult> {
        const qs = path ? `?path=${encodeURIComponent(path)}` : '';
        return authFetch<BrowseResult>(`/filesystem/browse${qs}`);
    },

    createFolder(path: string): Promise<BrowseResult> {
        return authFetch<BrowseResult>('/filesystem/mkdir', {
            method: 'POST',
            body: JSON.stringify({ path }),
        });
    },

    async probeWorktree(workingDir: string): Promise<{ isGit: boolean; suggestedBranch: string }> {
        try {
            const res = await authFetch<{ is_git?: boolean; git?: boolean; suggested_branch?: string }>(
                `/worktrees/probe?working_dir=${encodeURIComponent(workingDir)}`,
            );
            return {
                isGit: Boolean(res?.is_git ?? res?.git ?? false),
                suggestedBranch: res?.suggested_branch || 'feat/agent-task',
            };
        } catch {
            return { isGit: false, suggestedBranch: 'feat/agent-task' };
        }
    },

    async createProject(row: { name: string; path: string; description?: string | null }): Promise<void> {
        await authFetch('/projects', { method: 'POST', body: JSON.stringify(row) });
    },

    async saveProjectUnique(row: {
        name: string;
        path: string;
        description?: string | null;
    }): Promise<{ name: string; path: string }> {
        let attempt = row.name;
        for (let i = 0; i < UNIQUE_NAME_ATTEMPTS; i += 1) {
            try {
                await authFetch('/projects', {
                    method: 'POST',
                    body: JSON.stringify({
                        name: attempt,
                        path: row.path,
                        description: row.description ?? null,
                    }),
                });
                return { name: attempt, path: row.path };
            } catch (error) {
                const err = error as { status?: number; body?: { existing_project?: { name?: string | null } | null } | null } | null;
                if (err?.status === 409) {
                    const existing = err.body?.existing_project?.name;
                    if (existing) return { name: String(existing), path: row.path };
                    return { name: attempt, path: row.path };
                }
                if (!refusedWith(error, { code: 'project_name_taken', phrase: 'already exists' })) throw error;
                attempt = `${row.name} (${i + 2})`;
            }
        }
        const failure: KeyedError = new Error(PROJECT_CREATE_KEYS.uniqueNameFailed);
        failure.cloudeKey = PROJECT_CREATE_KEYS.uniqueNameFailed;
        throw failure;
    },

    async cloneProject(payload: {
        repoUrl: string;
        parentDir?: string;
        projectName?: string;
        description?: string;
    }): Promise<ClonedProjectResult> {
        const body: Record<string, unknown> = { repo_url: payload.repoUrl };
        if (payload.parentDir) body.parent_dir = payload.parentDir;
        if (payload.projectName) body.project_name = payload.projectName;
        if (payload.description) body.description = payload.description;
        return authFetch<ClonedProjectResult>('/projects/clone', {
            method: 'POST',
            body: JSON.stringify(body),
        });
    },

    createSession(payload: Record<string, unknown>): Promise<CreatedSession> {
        return authFetch<CreatedSession>('/sessions', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
    },

    loadRecentFolders: () => loadRecentFolders(),
    rememberRecentFolder,
};
