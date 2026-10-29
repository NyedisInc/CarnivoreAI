import type { SidebarRow } from './legacy';

export type LeaderRank = 'alpha' | 'company' | 'project';

export interface RosterLeader {
    id: number;
    rank: string;
    display_name: string;
    state?: string;
    session_row_id?: number | null;
    session_uuid?: string | null;
}

export interface LeaderInfo {
    rank: LeaderRank;
    agentId: number;
    name: string;
    companyId: number | null;
}

export const GHOST_PREFIX = 'swarm-agent:';

export interface LeaderIndex {
    of(row: SidebarRow): LeaderInfo | null;
    readonly empty: boolean;
    workerRank?(row: SidebarRow): WorkerRank | null;
    spawned?(row: SidebarRow): boolean;
}

export type WorkerRank = 'task' | 'feature';

export type RosterWithCompany = RosterLeader & { company_id?: number | null; project_id?: number | null; parent_id?: number | null };

export function indexLeaders(agents: readonly RosterWithCompany[]): LeaderIndex {
    const byRow = new Map<number, LeaderInfo>();
    const byUuid = new Map<string, LeaderInfo>();
    const byAgent = new Map<number, LeaderInfo>();
    const workerByRow = new Map<number, WorkerRank>();
    const workerByUuid = new Map<string, WorkerRank>();
    const byId = new Map<number, RosterWithCompany>(agents.map((a) => [a.id, a]));
    const spawnedRows = new Set<number>();
    const spawnedUuids = new Set<string>();
    for (const a of agents) {
        if (a.rank !== 'task' && a.rank !== 'feature') continue;
        const seen = new Set<number>([a.id]);
        for (let p = a.parent_id == null ? undefined : byId.get(a.parent_id); p && !seen.has(p.id); p = p.parent_id == null ? undefined : byId.get(p.parent_id)) {
            seen.add(p.id);
            if (p.rank !== 'project') continue;
            if (typeof a.session_row_id === 'number') spawnedRows.add(a.session_row_id);
            if (typeof a.session_uuid === 'string' && a.session_uuid) spawnedUuids.add(a.session_uuid);
            break;
        }
    }
    for (const a of agents) {
        if (a.rank === 'task' || a.rank === 'feature') {
            if (typeof a.session_row_id === 'number') workerByRow.set(a.session_row_id, a.rank);
            if (typeof a.session_uuid === 'string' && a.session_uuid) workerByUuid.set(a.session_uuid, a.rank);
            continue;
        }
        if (a.rank !== 'alpha' && a.rank !== 'company' && a.rank !== 'project') continue;
        const info: LeaderInfo = { rank: a.rank, agentId: a.id, name: a.display_name, companyId: a.company_id ?? null };
        byAgent.set(a.id, info);
        if (typeof a.session_row_id === 'number') byRow.set(a.session_row_id, info);
        if (typeof a.session_uuid === 'string' && a.session_uuid) byUuid.set(a.session_uuid, info);
    }
    return {
        empty: byAgent.size === 0,
        of(row: SidebarRow): LeaderInfo | null {
            const id = row.session_row_id;
            const uuid = row.session_uuid;
            if (typeof row.swarm_agent_id === 'number') return byAgent.get(row.swarm_agent_id) ?? null;
            return (typeof id === 'number' ? byRow.get(id) : undefined)
                ?? (typeof uuid === 'string' ? byUuid.get(uuid) : undefined) ?? null;
        },
        spawned(row: SidebarRow): boolean {
            return (typeof row.session_row_id === 'number' && spawnedRows.has(row.session_row_id))
                || (typeof row.session_uuid === 'string' && spawnedUuids.has(row.session_uuid));
        },
        workerRank(row: SidebarRow): WorkerRank | null {
            const id = row.session_row_id;
            const uuid = row.session_uuid;
            return (typeof id === 'number' ? workerByRow.get(id) : undefined)
                ?? (typeof uuid === 'string' ? workerByUuid.get(uuid) : undefined) ?? null;
        },
    };
}

export interface LeaderPlacement {
    alpha: SidebarRow | null;
    companies: Map<number, SidebarRow>;
    rest: SidebarRow[];
}

export function placeLeaders(rows: readonly SidebarRow[], idx: LeaderIndex): LeaderPlacement {
    const out: LeaderPlacement = { alpha: null, companies: new Map(), rest: [] };
    for (const row of rows) {
        const info = idx.empty ? null : idx.of(row);
        if (info?.rank === 'alpha' && !out.alpha) out.alpha = row;
        else if (info?.rank === 'company' && info.companyId !== null && !out.companies.has(info.companyId)) out.companies.set(info.companyId, row);
        else out.rest.push(row);
    }
    return out;
}

export function projectLeaderFirst(rows: readonly SidebarRow[], idx: LeaderIndex): SidebarRow[] {
    if (idx.empty) return [...rows];
    const lead = rows.filter((r) => idx.of(r)?.rank === 'project');
    return lead.length ? lead.concat(rows.filter((r) => idx.of(r)?.rank !== 'project')) : [...rows];
}

const INSIGNIA: Record<LeaderRank, string> = {
    project: '<path d="M3 8.5 7 4.5 11 8.5" />',
    company: '<path d="M3 6.5 7 2.5 11 6.5" /><path d="M3 11.5 7 7.5 11 11.5" />',
    alpha: '<path d="M7 1.5 8.6 5.2 12.6 5.5 9.5 8.1 10.5 12 7 9.9 3.5 12 4.5 8.1 1.4 5.5 5.4 5.2Z" />',
};

export function insigniaSvg(rank: LeaderRank): string {
    return `<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="square" stroke-linejoin="miter" aria-hidden="true">${INSIGNIA[rank]}</svg>`;
}

export function ghostLeaderRows(
    agents: readonly RosterWithCompany[], rows: readonly SidebarRow[], idx: LeaderIndex, projectName: (id: number) => string | null,
): SidebarRow[] {
    const placed = new Set<number>();
    for (const row of rows) {
        const info = idx.of(row);
        if (info) placed.add(info.agentId);
    }
    const out: SidebarRow[] = [];
    for (const a of agents) {
        if ((a.rank !== 'alpha' && a.rank !== 'company' && a.rank !== 'project') || placed.has(a.id)) continue;
        const pid = typeof a.project_id === 'number' ? a.project_id : null;
        out.push({
            name: `${GHOST_PREFIX}${a.id}`, label: a.display_name, asleep: true, status: 'asleep', is_active: false, unread: false,
            session_uuid: a.session_uuid ?? null, agent_family: 'claude', is_pinned: false, band_key: 'other',
            project_id: pid, project_name: pid === null ? null : projectName(pid), swarm_agent_id: a.id,
        });
    }
    return out;
}
