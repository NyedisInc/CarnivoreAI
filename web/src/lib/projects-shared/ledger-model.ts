/*  hidden  */
import { companyImageUrl, projectImageUrl, type Company } from '../companies';
import type { HistoryGroup, HistorySession } from './history-api';
import { ORPHANED } from './route';

export type SessionGroup = 'running' | 'sleeping' | 'closed';

export const SESSION_GROUPS: readonly SessionGroup[] = ['running', 'sleeping', 'closed'];

export const CLOSED_PREVIEW = 6;

export const CLOSED_SLACK = 2;

export function previewOf(total: number, open: boolean): number {
    return open || total <= CLOSED_PREVIEW + CLOSED_SLACK ? total : CLOSED_PREVIEW;
}

export const PROJECT_SORTS = ['name', 'recent', 'running', 'sleeping', 'closed', 'active'] as const;
export type ProjectSort = (typeof PROJECT_SORTS)[number];
export type SortDir = 'asc' | 'desc';

export const defaultDir = (sort: ProjectSort): SortDir => (sort === 'name' ? 'asc' : 'desc');

export interface ProjectRow {
    readonly key: string;
    readonly name: string;
    readonly archived: boolean;
    readonly movedTo: string | null;
    readonly automatedOnly: boolean;
    readonly hidden: boolean;
    readonly running: number;
    readonly sleeping: number;
    readonly closed: number;
    readonly activity: readonly number[];
    readonly lastActive: string | null;
    readonly imageUrl: string | null;
    readonly group: HistoryGroup;
}

const countOf = (record: Readonly<Record<string, number>> | undefined, state: string): number => record?.[state] ?? 0;

export function isHiddenProject(group: HistoryGroup): boolean {
    return Boolean(group.project?.archived_at) || isAutomatedOnly(group);
}

export function projectShown(group: HistoryGroup, showHidden: boolean, showArchived: boolean): boolean {
    if (group.project?.archived_at) return showArchived;
    return showHidden || !isAutomatedOnly(group);
}

export function isAutomatedOnly(group: HistoryGroup): boolean {
    const automated = Object.values(group.automated_counts ?? {}).reduce((a, b) => a + b, 0);
    return group.session_total > 0 && automated === group.session_total;
}

export function projectRow(group: HistoryGroup, showHidden: boolean, fallbackName: string): ProjectRow {
    const own = (state: string): number =>
        countOf(group.counts, state) - (showHidden ? 0 : countOf(group.automated_counts, state));
    return {
        key: group.key,
        name: group.project?.name ?? fallbackName,
        archived: Boolean(group.project?.archived_at),
        movedTo: group.project?.pack_state === 'moved_away' ? (group.project.moved_to_label ?? '') : null,
        automatedOnly: isAutomatedOnly(group),
        hidden: isHiddenProject(group),
        running: own('running'),
        sleeping: own('asleep'),
        closed: own('closed') + own('unknown') + (showHidden ? own('removed') : 0),
        activity: group.activity_days ?? [],
        lastActive: group.last_activity_at,
        imageUrl: group.project ? projectImageUrl({ name: group.project.name, has_image: Boolean(group.project.has_image), image_rev: group.project.image_rev ?? null }) : null,
        group,
    };
}

/*  hidden  */
export function projectRows(
    groups: readonly HistoryGroup[],
    options: { query: string; showHidden: boolean; showArchived?: boolean; sort: ProjectSort; dir?: SortDir; fallbackName: string },
): ProjectRow[] {
    const needle = options.query.trim().toLowerCase();
    const rows = groups
        .filter((g) => projectShown(g, options.showHidden, options.showArchived ?? false))
        .map((g) => projectRow(g, options.showHidden, options.fallbackName))
        .filter((r) => !needle || r.name.toLowerCase().includes(needle));
    return sortProjectRows(rows, options.sort, options.dir ?? defaultDir(options.sort));
}

