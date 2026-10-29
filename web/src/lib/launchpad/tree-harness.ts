import { mount, unmount } from 'svelte';

import ProjectTree from './ProjectTree.svelte';
import { sessionStore } from '../sessions/store.svelte';
import { treeCollapse } from './tree-collapse.svelte';
import { uiPrefs } from '../ui/prefs.svelte';
import type { ProjectChromeControl } from './project-chrome-control';
import type { ProjectTreeHost } from './project-tree-host';
import type { TreeSessionRow } from './project-groups';
import type { SessionHost } from '../sessions/host';
import type {
    AttachableSession,
    ProjectAuthority,
    ProjectPresenceRow,
    ProjectRow,
    RunningSessionRow,
    SessionRecord,
} from '../sessions/types';

export interface HostCall {
    method: string;
    arg: unknown;
}

export interface RecordingHost extends ProjectTreeHost {
    calls: HostCall[];
}

export function recordingHost(): RecordingHost {
    const calls: HostCall[] = [];
    const note = (method: string, arg: unknown) => {
        calls.push({ method, arg });
    };
    return {
        calls,
        selectProject: (p) => note('selectProject', p),
        explainRefused: (p) => note('explainRefused', p),
        editProject: (p) => note('editProject', p),
        archiveProject: async (n) => { note('archiveProject', n); },
        unarchiveProject: async (n) => { note('unarchiveProject', n); },
        returnToActive: async (id) => { note('returnToActive', id); },
        attachSession: async (n) => { note('attachSession', n); },
        restartEnded: async (r) => { note('restartEnded', r); },
        archiveRecord: async (u) => { note('archiveRecord', u); },
        displayLabel: (row: TreeSessionRow) => {
            const label = typeof row.label === 'string' ? row.label.trim() : '';
            if (label) return label;
            const name = row.name || '';
            return name.startsWith('cloude_') ? name.slice('cloude_'.length) : name;
        },
        reloadProjects: async () => { note('reloadProjects', null); },
    };
}

export interface RecordingControl extends ProjectChromeControl {
    toggleStates: Array<{ on: boolean; title: string }>;
    click(): void;
}

export function recordingControl(): RecordingControl {
    const toggleStates: Array<{ on: boolean; title: string }> = [];
    let handler: (() => void) | null = null;
    return {
        toggleStates,
        setArchivedToggle(on, title) { toggleStates.push({ on, title }); },
        bindArchivedToggle(onClick) { handler = onClick; },
        click() { if (handler) handler(); },
    };
}

export interface TreeFixture {
    projects?: ProjectRow[];
    presence?: Map<string, ProjectPresenceRow>;
    authority?: ProjectAuthority | null;
    archivedFetchOk?: boolean | null;
    runningSessions?: RunningSessionRow[];
    sessionRecords?: SessionRecord[];
    sessionAttribution?: Map<string, SessionRecord>;
    sessionAttributionByInstance?: Map<string, SessionRecord>;
    sessionAttributionAmbiguous?: Set<string>;
    sessionAttributionListingOk?: boolean;
    sessionAttributionListingDetail?: string | null;
    workStampByName?: Map<string, string>;
}

export function applyFixture(fixture: TreeFixture): void {
    sessionStore.projects = fixture.projects ?? [];
    sessionStore.projectPresence = fixture.presence ?? new Map();
    sessionStore.projectAuthority = fixture.authority === undefined
        ? { mode: 'db', degraded: false, writable: true }
        : fixture.authority;
    sessionStore.archivedFetchOk = fixture.archivedFetchOk ?? null;
    sessionStore.runningSessions = fixture.runningSessions ?? [];
    sessionStore.sessionRecords = fixture.sessionRecords ?? [];
    sessionStore.sessionAttribution = fixture.sessionAttribution ?? new Map();
    sessionStore.sessionAttributionByInstance =
        fixture.sessionAttributionByInstance ?? new Map();
    sessionStore.sessionAttributionAmbiguous =
        fixture.sessionAttributionAmbiguous ?? new Set();
    sessionStore.sessionAttributionListingOk =
        fixture.sessionAttributionListingOk ?? true;
    sessionStore.sessionAttributionListingDetail =
        fixture.sessionAttributionListingDetail ?? null;
    sessionStore.workStampByName = fixture.workStampByName ?? new Map();
}

