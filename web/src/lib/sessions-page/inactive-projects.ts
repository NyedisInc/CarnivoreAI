import type { HistoryProject } from '../projects-shared/history-api';
import type { LensGroup } from './lenses';
import type { ProjectSortKey } from './toolbar-prefs';

export interface ProjectBands {
    readonly groups: readonly LensGroup[];
    readonly inactive: ReadonlySet<string>;
}

const byName = (a: LensGroup, b: LensGroup): number => a.label.toLowerCase().localeCompare(b.label.toLowerCase());

const byActive = (a: LensGroup, b: LensGroup): number => lastActive(b) - lastActive(a) || byName(a, b);

function lastActive(g: LensGroup): number {
    const times = g.rows.map((r) => Date.parse(r.s.last_activity_at ?? ''));
    const own = Date.parse(g.project?.last_opened_at ?? g.project?.created_at ?? '');
    return Math.max(0, ...times.filter(Number.isFinite), Number.isFinite(own) ? own : 0);
}

const matches = (p: HistoryProject, needle: string): boolean => !needle || p.name.toLowerCase().includes(needle) || (p.company_name ?? '').toLowerCase().includes(needle);

export function emptyGroup(project: HistoryProject): LensGroup {
    const key = `project:empty:${project.id ?? project.name}`;
    return { key, label: project.name, bits: project.company_name ? [project.company_name] : [], measure: '', rows: [], count: 0, live: 0, project, provider: null };
}

export function projectBands(groups: readonly LensGroup[], empties: readonly HistoryProject[], find: string, withEmpties: boolean, sort: ProjectSortKey = 'default'): ProjectBands {
    const needle = find.trim().toLowerCase();
    const shown = new Set(groups.map((g) => g.project?.id ?? g.label));
    const extra = withEmpties
        ? empties.filter((p) => !p.archived_at && !shown.has(p.id ?? p.name) && matches(p, needle)).map(emptyGroup)
        : [];
    const order = sort === 'recent' ? byActive : byName;
    const active = groups.filter((g) => g.live > 0);
    if (sort !== 'default') active.sort(order);
    const inactive = [...groups.filter((g) => g.live === 0), ...extra].sort(order);
    return { groups: [...active, ...inactive], inactive: new Set(inactive.map((g) => g.key)) };
}

export function archivedBand(archived: readonly HistoryProject[], find: string, withEmpties: boolean): LensGroup[] {
    const needle = find.trim().toLowerCase();
    if (!withEmpties) return [];
    return archived
        .filter((p) => matches(p, needle))
        .map((p) => ({ ...emptyGroup(p), key: `project:archived:${p.id ?? p.name}` }))
        .sort(byName);
}