export function sortProjectRows(rows: readonly ProjectRow[], sort: ProjectSort, dir: SortDir): ProjectRow[] {
    const value = (r: ProjectRow): number | string | null => {
        if (sort === 'name') return r.name;
        if (sort === 'recent') return r.lastActive ? Date.parse(r.lastActive) || null : null;
        if (sort === 'active') return r.activity.reduce((a, b) => a + b, 0) || null;
        return r[sort] || null;
    };
    const byName = (a: ProjectRow, b: ProjectRow): number => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
    const sign = dir === 'asc' ? 1 : -1;
    return [...rows].sort((a, b) => {
        const x = value(a);
        const y = value(b);
        if (x === null || y === null) return x === y ? byName(a, b) : x === null ? 1 : -1;
        const c = typeof x === 'string' ? x.localeCompare(y as string, undefined, { sensitivity: 'base' }) : x - (y as number);
        return c * sign || byName(a, b);
    });
}

/*  hidden  */
export const hiddenProjectCount = (groups: readonly HistoryGroup[]): number =>
    groups.filter((g) => !g.project?.archived_at && isAutomatedOnly(g)).length;

export const archivedProjectCount = (groups: readonly HistoryGroup[]): number => groups.filter((g) => Boolean(g.project?.archived_at)).length;

/*  hidden  */
export function isHiddenSession(session: HistorySession, projectAutomatedOnly: boolean): boolean {
    if (session.state === 'removed') return true;
    return session.kind === 'automated' && !projectAutomatedOnly;
}

export function groupOf(session: HistorySession): SessionGroup {
    if (session.state === 'running') return 'running';
    if (session.state === 'asleep') return 'sleeping';
    return 'closed';
}

export function sessionGroups(
    group: HistoryGroup,
    options: { showHidden: boolean; query: string },
): Record<SessionGroup, HistorySession[]> {
    const automatedOnly = isAutomatedOnly(group);
    const needle = options.query.trim().toLowerCase();
    const out: Record<SessionGroup, HistorySession[]> = { running: [], sleeping: [], closed: [] };
    for (const s of group.sessions) {
        if (!options.showHidden && isHiddenSession(s, automatedOnly)) continue;
        if (needle && !s.title.toLowerCase().includes(needle)) continue;
        out[groupOf(s)].push(s);
    }
    for (const list of Object.values(out)) list.sort((a, b) => Date.parse(b.last_activity_at ?? '') - Date.parse(a.last_activity_at ?? ''));
    return out;
}

/*  hidden  */
export function hiddenSessionCount(group: HistoryGroup): number {
    const automatedOnly = isAutomatedOnly(group);
    return group.sessions.filter((s) => isHiddenSession(s, automatedOnly)).length;
}

export type PrimaryId = 'open' | 'wake' | 'resume' | 'restart' | 'none';

export interface Primary {
    readonly id: PrimaryId;
    readonly disabledReasonKey?: string;
}

export function primaryAction(session: HistorySession): Primary {
    switch (session.state) {
        case 'running':
            return session.host_key === 'local' || session.live_session_id ? { id: 'open' } : { id: 'none' };
        case 'asleep':
            return { id: 'wake' };
        default:
            break;
    }
    if (session.has_transcript) return { id: 'resume' };
    if (!session.claude_session_uuid) return { id: 'restart' };
    return { id: 'none', disabledReasonKey: 'projects.page.primary.gone_reason' };
}

export function diskTag(session: HistorySession): 'on-disk' | 'gone' | null {
    if (session.state === 'running' || session.state === 'asleep') return null;
    if (!session.claude_session_uuid) return null;
    return session.has_transcript ? 'on-disk' : 'gone';
}

export function findSession(
    groups: readonly HistoryGroup[],
    sessionUuid: string,
): { group: HistoryGroup; session: HistorySession } | null {
    for (const group of groups) {
        const session = group.sessions.find((s) => s.session_uuid === sessionUuid);
        if (session) return { group, session };
    }
    return null;
}

