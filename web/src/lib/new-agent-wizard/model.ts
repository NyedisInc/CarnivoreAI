import type { ProfileRow } from '../launch-profiles-page/api';
import { visibleProfiles } from '../launch-profiles-page/visibility';

export type WizardEntryContext =
    | 'top_plus'
    | 'tab_plus'
    | 'project_start'
    | 'clone_project'
    | 'open_folder'
    | 'existing_project_pick'
    | 'project_launch';

export type WizardBranch = 'disposable' | 'existing' | 'new_project';

export type WizardView =
    | 'step1'
    | 'project_kind'
    | 'existing_pick'
    | 'existing_launch'
    | 'new_setup'
    | 'new_launch'
    | 'clone_setup'
    | 'clone_launch'
    | 'open_folder_setup'
    | 'open_folder_launch'
    | 'disposable'
    | 'folder_picker';

export function initialViewForEntry(entryContext: WizardEntryContext, hasInitialProject = false): WizardView {
    switch (entryContext) {
        case 'project_start':
            return 'project_kind';
        case 'clone_project':
            return 'clone_setup';
        case 'open_folder':
            return 'open_folder_setup';
        case 'existing_project_pick':
            return 'existing_pick';
        case 'project_launch':
            return hasInitialProject ? 'existing_launch' : 'existing_pick';
        default:
            return 'step1';
    }
}

export function projectToWizardProject(project: Record<string, unknown>): WizardProject {
    const path = String(project.path || project.root || '');
    const root = String(project.root || project.path || '');
    const rawId = Number(project.id ?? 0);
    return {
        id: Number.isFinite(rawId) ? rawId : 0,
        name: String(project.name || folderBasename(path) || 'project'),
        path,
        root,
        defaultLaunchProfile:
            typeof project.default_launch_profile === 'string'
                ? project.default_launch_profile
                : typeof project.defaultLaunchProfile === 'string'
                  ? project.defaultLaunchProfile
                  : null,
        companyId:
            typeof project.company_id === 'number'
                ? project.company_id
                : typeof project.companyId === 'number'
                  ? project.companyId
                  : null,
        color: typeof project.color === 'string' ? project.color : null,
    };
}

export function extractRepoName(rawUrl: string): string | null {
    let url = String(rawUrl || '').trim().replace(/\/+$/, '');
    if (!url) return null;
    if (url.endsWith('.git')) url = url.slice(0, -4);
    if (url.includes('@') && url.includes(':') && !url.includes('://')) {
        url = url.split(':', 2)[1] ?? '';
    }
    if (url.includes('://')) {
        url = url.split('://', 2)[1] ?? '';
    }
    if (url.toLowerCase().startsWith('github.com/')) {
        url = url.slice('github.com/'.length);
    }
    const parts = url.split('/').filter(Boolean);
    if (parts.length < 2) return null;
    const name = parts[parts.length - 1] ?? '';
    if (!name || name.includes('..') || name.includes('/') || name.includes('\\') || name.trim() !== name) {
        return null;
    }
    return name;
}

export function folderBasename(dirPath: string): string {
    const clean = String(dirPath || '').trim().replace(/\/+$/, '');
    if (!clean) return '';
    const parts = clean.split('/').filter(Boolean);
    return parts[parts.length - 1] ?? '';
}

export interface WizardProject {
    id: number;
    name: string;
    path: string;
    root: string;
    defaultLaunchProfile: string | null;
    companyId: number | null;
    color?: string | null;
}

export type ProjectDotRole = 'orange' | 'cyan' | 'yellow' | 'violet' | 'green' | 'muted';

const ACTIVE_DOT_CYCLE: readonly ProjectDotRole[] = ['cyan', 'violet', 'orange', 'yellow', 'green'];

export function projectDotRole(color: string | null | undefined, inDrawer: boolean, index: number): ProjectDotRole {
    if (!inDrawer) return 'muted';
    const key = (color || '').trim().toLowerCase();
    if (key === 'orange' || key === 'coral' || key === 'rose' || key === 'red') return 'orange';
    if (key === 'cyan' || key === 'teal' || key === 'blue') return 'cyan';
    if (key === 'yellow' || key === 'gold' || key === 'amber') return 'yellow';
    if (key === 'violet' || key === 'purple' || key === 'magenta') return 'violet';
    if (key === 'green' || key === 'lime' || key === 'emerald') return 'green';
    return ACTIVE_DOT_CYCLE[Math.abs(index) % ACTIVE_DOT_CYCLE.length]!;
}

export interface WizardAdjacentContext {
    project: WizardProject;
    tabLabel: string;
}

export interface WizardComputer {
    key: string;
    label: string;
    online: boolean;
}

export interface WizardAccount {
    id: string;
    name: string;
    provider: string;
}

export interface FolderCrumb {
    label: string;
    path: string;
}

export interface WizardPayloadInput {
    branch: WizardBranch;
    agentName: string;
    profileId: string;
    model: string | null;
    computerKey: string;
    accountId: string | null;
    storyRef?: string | null;
    project: WizardProject | null;
    newProjectName: string;
    newProjectPath: string;
    disposableCustomPath: string | null;
    useWorktree: boolean;
    worktreeBranch: string;
    dims: { cols?: number; rows?: number };
}

