import * as G from './group-store';
import { matchesRow } from './search';

export interface BucketRow {
    name: string;
    kind?: unknown;
    agent_family?: unknown;
    is_pinned?: boolean;
    project_id?: unknown;
    project_name?: unknown;
    working_dir?: unknown;
    [field: string]: unknown;
}

export interface Band<T = BucketRow> {
    key: string;
    rows: T[];
}

export interface ProjectBucket<T = BucketRow> extends Band<T> {
    label: string;
    isProject: boolean;
}

export const KEYS: readonly string[] = ['pinned', 'other'];

export const LABELS: Readonly<Record<string, string>> = { pinned: 'pinned', other: 'other' };

export const KIND_AGENT = 'agent';
export const KIND_TERMINAL = 'terminal';
export const KIND_BROWSER = 'browser';
export const KIND_LAYOUT = 'layout';

export const BAND_TERMINALS = 'terminals';
export const BAND_BROWSERS = 'browsers';
export const BAND_FILES = 'files';

export function kindOf(row: BucketRow | null | undefined): string {
    if (!row) return KIND_AGENT;
    if (row.kind === KIND_BROWSER) return KIND_BROWSER;
    if (row.kind === KIND_LAYOUT) return KIND_LAYOUT;
    if (row.agent_family === 'shell') return KIND_TERMINAL;
    return KIND_AGENT;
}

export function isAgentKind(row: BucketRow): boolean {
    return kindOf(row) === KIND_AGENT;
}

export function isTerminal(row: BucketRow): boolean {
    return kindOf(row) === KIND_TERMINAL;
}

export function isBrowser(row: BucketRow): boolean {
    return kindOf(row) === KIND_BROWSER && !row.file;
}

export function isFileRow(row: BucketRow): boolean {
    return kindOf(row) === KIND_BROWSER && !!row.file;
}

export function pageSectionOf(row: BucketRow): string | null {
    return isBrowser(row) && typeof row.section === 'string' && row.section ? row.section : null;
}

export function pageSectionRows<T extends BucketRow>(rows: T[], section: string): T[] {
    return rows.filter((row) => pageSectionOf(row) === section);
}

export function pageSectionIds(rows: readonly BucketRow[]): string[] {
    const out: string[] = [];
    for (const row of rows) {
        const id = pageSectionOf(row);
        if (id !== null && out.indexOf(id) === -1) out.push(id);
    }
    return out;
}

export function isBrowserBand(row: BucketRow): boolean {
    return isBrowser(row) && pageSectionOf(row) === null;
}

export function terminalRows<T extends BucketRow>(rows: readonly T[]): T[] {
    return (Array.isArray(rows) ? rows : []).filter(isTerminal);
}

export function isListedSession(row: BucketRow): boolean {
    const kind = kindOf(row);
    return (kind === KIND_AGENT || kind === KIND_TERMINAL) && row.archived !== true && typeof row.swarm_agent_id !== 'number';
}

export function filterAwakeSleeping<T extends BucketRow>(rows: readonly T[], open: boolean, sleeping: boolean): T[] {
    const list = Array.isArray(rows) ? rows : [];
    if (open && sleeping) return [...list];
    return list.filter((r) => !isListedSession(r) || r.closed === true || (r.asleep === true ? sleeping : open));
}

export function folderLabel(row: BucketRow): string | null {
    if (row && row.working_dir) return row.working_dir as string;
    if (row && row.project_name) return row.project_name as string;
    return null;
}

export function labelFor(key: string): string {
    const label = G.labelFor(key);
    if (label && label.trim()) return label;
    return LABELS[key] || key;
}

export function split<T extends BucketRow>(rows: readonly T[]): { pinned: T[]; other: T[] } {
    const list = Array.isArray(rows) ? rows : [];
    return { pinned: list.filter((r) => !!r.is_pinned), other: list.filter((r) => !r.is_pinned) };
}

export function bands<T extends BucketRow>(rows: readonly T[]): Array<Band<T>> {
    const usable = G.isUsable();
    const keys = ['pinned'].concat(usable ? G.bandOrder().filter((k) => k !== 'pinned' && k !== 'other') : []);
    const buckets = new Map<string, T[]>(keys.map((k) => [k, []]));
    for (const row of Array.isArray(rows) ? rows : []) {
        if (row.is_pinned) (buckets.get('pinned') as T[]).push(row);
        const uuid = usable ? G.groupOf(row.name) : null;
        const groupKey = uuid ? G.bandKeyFor(uuid) : null;
        if (groupKey && buckets.has(groupKey)) (buckets.get(groupKey) as T[]).push(row);
    }
    return keys.map((key) => ({ key, rows: buckets.get(key) as T[] }));
}

