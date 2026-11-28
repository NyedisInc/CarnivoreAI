import * as M from './group-membership';
import { ruleOf, type GroupRule } from './group-rule';
import { readKey, writeKey } from './storage';

export const STATUS_UNKNOWN = 'unknown';
export const STATUS_OK = 'ok';
export const STATUS_UNAVAILABLE = 'unavailable';

export const BAND_PINNED = 'pinned';
export const BAND_OTHER = 'other';
export const BAND_GROUP_PREFIX = 'g:';
export const BAND_PROJECT_PREFIX = 'p:';
/* could not be determined */
export const BAND_ROGUE = 'rogue';

export interface SessionGroup {
    group_uuid: string;
    name: string;
    position: number;
    members: string[];
    member_session_uuids: string[];
    colour: string | null;
    gradient: string | null;
    animation: string;
    icon: string | null;
    rule: GroupRule | null;
    parent_key: string | null;
}

export interface GroupState {
    status: string;
    groups: SessionGroup[];
    detail: string | null;
}

export interface BandIntent {
    pinned: boolean;
    group: string | null | undefined;
}

let state: GroupState = { status: STATUS_UNKNOWN, groups: [], detail: null };

export function bandKeyFor(groupUuid: string): string {
    return BAND_GROUP_PREFIX + groupUuid;
}

export function groupUuidOf(key: unknown): string | null {
    if (typeof key !== 'string') return null;
    if (key.indexOf(BAND_GROUP_PREFIX) !== 0) return null;
    return key.slice(BAND_GROUP_PREFIX.length) || null;
}

export function apply(body: unknown): GroupState {
    const b = body as { status?: unknown; groups?: unknown; detail?: unknown } | null;
    const ok = !!b && typeof b === 'object' && b.status === STATUS_OK && Array.isArray(b.groups);
    if (!ok) {
        const detail = (b && typeof b === 'object' && b.detail) ? String(b.detail) : 'the groups could not be read';
        state = { status: STATUS_UNAVAILABLE, groups: [], detail };
        M.clear();
        return state;
    }
    const groups = (b!.groups as Array<Record<string, unknown>>)
        .filter((g) => g && typeof g.group_uuid === 'string' && g.group_uuid)
        .map((g): SessionGroup => ({
            group_uuid: g.group_uuid as string,
            name: typeof g.name === 'string' ? g.name : '',
            position: Number.isFinite(g.position) ? g.position as number : 0,
            members: Array.isArray(g.members) ? (g.members as string[]).filter((n) => !!n) : [],
            member_session_uuids: Array.isArray(g.member_session_uuids)
                ? (g.member_session_uuids as string[]).filter((u) => !!u) : [],
            colour: typeof g.colour === 'string' ? g.colour : null,
            gradient: typeof g.gradient === 'string' ? g.gradient : null,
            animation: typeof g.animation === 'string' ? g.animation : 'none',
            icon: typeof g.icon === 'string' && g.icon ? g.icon : null,
            rule: ruleOf(g.rule),
            parent_key: typeof g.parent_key === 'string' && g.parent_key ? g.parent_key : null,
        }))
        .sort((x, y) => (x.position - y.position) || (x.group_uuid < y.group_uuid ? -1 : 1));
    M.rebuild(groups);
    state = { status: STATUS_OK, groups, detail: null };
    return state;
}

export function markUnavailable(detail: unknown): GroupState {
    state = {
        status: STATUS_UNAVAILABLE,
        groups: [],
        detail: detail ? String(detail) : 'the groups could not be read',
    };
    M.clear();
    return state;
}

export function current(): GroupState {
    return state;
}

export function isUsable(): boolean {
    return state.status === STATUS_OK;
}

export function noticeText(): string | null {
    if (state.status !== STATUS_UNAVAILABLE) return null;
    return `groups unavailable: ${state.detail}`;
}

export function groupOf(name: string): string | null {
    return M.groupOf(name);
}

export function groupByUuid(groupUuid: string | null | undefined): SessionGroup | null {
    if (!groupUuid) return null;
    return state.groups.find((g) => g.group_uuid === groupUuid) || null;
}

export function setOptimistic(name: string, groupUuid: string | null): string | null {
    const previous = groupOf(name);
    M.setLocal(name, groupUuid);
    return previous;
}

export function bandOf(name: string, pinned: boolean): string {
    if (pinned) return BAND_PINNED;
    if (!isUsable()) return BAND_OTHER;
    const uuid = groupOf(name);
    return uuid ? bandKeyFor(uuid) : BAND_OTHER;
}

let previewGroups: string[] | null = null;

export function previewGroupOrder(uuids: readonly string[] | null): void {
    previewGroups = uuids ? [...uuids] : null;
}