export function filterProfilesForWizard(profiles: readonly ProfileRow[]): ProfileRow[] {
    return visibleProfiles(profiles).filter((p) => p.harness !== 'shell');
}

export function brandColorRole(harness: string, icon: string | null): '' | 'green' | 'violet' | 'yellow' | 'cyan' {
    if (icon === 'logo-antigravity' || harness === 'claude' || harness === 'openclaw') return '';
    if (icon === 'logo-copilot') return 'violet';
    if (harness === 'codex') return 'green';
    if (harness === 'hermes') return 'yellow';
    if (harness === 'local') return 'cyan';
    return '';
}

export function splitProjectsAZ(
    projects: readonly WizardProject[],
    activeRoots: ReadonlySet<string>,
): { drawer: WizardProject[]; older: WizardProject[] } {
    const byName = (a: WizardProject, b: WizardProject) =>
        a.name.localeCompare(b.name, 'en', { sensitivity: 'base' });
    const drawer: WizardProject[] = [];
    const older: WizardProject[] = [];
    for (const p of projects) {
        const normRoot = (p.root || p.path || '').replace(/\/+$/, '');
        const normPath = (p.path || '').replace(/\/+$/, '');
        if ((normRoot && activeRoots.has(normRoot)) || (normPath && activeRoots.has(normPath))) {
            drawer.push(p);
        } else {
            older.push(p);
        }
    }
    drawer.sort(byName);
    older.sort(byName);
    return { drawer, older };
}

export function slugifyProjectName(name: string): string {
    return (
        String(name || '')
            .trim()
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-+|-+$/g, '') || 'new-project'
    );
}

export function joinChildPath(parent: string, child: string): string {
    const base = (parent || '/').replace(/\/+$/, '');
    const leaf = child.replace(/^\/+/, '');
    return `${base}/${leaf}`;
}

export function buildBreadcrumbs(dirPath: string, homeLabel: string, homePath: string | null): FolderCrumb[] {
    const clean = (dirPath || '/').replace(/\/+$/, '') || '/';
    if (homePath) {
        const normHome = homePath.replace(/\/+$/, '');
        if (clean === normHome || clean.startsWith(`${normHome}/`)) {
            const tail = clean.slice(normHome.length).split('/').filter(Boolean);
            const crumbs: FolderCrumb[] = [{ label: homeLabel, path: normHome }];
            let cur = normHome;
            for (const seg of tail) {
                cur = `${cur}/${seg}`;
                crumbs.push({ label: seg, path: cur });
            }
            return crumbs;
        }
    }
    const parts = clean.split('/').filter(Boolean);
    if (!parts.length) return [{ label: '/', path: '/' }];
    const crumbs: FolderCrumb[] = [{ label: '/', path: '/' }];
    let acc = '';
    for (const seg of parts) {
        acc = `${acc}/${seg}`;
        crumbs.push({ label: seg, path: acc });
    }
    return crumbs;
}

export function shortenPath(dirPath: string, homePath: string | null): string {
    if (!dirPath) return '';
    if (homePath) {
        const normHome = homePath.replace(/\/+$/, '');
        if (dirPath === normHome) return '~';
        if (dirPath.startsWith(`${normHome}/`)) return `~${dirPath.slice(normHome.length)}`;
    }
    return dirPath;
}

export function buildWizardSessionPayload(input: WizardPayloadInput): Record<string, unknown> {
    const isLocal = !input.computerKey || input.computerKey === 'local';
    const trimmedName = input.agentName.trim();
    const payload: Record<string, unknown> = {
        auto_start_claude: true,
        copy_templates: false,
        agent_type: input.profileId,
        ...input.dims,
    };

    if (trimmedName) {
        payload.label = trimmedName;
    }
    if (!isLocal) {
        payload.host_key = input.computerKey;
    }
    if (isLocal && input.model) {
        payload.model = input.model;
    }
    if (isLocal && input.accountId) {
        payload.account_id = input.accountId;
    }
    if (isLocal && input.storyRef) {
        payload.story_ref = input.storyRef;
    }

    if (input.branch === 'disposable') {
        payload.disposable = true;
        payload.project_name = 'Disposable';
        if (input.disposableCustomPath) {
            payload.working_dir = input.disposableCustomPath;
        }
    } else if (input.branch === 'existing') {
        if (input.project) {
            payload.project_name = input.project.name;
            payload.working_dir = input.project.path || input.project.root;
        }
        if (isLocal && input.useWorktree && input.worktreeBranch.trim()) {
            payload.worktree = { branch: input.worktreeBranch.trim() };
        }
    } else if (input.branch === 'new_project') {
        const pname = input.newProjectName.trim();
        payload.project_name = pname;
        if (!trimmedName && pname) {
            payload.label = pname;
        }
        payload.working_dir = input.newProjectPath;
        payload.copy_templates = isLocal;
    }

    return payload;
}