export function ageLabel(
    iso: string | null,
    now: number,
    format: { minutes: (n: number) => string; hours: (n: number) => string; days: (n: number) => string; date: (d: Date) => string },
): string {
    const at = iso ? Date.parse(iso) : Number.NaN;
    if (Number.isNaN(at)) return '';
    const minutes = Math.max(0, Math.floor((now - at) / 60_000));
    if (minutes < 60) return format.minutes(minutes);
    if (minutes < 1440) return format.hours(Math.floor(minutes / 60));
    if (minutes < 7 * 1440) return format.days(Math.floor(minutes / 1440));
    return format.date(new Date(at));
}

export function transcriptPath(session: HistorySession): string | null {
    if (!session.has_transcript || !session.claude_session_uuid || !session.working_dir) return null;
    return `~/.claude/projects/${session.working_dir.replace(/[^A-Za-z0-9]/g, '-')}/${session.claude_session_uuid}.jsonl`;
}

export type ProjectActionId =
    | 'new-session'
    | 'rename-project'
    | 'copy-path'
    | 'load-blueprint'
    | 'turn-on-agent'
    | 'archive-project'
    | 'unarchive-project'
    | 'pack-folder'
    | 'unpack-folder'
    | 'delete-project';

export interface ProjectAction {
    readonly id: ProjectActionId;
    readonly labelKey: string;
    readonly sep?: boolean;
}

export interface MenuItem {
    readonly id: string;
    readonly labelKey?: string;
    readonly label?: string;
    readonly sep?: boolean;
    readonly checked?: boolean;
    readonly children?: readonly MenuItem[];
}

export const SET_COMPANY = 'set-company:';

export const PICK_COLOR = 'pick-color';
export const SET_COLOR = 'set-color:';

export function companyKeyOf(group: HistoryGroup): string {
    const id = group.project?.company_id;
    return typeof id === 'number' ? String(id) : ORPHANED;
}

export interface CompanyCardRow {
    readonly key: string;
    readonly id: number;
    readonly name: string;
    readonly count: number;
    readonly imageUrl: string | null;
    readonly hasImage: boolean;
}

/*  hidden  */
export function companyCards(
    companies: readonly Company[],
    groups: readonly HistoryGroup[],
    showHidden: boolean,
    query = '',
    state = 'all',
    showArchived = false,
): CompanyCardRow[] {
    const members = new Map<string, ProjectRow[]>();
    for (const g of groups) {
        if (!projectShown(g, showHidden, showArchived)) continue;
        const key = companyKeyOf(g);
        members.set(key, [...(members.get(key) ?? []), projectRow(g, showHidden, '')]);
    }
    const needle = query.trim().toLowerCase();
    const sorted = [...companies].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) || a.id - b.id);
    return sorted
        .filter((c) => {
            const projects = members.get(String(c.id)) ?? [];
            const passing = projects.filter((r) => projectPassesState(r, state));
            if (state !== 'all' && passing.length === 0) return false;
            return !needle || c.name.toLowerCase().includes(needle) || passing.some((r) => r.name.toLowerCase().includes(needle));
        })
        .map((c) => ({ key: String(c.id), id: c.id, name: c.name, count: members.get(String(c.id))?.length ?? 0, imageUrl: companyImageUrl(c), hasImage: Boolean(c.has_image) }));
}

export function projectPassesState(r: ProjectRow, state: string): boolean {
    if (state === 'running') return r.running > 0;
    if (state === 'asleep') return r.sleeping > 0;
    if (state === 'quiet') return r.running === 0 && r.sleeping === 0;
    return true;
}

