import {
    BAND_BROWSERS, BAND_FILES, BAND_TERMINALS, COMPANY_ORPHANED_KEY, KIND_LAYOUT, companyBuckets, isAgentKind, isBrowserBand,
    isFileRow, kindOf, projectBuckets, terminalRows, type BucketRow,
} from './bucketing';
import { matches, type GroupRule, type RuleContext } from './group-rule';
import * as GroupStore from './group-store';
import { bridge as drawerLayoutsBridge } from './layouts-model';
import { layoutsBridge } from '../layouts-bridge/bridge';

export interface ScopeCompanySource {
    readonly companies: readonly { id: number; name: string }[];
    companyOf(projectId: string): number | null;
    parentOf?(companyId: number): number | null;
    projectParentOf?(projectId: string): string | null;
}

export function resolveNestedGroupRows<T extends BucketRow>(
    group: GroupStore.SessionGroup,
    scopeRows: readonly T[],
    allRows: readonly T[],
    ctx: RuleContext = GroupStore.getRuleContext(),
): T[] {
    const out: T[] = [];
    const seen = new Set<string>();
    const add = (row: T): void => {
        if (!row || !row.name || seen.has(row.name)) return;
        seen.add(row.name);
        out.push(row);
    };
    for (const row of GroupStore.handPickedRowsFor(group, allRows as Array<T & { session_uuid?: string | null }>)) add(row);
    if (group.rule) {
        for (const row of scopeRows) {
            if (matches(group.rule, row, ctx)) add(row);
        }
    }
    return out;
}

function companySubtreeIds(rootId: number, source: ScopeCompanySource): Set<number> {
    const set = new Set<number>([rootId]);
    if (!source.parentOf) return set;
    let grew = true;
    while (grew) {
        grew = false;
        for (const c of source.companies) {
            const parent = source.parentOf(c.id);
            if (!set.has(c.id) && parent !== null && set.has(parent)) {
                set.add(c.id);
                grew = true;
            }
        }
    }
    return set;
}

function projectSubtreeKeys(
    rootProjectId: string,
    buckets: readonly { key: string; isProject: boolean }[],
    source?: ScopeCompanySource,
): Set<string> {
    const ids = new Set<string>([rootProjectId]);
    if (source?.projectParentOf) {
        let grew = true;
        while (grew) {
            grew = false;
            for (const b of buckets) {
                if (!b.isProject) continue;
                const pid = b.key.slice(GroupStore.BAND_PROJECT_PREFIX.length);
                if (ids.has(pid)) continue;
                const parent = source.projectParentOf(pid);
                if (parent !== null && ids.has(parent)) {
                    ids.add(pid);
                    grew = true;
                }
            }
        }
    }
    const keys = new Set<string>();
    for (const id of ids) keys.add(GroupStore.BAND_PROJECT_PREFIX + id);
    return keys;
}

export function scopeRowsForContainer<T extends BucketRow>(
    parentKey: string | null | undefined,
    allRows: readonly T[],
    source?: ScopeCompanySource,
    ctx: RuleContext = GroupStore.getRuleContext(),
    visited: Set<string> = new Set(),
): T[] {
    if (!parentKey) return [...allRows];
    if (parentKey === GroupStore.BAND_PINNED) {
        return allRows.filter((r) => !!r.is_pinned || ctx.isPinned(r.name));
    }
    if (parentKey === 'layouts') {
        return allRows.filter((r) => kindOf(r) === KIND_LAYOUT);
    }
    if (parentKey.startsWith('layout:')) {
        const layoutRow = allRows.find((r) => r.name === parentKey) as (T & { _members?: T[] }) | undefined;
        if (layoutRow && Array.isArray(layoutRow._members)) return layoutRow._members;
        const uuid = parentKey.slice('layout:'.length);
        const layout = drawerLayoutsBridge()?.get(uuid) ?? layoutsBridge.get(uuid);
        if (!layout) return [];
        const memberUuids = new Set((layout.members ?? []).map((m) => m.session_uuid).filter((u): u is string => typeof u === 'string'));
        return allRows.filter((r) => typeof r.session_uuid === 'string' && memberUuids.has(r.session_uuid));
    }
    if (parentKey === GroupStore.BAND_ROGUE) {
        return allRows.filter((r) => isAgentKind(r) && (r.project_id === null || r.project_id === undefined));
    }
    if (parentKey === BAND_TERMINALS) return terminalRows(allRows);
    if (parentKey === BAND_BROWSERS) return allRows.filter(isBrowserBand);
    if (parentKey === BAND_FILES) return allRows.filter(isFileRow);

    if (parentKey === COMPANY_ORPHANED_KEY || /^c:\d+$/.test(parentKey)) {
        const buckets = projectBuckets(allRows);
        if (!source) return [];
        const filed = companyBuckets(buckets, source.companies, source.companyOf);
        if (parentKey === COMPANY_ORPHANED_KEY) {
            const orphaned = filed.companies.find((c) => c.companyId === null);
            return orphaned ? orphaned.projects.flatMap((p) => p.rows) : [];
        }
        const ids = companySubtreeIds(Number(parentKey.slice(2)), source);
        const out: T[] = [];
        for (const c of filed.companies) {
            if (c.companyId !== null && ids.has(c.companyId)) {
                for (const p of c.projects) out.push(...p.rows);
            }
        }
        return out;
    }

    if (/^p:\d+$/.test(parentKey)) {
        const buckets = projectBuckets(allRows);
        const keys = projectSubtreeKeys(parentKey.slice(2), buckets, source);
        const out: T[] = [];
        for (const b of buckets) if (keys.has(b.key)) out.push(...b.rows);
        return out;
    }

    const groupUuid = GroupStore.groupUuidOf(parentKey);
    if (groupUuid) {
        if (visited.has(groupUuid)) return [];
        visited.add(groupUuid);
        const parent = GroupStore.groupByUuid(groupUuid);
        if (!parent) return [];
        if (!parent.parent_key) {
            return allRows.filter((r) => GroupStore.groupOf(r.name) === parent.group_uuid);
        }
        const upper = scopeRowsForContainer(parent.parent_key, allRows, source, ctx, visited);
        return resolveNestedGroupRows(parent, upper, allRows, ctx);
    }

    return [];
}

export function rowsForGroup<T extends BucketRow>(
    groupUuid: string,
    allRows: readonly T[],
    source?: ScopeCompanySource,
): T[] {
    const group = GroupStore.groupByUuid(groupUuid);
    if (!group) return [];
    if (!group.parent_key) return allRows.filter((r) => GroupStore.groupOf(r.name) === groupUuid);
    const scope = scopeRowsForContainer(group.parent_key, allRows, source);
    return resolveNestedGroupRows(group, scope, allRows);
}

export function countMatchingInContainer(
    rule: GroupRule,
    groupUuid: string,
    source?: ScopeCompanySource,
): number {
    const group = GroupStore.groupByUuid(groupUuid);
    if (!group?.parent_key) return GroupStore.countMatching(rule);
    const all = GroupStore.listedRows() as BucketRow[];
    const scope = scopeRowsForContainer(group.parent_key, all, source);
    return GroupStore.countMatching(rule, scope);
}