export interface MountedTree {
    container: HTMLElement;
    host: RecordingHost;
    control: RecordingControl;
    destroy(): void;
}

export function mountTree(fixture: TreeFixture = {}): MountedTree {
    treeCollapse.resetForTests();
    uiPrefs.resetForTests();
    applyFixture(fixture);
    const container = document.createElement('div');
    container.id = 'project-list';
    document.body.appendChild(container);
    const host = recordingHost();
    const control = recordingControl();
    const instance = mount(ProjectTree, {
        target: container,
        props: { host, control },
    });
    return {
        container,
        host,
        control,
        destroy() {
            unmount(instance, { outro: false });
            container.remove();
            sessionStore.reset();
            treeCollapse.resetForTests();
            uiPrefs.resetForTests();
        },
    };
}

function subtreeSize(list: NodeList): number {
    let total = 0;
    for (const node of Array.from(list)) {
        total += 1;
        if (node.nodeType === 1) {
            total += (node as Element).querySelectorAll('*').length;
        }
    }
    return total;
}

export function watchMutations(container: HTMLElement): {
    stop(): { records: number; nodes: number };
} {
    const seen: MutationRecord[] = [];
    const observer = new MutationObserver((batch) => {
        seen.push(...batch);
    });
    observer.observe(container, {
        childList: true,
        subtree: true,
        attributes: true,
        characterData: true,
    });
    return {
        stop() {
            seen.push(...observer.takeRecords());
            observer.disconnect();
            let nodes = 0;
            for (const record of seen) {
                nodes += subtreeSize(record.addedNodes);
                nodes += subtreeSize(record.removedNodes);
            }
            return { records: seen.length, nodes };
        },
    };
}

export async function settle(): Promise<void> {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
}

export function fixtureHost(fleet: Harbor): SessionHost {
    return {
        getProjects: async () => fleet.projects.slice(),
        getProjectsPresence: async () => ({ status: 'ok', projects: [] }),
        getProjectsAuthority: async () => ({
            mode: 'db', degraded: false, writable: true,
        }),
        listAttachableSessions: async () => fleet.attachable.map((r) => ({ ...r })),
        listSessions: async () => [],
        getCurrentSession: async () => null,
        listSessionRecords: async () => fleet.records.map((r) => ({ ...r })),
    };
}

export interface Harbor {
    projects: ProjectRow[];
    attachable: AttachableSession[];
    records: SessionRecord[];
}

export function fleet(opts: {
    projects?: number;
    perProject?: number;
    working?: string[];
} = {}): Harbor {
    const projectCount = opts.projects ?? 9;
    const per = opts.perProject ?? 5;
    const working = new Set(opts.working ?? []);
    const projects: ProjectRow[] = [];
    const attachable: AttachableSession[] = [];
    const records: SessionRecord[] = [];
    for (let p = 0; p < projectCount; p++) {
        projects.push({
            id: p, name: `project-${p}`, path: `/p${p}`, root: `/p${p}`,
            description: '', archived_at: null, work_at: null,
        });
        for (let s = 0; s < per; s++) {
            const name = `cloude_p${p}_s${s}`;
            const epoch = p * 100 + s;
            attachable.push({
                name, label: null, created_by_cloude: true,
                created_at_epoch: epoch, window_count: 1,
                agent_type: 'claude', agent_family: 'claude',
                agent_family_source: 'wrapper', agent_wrapper_label: null,
                pinned_theme: null, session_row_id: epoch,
                parent_session_id: null,
                status: working.has(name) ? 'working' : 'idle',
                unread: false, listing_ok: true, listing_reason: null,
            });
            records.push({
                session_uuid: `u${epoch}`, id: epoch, tmux_name: name,
                tmux_created_epoch: epoch, lifecycle: 'running',
                project_id: p, project_attribution: 'project',
                working_dir: `/p${p}`, archived_at: null, title: null,
                parent_session_id: null, last_work_at: null, owned: true,
                agent_type: 'claude', agent_family: 'claude',
                agent_family_source: 'wrapper',
            });
        }
    }
    return { projects, attachable, records };
}
