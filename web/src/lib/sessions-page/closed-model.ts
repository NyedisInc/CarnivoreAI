import type { HistoryGroup } from '../projects-shared/history-api';
import { CLOSED_PREVIEW, CLOSED_SLACK } from '../projects-shared/ledger-model';
import { passesFacets, rowsFromGroups, type Filters, type PageRow } from './filters';
import type { LensGroup } from './lenses';

const CLOSED_STATES: ReadonlySet<string> = new Set(['closed', 'removed', 'unknown']);

export function closedRowsFrom(groups: readonly HistoryGroup[], peers: readonly HistoryGroup[], noProject: string): PageRow[] {
    return rowsFromGroups(groups, peers, noProject).filter((r) => CLOSED_STATES.has(r.s.state));
}

export function historyKeyOf(g: LensGroup): string {
    return g.rows[0]?.groupKey ?? (g.project?.id != null ? String(g.project.id) : '');
}

export function closedShown(r: PageRow, f: Filters, labels: { noCompany: string; thisComputer: string }, showHidden = false): boolean {
    const kind = r.s.state === 'removed' ? f.on.includes('archived') || (showHidden && f.on.includes('closed')) : f.on.includes('closed');
    return kind && (r.computer === null || f.computer !== '') && passesFacets(r, f, labels);
}

const newest = (a: PageRow, b: PageRow): number => Date.parse(b.s.last_activity_at ?? '') - Date.parse(a.s.last_activity_at ?? '');

export function closedByKey(rows: readonly PageRow[]): Map<string, PageRow[]> {
    const out = new Map<string, PageRow[]>();
    for (const r of rows) out.set(r.groupKey, [...(out.get(r.groupKey) ?? []), r]);
    for (const list of out.values()) list.sort(newest);
    return out;
}

export function closedOnlyGroups(byKey: ReadonlyMap<string, readonly PageRow[]>, drawn: ReadonlySet<string>): LensGroup[] {
    const out: LensGroup[] = [];
    for (const [key, rows] of byKey) {
        const first = rows[0] as PageRow;
        if (drawn.has(key)) continue;
        out.push({ key: `closed:${key}`, label: first.project, bits: first.computer ? [first.computer] : first.company ? [first.company] : [], measure: '', rows: [], count: 0, live: 0, project: null, provider: null });
    }
    return out.sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase()));
}

export function previewCount(total: number, open: boolean): number {
    return open || total <= CLOSED_PREVIEW + CLOSED_SLACK ? total : CLOSED_PREVIEW;
}
