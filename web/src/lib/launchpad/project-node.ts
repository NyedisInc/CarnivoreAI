import type { ProjectPresenceRow, ProjectRow } from '../sessions/types';
import type { TreeSessionRow } from './project-groups';

/* could not */
export type PresenceState = 'unchecked' | 'present' | 'missing' | 'unreachable';

export interface ProjectNodeView {
    project: ProjectRow;
    index: number;
    name: string;
    path: string;
    description: string;
    hasDescription: boolean;
    presenceState: PresenceState;
    presenceDetail: string | null;
    isDisabled: boolean;
    isArchived: boolean;
    projectId: number | null;
    children: TreeSessionRow[];
    hasChildren: boolean;
    nodeKey: string;
    foldable: boolean;
    work: WorkAttrs;
}

export interface WorkAttrs {
    state: 'recorded' | 'unrecorded';
    at: string | null;
    titleKey: string | null;
}

export const PROJECT_WORK_UNRECORDED_KEY = 'project.work.unrecorded';
export const SESSION_WORK_UNRECORDED_KEY = 'session.work.unrecorded';

export function workAttrs(
    stamp: string | null | undefined,
    titleKey: string,
): WorkAttrs {
    if (stamp) return { state: 'recorded', at: stamp, titleKey: null };
    return { state: 'unrecorded', at: null, titleKey };
}

export function presenceFor(
    project: ProjectRow,
    presence: Map<string, ProjectPresenceRow>,
): ProjectPresenceRow | null {
    const root = typeof project.root === 'string' ? project.root : null;
    const path = typeof project.path === 'string' ? project.path : null;
    if (root && presence.has(root)) return presence.get(root) || null;
    if (path && presence.has(path)) return presence.get(path) || null;
    return null;
}

export function resolveProjectId(
    project: ProjectRow,
    presenceRow: ProjectPresenceRow | null,
): number | null {
    const own = project.id;
    if (own !== null && own !== undefined) return own as number;
    if (presenceRow) {
        const fromPresence = (presenceRow as { id?: unknown }).id;
        if (fromPresence !== null && fromPresence !== undefined) {
            return fromPresence as number;
        }
    }
    return null;
}

export interface NodeDeps {
    presence: Map<string, ProjectPresenceRow>;
    byProjectId: Map<number, TreeSessionRow[]>;
}

export function projectNodeKey(name: string, projectId: number | null): string {
    return 'project:' + (projectId ?? name);
}

export function projectNodeView(
    project: ProjectRow,
    index: number,
    deps: NodeDeps,
): ProjectNodeView {
    const presenceRow = presenceFor(project, deps.presence);
    const rawState = presenceRow
        ? (presenceRow as { presence?: unknown }).presence
        : undefined;
    const presenceState: PresenceState =
        rawState === 'missing' || rawState === 'unreachable' || rawState === 'present'
            ? rawState
            : 'unchecked';
    const isDisabled = presenceState === 'missing' || presenceState === 'unreachable';
    const presenceDetail = presenceRow
        ? ((presenceRow as { presence_detail?: unknown }).presence_detail as string)
            || null
        : null;

    const rawDescription = (
        typeof project.description === 'string' ? project.description : ''
    ).trim();

    const projectId = resolveProjectId(project, presenceRow);
    const children = projectId !== null
        ? (deps.byProjectId.get(projectId) || [])
        : [];
    const hasChildren = children.length > 0;
    const hasDescription = rawDescription.length > 0;
    const name = typeof project.name === 'string' ? project.name : '';

    return {
        project,
        index,
        name,
        path: typeof project.path === 'string' ? project.path : '',
        description: rawDescription,
        hasDescription,
        presenceState,
        presenceDetail,
        isDisabled,
        isArchived: !!project.archived_at,
        projectId,
        children,
        hasChildren,
        nodeKey: projectNodeKey(name, projectId),
        foldable: hasChildren || hasDescription,
        work: workAttrs(
            typeof project.work_at === 'string' ? project.work_at : null,
            PROJECT_WORK_UNRECORDED_KEY,
        ),
    };
}
