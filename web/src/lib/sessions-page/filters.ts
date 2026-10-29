import type { HistoryGroup, HistoryProject, HistorySession } from '../projects-shared/history-api';
import type { SessionListItem } from '../sessions/types';

export const AGENT_FAMILIES: readonly string[] = ['claude', 'codex'];

export interface PageRow {
    readonly s: HistorySession;
    readonly groupKey: string;
    readonly projectRef: HistoryProject | null;
    readonly project: string;
    readonly company: string | null;
    readonly computer: string | null;
    readonly provider: string;
}

export type StateKey = 'working' | 'questions' | 'sleep' | 'closed' | 'archived';
export const STATE_KEYS: readonly StateKey[] = ['working', 'questions', 'sleep', 'closed', 'archived'];

export const DEFAULT_ON: readonly StateKey[] = ['working', 'sleep'];

export interface Filters {
    on: readonly StateKey[];
    company: string;
    project: string;
    computer: string;
    provider: string;
    q: string;
}

export const NO_FILTERS: Readonly<Filters> = { on: DEFAULT_ON, company: '', project: '', computer: '', provider: '', q: '' };

export interface Signals {
    live(s: HistorySession): SessionListItem | undefined;
    asleepUnread(sessionUuid: string): boolean;
}

export function isAgentRow(s: HistorySession): boolean {
    const family = (s.agent_family ?? '').toLowerCase();
    return AGENT_FAMILIES.includes(family) && (s.kind ?? '') !== 'shell';
}

export function rowsFromGroups(groups: readonly HistoryGroup[], peers: readonly HistoryGroup[], noProject: string): PageRow[] {
    const rows: PageRow[] = [];
    for (const g of [...groups, ...peers]) {
        for (const s of g.sessions) {
            if (!isAgentRow(s)) continue;
            rows.push({
                s,
                groupKey: g.key,
                projectRef: g.project,
                project: g.project?.name ?? noProject,
                company: g.project?.company_name ?? null,
                computer: s.host_label ?? g.host_label ?? null,
                provider: (s.agent_family ?? '').toLowerCase(),
            });
        }
    }
    return rows;
}

const NEEDS_STATUS = new Set(['question', 'notice', 'finished_unread']);
const WORKING_STATUS = new Set(['working', 'working_subagent']);

export function needsYou(s: HistorySession, sig: Signals): boolean {
    const w = sig.live(s);
    if (w) return NEEDS_STATUS.has(w.activity_status ?? '') || w.startup_gate === 'awaiting_startup_prompt';
    return s.state === 'asleep' && sig.asleepUnread(s.session_uuid);
}

export function isWorking(s: HistorySession, sig: Signals): boolean {
    return WORKING_STATUS.has(sig.live(s)?.activity_status ?? '');
}

export interface FleetCounts {
    running: number;
    needs: number;
    working: number;
    asleep: number;
    oldestDays: number;
}

export function fleetCounts(rows: readonly PageRow[], sig: Signals, now: number): FleetCounts {
    const c: FleetCounts = { running: 0, needs: 0, working: 0, asleep: 0, oldestDays: 0 };
    let oldest = 0;
    for (const { s } of rows) {
        if (s.state === 'running') c.running += 1;
        if (needsYou(s, sig)) c.needs += 1;
        if (isWorking(s, sig)) c.working += 1;
        if (s.state === 'asleep') {
            c.asleep += 1;
            const at = Date.parse(s.last_activity_at ?? '');
            if (Number.isFinite(at)) oldest = Math.max(oldest, now - at);
        }
    }
    c.oldestDays = Math.floor(oldest / 86_400_000);
    return c;
}

function haystack(r: PageRow): string {
    return [r.s.label ?? r.s.title, r.project, r.company ?? '', r.provider].join('\n').toLowerCase();
}

export function passes(r: PageRow, f: Filters, sig: Signals, labels: { noCompany: string; thisComputer: string }): boolean {
    return statesShow(r, f.on, sig) && passesFacets(r, f, labels);
}

export function passesFacets(r: PageRow, f: Filters, labels: { noCompany: string; thisComputer: string }): boolean {
    if (f.company && (r.company ?? labels.noCompany) !== f.company) return false;
    if (f.project && r.project !== f.project) return false;
    if (f.computer && (r.computer ?? labels.thisComputer) !== f.computer) return false;
    if (f.provider && r.provider !== f.provider) return false;
    return matchesFind(r, f.q);
}

export function statesShow(r: PageRow, on: readonly StateKey[], sig: Signals): boolean {
    return (on.includes('working') && r.s.state === 'running') || (on.includes('sleep') && r.s.state === 'asleep') || (on.includes('questions') && needsYou(r.s, sig));
}

export function toggleState(on: readonly StateKey[], k: StateKey): readonly StateKey[] {
    const next = on.includes(k) ? on.filter((x) => x !== k) : [...on, k];
    return STATE_KEYS.filter((x) => next.includes(x));
}

export function matchesFind(r: PageRow, q: string): boolean {
    const needle = q.trim().toLowerCase();
    return !needle || haystack(r).includes(needle);
}

export function distinct(values: readonly string[]): string[] {
    return [...new Set(values)].sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
}

export function filtersActive(f: Filters): boolean {
    return f.on.length !== DEFAULT_ON.length || DEFAULT_ON.some((k) => !f.on.includes(k)) || f.company !== '' || f.project !== '' || f.computer !== '' || f.provider !== '' || f.q !== '';
}