export function projectBuckets<T extends BucketRow>(rows: readonly T[]): Array<ProjectBucket<T>> {
    const rogueKey = G.BAND_ROGUE;
    const order: string[] = [];
    const buckets = new Map<string, { label: string; rows: T[]; isProject: boolean }>();
    for (const row of Array.isArray(rows) ? rows : []) {
        if (!isAgentKind(row)) continue;
        const pid = row.project_id;
        const known = pid !== null && pid !== undefined;
        const key = known ? G.projectBandKeyFor(pid) : rogueKey;
        if (!buckets.has(key)) {
            buckets.set(key, {
                label: known ? ((row.project_name as string) || 'unnamed project') : 'rogue agents',
                rows: [],
                isProject: known,
            });
            order.push(key);
        }
        (buckets.get(key) as { rows: T[] }).rows.push(row);
    }
    const withoutRogue = order.filter((k) => k !== rogueKey);
    const keys = buckets.has(rogueKey) ? withoutRogue.concat([rogueKey]) : withoutRogue;
    return keys.map((key) => ({ key, ...(buckets.get(key) as { label: string; rows: T[]; isProject: boolean }) }));
}

export interface CompanyBucket<T = BucketRow> {
    key: string;
    label: string;
    companyId: number | null;
    projects: Array<ProjectBucket<T>>;
}

export const COMPANY_ORPHANED_KEY = 'c:orphaned';

export function sortProjectsAlpha<T>(projects: ReadonlyArray<ProjectBucket<T>>): Array<ProjectBucket<T>> {
    return [...projects].sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base', numeric: true }));
}

export function companyBuckets<T extends BucketRow>(
    buckets: ReadonlyArray<ProjectBucket<T>>,
    companies: ReadonlyArray<{ id: number; name: string }>,
    companyOf: (projectId: string) => number | null,
): { companies: Array<CompanyBucket<T>>; rogue: ProjectBucket<T> | null } {
    const sorted = [...companies].sort(
        (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) || a.id - b.id,
    );
    const out = new Map<number, CompanyBucket<T>>(sorted.map((c) => [c.id, {
        key: `c:${c.id}`, label: c.name, companyId: c.id, projects: [],
    }]));
    const orphaned: CompanyBucket<T> = { key: COMPANY_ORPHANED_KEY, label: 'orphaned projects', companyId: null, projects: [] };
    let rogue: ProjectBucket<T> | null = null;
    for (const b of buckets) {
        if (!b.isProject) { rogue = b; continue; }
        const id = companyOf(b.key.slice(G.BAND_PROJECT_PREFIX.length));
        const home = id === null ? undefined : out.get(id);
        (home ?? orphaned).projects.push(b);
    }
    for (const c of out.values()) c.projects = sortProjectsAlpha(c.projects);
    orphaned.projects = sortProjectsAlpha(orphaned.projects);
    const list = [...out.values()];
    return { companies: orphaned.projects.length ? list.concat([orphaned]) : list, rogue };
}

export function narrow<T extends BucketRow>(_label: string, rows: T[], q: string): T[] {
    if (!q) return rows;
    return rows.filter((r) => matchesRow(r, q));
}

export function filteredBandSections<T extends BucketRow>(
    sections: ReadonlyArray<Band<T>>, labelOf: (key: string) => string, q: string,
): Array<Band<T>> {
    return sections.map((b) => ({ key: b.key, rows: narrow(b.key === 'pinned' ? 'pinned' : labelOf(b.key), b.rows, q) }));
}

export function filteredProjectBuckets<T extends BucketRow>(
    buckets: ReadonlyArray<ProjectBucket<T>>, q: string,
): Array<ProjectBucket<T>> {
    return buckets
        .map((b) => ({ key: b.key, label: b.label, rows: narrow(b.label, b.rows, q), isProject: b.isProject }))
        .filter((b) => b.rows.length > 0);
}

/*  hidden  */
export function keepBandSection(key: string, rows: readonly unknown[], dragging: boolean, _q: string): boolean {
    void key;
    return rows.length > 0 || dragging;
}