export function projectActions(
    project: { readonly archived_at: string | null; readonly root?: string | null; readonly company_id?: number | null; readonly has_image?: boolean; readonly storage?: { readonly state: string; readonly packed_in?: number | null } | null; readonly pack_state?: string | null },
    companies: readonly Company[] = [],
    withColor = false,
    agentOffered = false,
): readonly MenuItem[] {
    const hidden = Boolean(project.archived_at);
    const out: MenuItem[] = [];
    if (!hidden) out.push({ id: 'new-session', labelKey: 'projects.page.action.new_session_here' });
    out.push({ id: 'rename-project', labelKey: 'projects.page.action.rename_project' });
    if (withColor) out.push({ id: PICK_COLOR, labelKey: 'projects.page.action.color' });
    if (project.root) out.push({ id: 'copy-path', labelKey: 'projects.page.action.copy_path' });
    if (!hidden) out.push({ id: 'load-blueprint', labelKey: 'layout.row.load_blueprint' });
    if (agentOffered && !hidden) out.push({ id: 'turn-on-agent', labelKey: 'projects.page.action.turn_on_agent' });
    if (project.pack_state === 'moved_away') out.push({ id: 'migrate-back', labelKey: 'projects.page.action.move_back' });
    else if (!hidden) out.push({ id: 'migrate-project', labelKey: 'projects.page.action.move_computer' });
    out.push({ id: 'set-image', labelKey: 'projects.page.action.set_image' });
    if (project.has_image) out.push({ id: 'remove-image', labelKey: 'projects.page.action.remove_image' });
    out.push({ id: 'regenerate-art', labelKey: 'projects.page.action.regenerate_art' });
    const byName = [...companies].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
    out.push({
        id: 'add-to-company',
        labelKey: 'projects.page.action.add_company',
        children: [
            ...byName.map((c) => ({ id: `${SET_COMPANY}${c.id}`, label: c.name, checked: c.id === project.company_id })),
            { id: 'new-company-for-project', labelKey: 'projects.page.action.new_company_ellipsis', sep: byName.length > 0 },
        ],
    });
    if (typeof project.company_id === 'number') out.push({ id: 'remove-from-company', labelKey: 'projects.page.action.remove_from_company' });
    //  hidden 
    const state = project.storage?.state ?? 'unpacked';
    const packed = state === 'packed';
    const busy = !packed && state !== 'unpacked';
    if (hidden && !busy && !packed) out.push({ id: 'pack-folder', labelKey: 'projects.page.action.pack_folder', sep: true });
    if (packed && !project.storage?.packed_in) out.push({ id: 'unpack-folder', labelKey: 'projects.page.action.unpack_folder', sep: true });
    if (hidden && !packed && !busy) out.push({ id: 'unarchive-project', labelKey: 'projects.page.action.unarchive_project', sep: !out.at(-1)?.sep });
    if (!hidden) out.push({ id: 'archive-project', labelKey: 'projects.page.action.archive_project', sep: true });
    out.push({ id: 'delete-project', labelKey: 'projects.page.action.delete_project' });
    return out;
}

export function companyActions(hasImage = false): readonly MenuItem[] {
    return [
        { id: 'rename-company', labelKey: 'projects.page.action.rename_company' },
        { id: 'migrate-company', labelKey: 'projects.page.action.move_computer' },
        { id: 'set-image', labelKey: 'projects.page.action.set_image' },
        ...(hasImage ? [{ id: 'remove-image', labelKey: 'projects.page.action.remove_image' }] : []),
        { id: 'regenerate-art', labelKey: 'projects.page.action.regenerate_art' },
        { id: 'delete-company', labelKey: 'projects.page.action.delete_company', sep: true },
    ];
}

/*  hidden  */
export function projectLead(project: { readonly archived_at: string | null; readonly storage?: { readonly state: string; readonly packed_in?: number | null } | null }): ProjectAction {
    if (project.storage?.state === 'packed' && !project.storage.packed_in) return { id: 'unpack-folder', labelKey: 'projects.page.action.unpack_folder' };
    return project.archived_at
        ? { id: 'unarchive-project', labelKey: 'projects.page.action.unarchive_project' }
        : { id: 'new-session', labelKey: 'projects.page.action.new_session' };
}