function orderedGroups(): SessionGroup[] {
    if (!previewGroups) return state.groups;
    const byId = new Map(state.groups.map((g) => [g.group_uuid, g]));
    const out: SessionGroup[] = [];
    const seen = new Set<string>();
    for (const uuid of previewGroups) {
        const g = byId.get(uuid);
        if (g && !seen.has(uuid)) { out.push(g); seen.add(uuid); }
    }
    for (const g of state.groups) if (!seen.has(g.group_uuid)) out.push(g);
    return out;
}

export function childrenOf(parentKey: string | null): SessionGroup[] {
    if (!isUsable()) return [];
    const want = parentKey || null;
    return orderedGroups().filter((g) => (g.parent_key ?? null) === want);
}

export function siblingsOf(groupUuid: string): SessionGroup[] {
    const target = groupByUuid(groupUuid);
    if (!target) return [];
    const want = target.parent_key ?? null;
    return state.groups.filter((g) => (g.parent_key ?? null) === want);
}

export function isInsidePinned(groupUuid: string): boolean {
    const seen = new Set<string>();
    let cur: SessionGroup | null = groupByUuid(groupUuid);
    while (cur && !seen.has(cur.group_uuid)) {
        seen.add(cur.group_uuid);
        if (cur.parent_key === BAND_PINNED) return true;
        const nextUuid = groupUuidOf(cur.parent_key);
        cur = nextUuid ? groupByUuid(nextUuid) : null;
    }
    return false;
}

export function bandOrder(): string[] {
    const keys = [BAND_PINNED];
    if (isUsable()) for (const g of childrenOf(null)) keys.push(bandKeyFor(g.group_uuid));
    keys.push(BAND_OTHER);
    return keys;
}

export function labelFor(key: string): string {
    if (key === BAND_PINNED) return 'pinned';
    if (key === BAND_OTHER) return 'other';
    const group = groupByUuid(groupUuidOf(key));
    return group ? group.name : 'unknown group';
}

export function bandIntent(key: string): BandIntent {
    if (key === BAND_PINNED) return { pinned: true, group: undefined };
    const uuid = groupUuidOf(key);
    if (uuid) return { pinned: isInsidePinned(uuid), group: uuid };
    return { pinned: false, group: null };
}

export function projectBandKeyFor(projectId: unknown): string {
    return BAND_PROJECT_PREFIX + String(projectId);
}

export function isFilingBand(key: unknown): boolean {
    if (typeof key !== 'string' || !key) return false;
    if (key === BAND_PINNED || key === BAND_OTHER) return true;
    return key.indexOf(BAND_GROUP_PREFIX) === 0 && key.length > BAND_GROUP_PREFIX.length;
}

export const PROJECTS_OPEN_KEY = 'carnivore.session.sidebar.projects.open';

let projectsOpenCache: boolean | null = null;

const projectsListeners: Array<(open: boolean) => void> = [];

export function onProjectsOpenChange(fn: (open: boolean) => void): void {
    if (typeof fn === 'function') projectsListeners.push(fn);
}

export function isProjectsOpen(): boolean {
    if (projectsOpenCache !== null) return projectsOpenCache;
    let raw: string | null = null;
    try {
        raw = readKey(PROJECTS_OPEN_KEY);
    } catch {
        console.warn('SessionSidebarGroupStore: projects-open storage unreadable, defaulting open');
        projectsOpenCache = true;
        return true;
    }
    projectsOpenCache = (raw === null || raw === undefined || raw === '') ? true : raw !== '0';
    return projectsOpenCache;
}

export function setProjectsOpen(open: boolean): boolean {
    projectsOpenCache = !!open;
    const value = projectsOpenCache;
    for (const fn of projectsListeners) {
        try {
            fn(value);
        } catch (err) {
            console.warn('SessionSidebarGroupStore: projects listener failed', err);
        }
    }
    try {
        writeKey(PROJECTS_OPEN_KEY, value ? '1' : '0');
    } catch (err) {
        console.warn('SessionSidebarGroupStore: could not persist projects-open:', err);
    }
    return value;
}

export function toggleProjectsOpen(): boolean {
    return setProjectsOpen(!isProjectsOpen());
}

export function resetProjectsCache(): void {
    projectsOpenCache = null;
}

export function reset(): void {
    state = { status: STATUS_UNKNOWN, groups: [], detail: null };
    M.clear();
    M.setIdentities([]);
    projectsOpenCache = null;
}

export const setIdentities = M.setIdentities;
export const setRuleContext = M.setRuleContext;
export const getRuleContext = M.getRuleContext;
export const handPickedRowsFor = M.handPickedRowsFor;
export const listedRows = M.listedRows;
export const countMatching = M.countMatching;
export const subscribeRows = M.subscribeRows;
export const uuidOfName = M.uuidOfName;
export const memberRank = M.memberRank;
