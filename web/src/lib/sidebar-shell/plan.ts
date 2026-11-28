import {
    BAND_BROWSERS, BAND_FILES, BAND_TERMINALS, KIND_LAYOUT, bands, companyBuckets, filteredBandSections, filteredProjectBuckets,
    folderLabel, isBrowserBand, isFileRow, kindOf, pageSectionIds, pageSectionRows, keepBandSection, labelFor, narrow, projectBuckets, terminalRows,
    type CompanyBucket,
} from '../drawer/bucketing';
import { orderBand } from '../drawer/arrangement';
import { nestByParent, pruneTree, type TreeNode } from '../drawer/lineage-tree';
import {
    BAND_PROJECT_PREFIX, bandKeyFor, childrenOf as groupChildrenOf, groupUuidOf, isUsable as groupsUsable,
} from '../drawer/group-store';
import { resolveNestedGroupRows } from '../drawer/nested-groups';
import { attentionHtml, esc } from '../drawer/listing-state';
import { FILTER_ONLY_QUERY, matchesLabel, noMatchesHtml } from '../drawer/search';
import { SEARCH_AGENTS_BAND, searchParts, type SearchAgentsPlan, type SearchConversationsPlan } from './search-plan';
import { activeCountFilter } from '../drawer/count-filter.svelte';
import { linkMarkFor, type LinkState } from '../pack-machines/pack-meter-math';
import { t } from '../i18n/index.svelte';
import { companySource, watchCompanies, type CompanySource } from './company-source.svelte';
import { packSource, watchPack } from './pack-source.svelte';
import { filterRowsByHost, offMachineIds } from './pack-filter';
import { hostLightHtml } from './pack-light';
import type { PackMachine } from '../pack-machines/pack-machines-store.svelte';
import type {
    ArrangementState, LegacyDrawer, ListingVerdict, ProjectBucket, SidebarRow,
} from './legacy';
import { parseAttrs } from './attr-string';
import { NEW_GROUP_KEY } from './new-group-target';
import { rollupHtml } from './subagent-rollup';
import { rowHost, type RowHost } from './row-host';
import { buildRowPlan, type GlyphChip, type RowPlan, type TextChip } from './row-plan';
import { inactiveProjectIcon, movedAwayChip } from './row-chips';
import { GHOST_PREFIX, ghostLeaderRows, placeLeaders, projectLeaderFirst, type LeaderIndex } from './leaders';
import { GROUPS_FOLD_KEY, SPAWNED_FOLD_SUFFIX } from '../drawer/store-keys';
import { foldPresent } from '../drawer/fold-view';
import { PAGE_SECTION_SLOT, pageSectionMeta } from '../drawer/page-sections';
import { previewOrder, resolveSectionOrder, type SectionId } from '../drawer/section-order';
import { leadersShown } from '../drawer/leader-visibility';
import { swarmIsOn } from '../swarm-switch/control.svelte';
import { emptySectionsHidden } from '../drawer/empty-sections.svelte';
import { companyTint, projectTint } from './tint';
import { archivedLast } from '../drawer/archived-rows';
import { sleepingFolded } from '../drawer/sleep-fold.svelte';
import { averagePackStats } from './pack-stats';
import { leaderIndex, leaderRoster, projectNameOf, watchLeaders } from './leaders-source.svelte';
import { memberOf } from '../swarm-membership/member-face';

export interface PaintInput {
    rows: SidebarRow[];
    density: string;
    listing: ListingVerdict | null;
    missing: string[];
    arrangement: ArrangementState | null;
    opts: { collapsed?: string[]; dragging?: boolean; query?: string; searchList?: boolean } | null;
}

export interface HeadingMenuPlan {
    kind: 'group' | 'project' | 'company';
    id: string;
    label: string;
}

export interface HeadingPlan {
    toggle: 'group';
    key: string;
    bandKind: 'reserved' | 'group' | 'project' | 'company';
    expanded: boolean;
    bodyId: string;
    title: string;
    label: string;
    inactive?: GlyphChip;
    badge?: TextChip;
    tint?: string;
    iconHtml: string;
    ledHtml: string;
    pickedIconHtml: string;
    rollupHtml: string;
    menu?: HeadingMenuPlan;
    packMark?: { kind: 'on' | 'leftover'; label: string; projectId: string };
    fxHtml?: string;
    countSummary?: { live: number; total: number } | null;
    projectCount?: number;
    featuresCount?: number;
    packHeaderStats?: { open: boolean; cpu: number | null; ram: number | null; disk: number | null };
}

export interface SectionPlan {
    type: 'section';
    key: string;
    colourAttrs: Record<string, string>;
    blockColor?: string;
    collapsed: boolean;
    count: number;
    bodyId: string;
    heading: HeadingPlan;
    rows: RowPlan[];
    sleepingRows?: RowPlan[];
    allAsleep?: boolean;
    spawned: SpawnedPlan | null;
    children?: SectionPlan[];
    groups?: SectionPlan[];
    nested?: boolean;
    empty?: string;
}

export interface SpawnedPlan {
    key: string;
    collapsed: boolean;
    count: number;
    heading: HeadingPlan;
    rows: RowPlan[];
}

export interface CompanyPlan {
    type: 'company';
    key: string;
    open: boolean;
    tint?: string;
    heading: HeadingPlan;
    sections: SectionPlan[];
    empty: boolean;
    leader: RowPlan | null;
    groups?: SectionPlan[];
    children?: CompanyPlan[];
}

export interface LeaderPlan {
    type: 'leader';
    key: string;
    row: RowPlan;
}

export interface CompaniesPlan {
    type: 'companies';
    key: string;
    open: boolean;
    heading: HeadingPlan;
}

export interface PackRowPlan {
    id: string;
    label: string;
    alpha: boolean;
    self: boolean;
    link: LinkState | null;
    machine: PackMachine;
    off: boolean;
    lightHtml: string;
}

export interface PackPlan {
    type: 'pack';
    key: string;
    open: boolean;
    density: string;
    heading: HeadingPlan;
    rows: PackRowPlan[];
    count: number;
}

export interface GroupsPlan {
    type: 'groups';
    key: string;
    open: boolean;
    heading: HeadingPlan;
    sections: SectionPlan[];
}

export interface NewGroupPlan {
    type: 'newgroup';
    key: string;
}

export type BandPart = SectionPlan | CompanyPlan | LeaderPlan | CompaniesPlan | PackPlan | GroupsPlan | NewGroupPlan | SearchAgentsPlan | SearchConversationsPlan;

export interface ListPlan {
    leadHtml: string;
    parts: BandPart[];
    tailHtml: string;
}

const COMPANIES_KEY = 'companies';
const GROUPS_KEY = GROUPS_FOLD_KEY;
const PACK_KEY = 'pack';
const LAYOUTS_KEY = 'layouts';
const TERMINALS_LABEL = 'terminals';
const EMPTY_HTML = '<div class="session-sidebar-empty">no other agents</div>';

/* could not be read */
export function arrangementNoticeHtml(arrangement: Pick<ArrangementState, 'status' | 'reason'> | null): string {
    if (!arrangement || arrangement.status !== 'unreadable') return '';
    const reason = esc(arrangement.reason || 'reason unknown');
    return (
        '<div class="session-sidebar-notice" role="status" data-arrangement-state="unreadable">'
        + '<div class="session-sidebar-notice__title">CANNOT LOAD your saved order</div>'
        + `<div class="session-sidebar-notice__detail">${reason}. showing the default order `
        + 'until you pin or move something.</div>'
        + '</div>'
    );
}

function agentsPhrase(count: number): string {
    return `(${count} ${count === 1 ? 'agent' : 'agents'})`;
}

export { parseAttrs };

interface Ctx {
    L: LegacyDrawer;
    density: string;
    isFolded: (key: string) => boolean;
    host: RowHost;
    leaders: LeaderIndex;
    query: string;
    hideEmptyKinds: boolean;
}

function isGhostRow(r: SidebarRow): boolean {
    return typeof r.swarm_agent_id === 'number' && typeof r.name === 'string' && r.name.startsWith(GHOST_PREFIX);
}

function rowPlan(ctx: Ctx, r: SidebarRow, band: string, subtitle?: string | null): RowPlan {
    const plan = buildRowPlan(r, ctx.density, band, subtitle, ctx.host);
    const info = ctx.leaders.empty || plan.type !== 'session' ? null : ctx.leaders.of(r);
    if (info && plan.type === 'session') {
        plan.leader = { rank: info.rank, label: t(`leader.mark.${info.rank}`) };
        plan.attrs['data-leader'] = info.rank;
        if (isGhostRow(r)) {
            plan.ghost = { agentId: r.swarm_agent_id as number, name: info.name, rank: info.rank };
            plan.attrs['data-ghost'] = '1';
            plan.pin = null;
            plan.keepAwake = null;
            plan.menu = null;
            plan.actions = [];
        }
    }
    if (plan.type === 'session' && plan.led) plan.member = memberOf(r as unknown as Record<string, unknown>, leaderRoster());
    const worker = plan.type === 'session' && plan.body && ctx.leaders.workerRank ? ctx.leaders.workerRank(r) : null;
    if (worker && plan.type === 'session' && plan.body) plan.body.rankTag = t(`cplug.huddle.swarm.rank.${worker}`);
    return plan;
}

interface SectionOpts {
    labelOverride?: string;
    subtitleFor?: (row: SidebarRow) => string | null;
    isProject?: boolean;
    noLight?: boolean;
    inactive?: boolean;
    movedTo?: string;
    delegate?: 'on' | 'leftover';
    excludeNames?: ReadonlySet<string>;
}

function sectionPlan(ctx: Ctx, key: string, rows: SidebarRow[], o: SectionOpts): SectionPlan {
    const { L } = ctx;
    const PH = L.projectHeader!;
    const collapsed = ctx.isFolded(key);
    const label = (typeof o.labelOverride === 'string' && o.labelOverride)
        ? o.labelOverride
        : labelFor(key);
    const bodyId = `session-sidebar-group-body-${key}`;
    const verb = collapsed ? 'Expand' : 'Collapse';
    const title = `${verb} the ${label} group ${agentsPhrase(rows.length)}`;
    const uuid = groupUuidOf(key);
    const showLight = o.isProject ? undefined : !o.noLight;
    const menu: HeadingMenuPlan | undefined = o.isProject
        ? { kind: 'project', id: key, label: t('sidebar.project.menu.title', { name: label }) }
        : uuid ? { kind: 'group', id: uuid, label: t('sidebar.group.menu.title', { name: label }) } : undefined;
    const bandKind = o.isProject ? 'project' : (uuid ? 'group' : 'reserved');
    const pickedIconHtml = PH.pickedIconHtml ? PH.pickedIconHtml({ key, bandKind }) : '';
    const iconName = PH.iconForBand(key, o.isProject) ?? (bandKind === 'group' && !pickedIconHtml ? 'agent-group' : null);
    const heading: HeadingPlan = {
        toggle: 'group',
        key,
        bandKind,
        expanded: !collapsed,
        bodyId,
        title,
        label,
        iconHtml: PH.iconHtml(iconName),
        ledHtml: PH.ledHtml(rows, collapsed, showLight),
        pickedIconHtml,
        rollupHtml: o.isProject ? '' : rollupHtml(rows),
        ...(menu ? { menu } : {}),
        ...(o.movedTo !== undefined ? { badge: movedAwayChip(o.movedTo) } : o.inactive ? { inactive: inactiveProjectIcon() } : {}),
    };
    if (o.isProject && o.delegate) {
        heading.packMark = { kind: o.delegate, projectId: key.slice(BAND_PROJECT_PREFIX.length), label: t(`sidebar.project.delegate.${o.delegate}`) };
    }
    const fxHtml = L.groupColour?.groupFxHtml ? L.groupColour.groupFxHtml(key, label) : '';
    if (fxHtml) heading.fxHtml = fxHtml;
    const visible = o.excludeNames && o.excludeNames.size ? rows.filter((r) => !o.excludeNames!.has(r.name)) : rows;
    const kids = o.isProject && ctx.leaders.spawned ? visible.filter((r) => ctx.leaders.spawned!(r)) : [];
    const direct = kids.length ? visible.filter((r) => !ctx.leaders.spawned!(r)) : visible;
    const isAsleep = (r: SidebarRow): boolean => Boolean(r.asleep || r.status === 'asleep');
    const liveCount = visible.filter((r) => !isAsleep(r) && !r.closed && !r.archived).length;
    if (o.isProject) {
        heading.projectCount = visible.length;
        if (kids.length) heading.featuresCount = kids.length;
    } else if (key === 'pinned' || bandKind === 'group' || key === 'rogue') {
        heading.countSummary = { live: liveCount, total: visible.length };
    }
    const ordered = archivedLast(orderBand(key, direct));
    const drawn = o.isProject ? projectLeaderFirst(ordered, ctx.leaders) : ordered;
    const canFoldSleep = !collapsed && sleepingFolded() && !ctx.query && !activeCountFilter()
        && key !== BAND_TERMINALS && key !== BAND_BROWSERS && key !== BAND_FILES && key !== LAYOUTS_KEY;
    const liveDrawn = canFoldSleep ? drawn.filter((r) => !isAsleep(r)) : drawn;
    const sleepDrawn = canFoldSleep ? drawn.filter((r) => isAsleep(r)) : [];
    const allAsleep = Boolean(o.isProject && visible.length > 0 && visible.every(isAsleep));
    const toPlan = (r: SidebarRow) => rowPlan(ctx, r, key, o.subtitleFor ? o.subtitleFor(r) : undefined);
    return {
        type: 'section',
        key,
        colourAttrs: parseAttrs(L.groupColour ? L.groupColour.attrsFor(key) : ''),
        ...(o.isProject && projectTint(key) ? { blockColor: projectTint(key) } : {}),
        ...(allAsleep ? { allAsleep: true } : {}),
        collapsed,
        count: rows.length,
        bodyId,
        heading,
        rows: collapsed ? [] : uniqueKeys(liveDrawn.map(toPlan)),
        ...(sleepDrawn.length ? { sleepingRows: uniqueKeys(sleepDrawn.map(toPlan)) } : {}),
        spawned: kids.length && !collapsed ? spawnedPlan(ctx, key, kids) : null,
    };
}

function spawnedPlan(ctx: Ctx, projectKey: string, kids: SidebarRow[]): SpawnedPlan {
    const key = projectKey + SPAWNED_FOLD_SUFFIX;
    const collapsed = !ctx.isFolded(key);
    const label = t('sidebar.spawned.heading', { count: kids.length });
    return {
        key,
        collapsed,
        count: kids.length,
        heading: {
            toggle: 'group',
            key,
            bandKind: 'reserved',
            expanded: !collapsed,
            bodyId: `session-sidebar-group-body-${key}`,
            title: t(collapsed ? 'sidebar.spawned.expand' : 'sidebar.spawned.collapse', { count: kids.length }),
            label,
            iconHtml: '',
            ledHtml: ctx.L.projectHeader!.ledHtml(kids, collapsed),
            pickedIconHtml: '',
            rollupHtml: '',
        },
        rows: collapsed ? [] : uniqueKeys(kids.map((r) => rowPlan(ctx, r, projectKey))),
    };
}

function uniqueKeys(rows: RowPlan[]): RowPlan[] {
    const seen = new Map<string, number>();
    for (const r of rows) {
        const n = seen.get(r.key) || 0;
        seen.set(r.key, n + 1);
        if (n) r.key = `${r.key}#${n}`;
    }
    return rows;
}

interface NestCtx {
    allRows: SidebarRow[];
    query: string;
    dragging: boolean;
    rawProjectRows: ReadonlyMap<string, SidebarRow[]>;
}

interface NestedGroupsResult {
    sections: SectionPlan[];
    claimed: Set<string>;
}

function mergeExclude(a?: ReadonlySet<string>, b?: ReadonlySet<string>): ReadonlySet<string> | undefined {
    if (!a?.size) return b?.size ? b : undefined;
    if (!b?.size) return a;
    const out = new Set<string>(a);
    for (const v of b) out.add(v);
    return out;
}

function nestedGroupsFor(
    ctx: Ctx, parentKey: string, scopeRows: SidebarRow[], nest: NestCtx, nested: boolean,
): NestedGroupsResult {
    const claimed = new Set<string>();
    if (!groupsUsable()) return { sections: [], claimed };
    const kids = groupChildrenOf(parentKey);
    if (!kids.length) return { sections: [], claimed };
    const hideEmpty = emptySectionsHidden();
    const sections: SectionPlan[] = [];
    for (const g of kids) {
        const key = bandKeyFor(g.group_uuid);
        const raw = resolveNestedGroupRows(g, scopeRows, nest.allRows);
        const sub = nestedGroupsFor(ctx, key, raw, nest, true);
        const narrowed = nest.query ? narrow(g.name, raw, nest.query) : raw;
        if (!keepBandSection(key, narrowed, nest.dragging, nest.query, hideEmpty) && !sub.sections.length) continue;
        for (const r of narrowed) claimed.add(r.name);
        for (const name of sub.claimed) claimed.add(name);
        const plan = sectionPlan(ctx, key, narrowed, { excludeNames: sub.claimed });
        if (nested) plan.nested = true;
        if (!plan.collapsed && sub.sections.length) plan.groups = sub.sections;
        sections.push(plan);
    }
    return { sections, claimed };
}

function companyPlan(
    ctx: Ctx, c: CompanyBucket<SidebarRow>, leaderRow: SidebarRow | undefined,
    source?: Pick<CompanySource, 'projectParentOf' | 'projectArchived' | 'projectMovedTo' | 'projectDelegate'>,
    nest?: NestCtx, excludeNames?: ReadonlySet<string>,
): CompanyPlan {
    const PH = ctx.L.projectHeader!;
    const open = !ctx.isFolded(c.key);
    const allRows = c.projects.reduce<SidebarRow[]>((acc, b) => acc.concat(b.rows), []);
    const orphaned = c.companyId === null;
    const label = orphaned ? t('sidebar.company.orphaned') : c.label;
    const visibleLeader = leaderRow && !(excludeNames && excludeNames.has(leaderRow.name)) ? leaderRow : undefined;
    const countRows = visibleLeader ? [visibleLeader, ...allRows] : allRows;
    const liveCount = countRows.filter((r) => !r.asleep && r.status !== 'asleep' && !r.closed && !r.archived).length;
    const tint = companyTint(c.companyId) || undefined;
    return {
        type: 'company',
        key: c.key,
        open,
        ...(tint ? { tint } : {}),
        empty: open && !c.projects.length && !visibleLeader,
        leader: open && visibleLeader ? rowPlan(ctx, visibleLeader, 'leader') : null,
        heading: {
            toggle: 'group',
            key: c.key,
            bandKind: orphaned ? 'reserved' : 'company',
            expanded: open,
            bodyId: `session-sidebar-group-body-${c.key}`,
            title: `${open ? 'Collapse' : 'Expand'} the ${label} company ${agentsPhrase(allRows.length)}`,
            label,
            iconHtml: PH.iconHtml(orphaned ? 'folder-tree' : 'building'),
            ledHtml: PH.ledHtml(allRows, !open),
            pickedIconHtml: '',
            rollupHtml: '',
            countSummary: { live: liveCount, total: countRows.length },
            ...(orphaned ? {} : { menu: { kind: 'company', id: c.key, label: t('sidebar.company.menu.title', { name: label }) } as HeadingMenuPlan }),
            ...(tint ? { tint } : {}),
        },
        sections: open ? projectSections(ctx, c.projects, source?.projectParentOf, source?.projectArchived, source?.projectMovedTo, source?.projectDelegate, nest, excludeNames) : [],
    };
}

export function withInactiveProjects(
    buckets: ProjectBucket[], known: readonly { id: string; name: string }[],
): ProjectBucket[] {
    if (!known.length) return buckets;
    const have = new Set(buckets.map((b) => b.key));
    const empty = known
        .filter((p) => !have.has(BAND_PROJECT_PREFIX + p.id))
        .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) || a.id.localeCompare(b.id))
        .map((p): ProjectBucket => ({ key: BAND_PROJECT_PREFIX + p.id, label: p.name || t('sidebar.project.unnamed'), rows: [], isProject: true }));
    return empty.length ? [...buckets, ...empty] : buckets;
}

function projectSections(
    ctx: Ctx, buckets: ReadonlyArray<ProjectBucket>, parentOf?: CompanySource['projectParentOf'],
    isArchived?: CompanySource['projectArchived'], movedTo?: CompanySource['projectMovedTo'], delegate?: CompanySource['projectDelegate'],
    nest?: NestCtx, parentExclude?: ReadonlySet<string>,
): SectionPlan[] {
    const moved = (b: ProjectBucket): string | null => (b.isProject && movedTo ? movedTo(b.key.slice(BAND_PROJECT_PREFIX.length)) : null);
    const archived = (b: ProjectBucket): boolean => !!(b.isProject && isArchived && isArchived(b.key.slice(BAND_PROJECT_PREFIX.length)));
    const inactive = (b: ProjectBucket): boolean => b.isProject && (archived(b) || b.rows.length === 0);
    const buildProject = (b: ProjectBucket, scopeRows: SidebarRow[], inheritedExclude?: ReadonlySet<string>): { section: SectionPlan; exclude?: ReadonlySet<string> } => {
        const own = nest ? nestedGroupsFor(ctx, b.key, scopeRows, nest, true) : { sections: [], claimed: new Set<string>() };
        const exclude = mergeExclude(inheritedExclude, own.claimed);
        const s = sectionPlan(ctx, b.key, b.rows, {
            labelOverride: b.label, isProject: b.isProject, ...(inactive(b) ? { inactive: true } : {}),
            ...(moved(b) !== null ? { movedTo: moved(b) as string } : {}),
            ...(b.isProject && delegate && delegate(b.key.slice(BAND_PROJECT_PREFIX.length)) ? { delegate: delegate(b.key.slice(BAND_PROJECT_PREFIX.length))! } : {}),
            excludeNames: exclude,
        });
        if (!s.collapsed && own.sections.length) s.groups = own.sections;
        return { section: s, exclude };
    };
    if (!parentOf) {
        return buckets.map((b) => buildProject(b, nest?.rawProjectRows.get(b.key) ?? b.rows, parentExclude).section);
    }
    const parentKey = (b: ProjectBucket): string | null => {
        const parent = b.isProject ? parentOf(b.key.slice(BAND_PROJECT_PREFIX.length)) : null;
        return parent === null ? null : BAND_PROJECT_PREFIX + parent;
    };
    const subtreeRows = (n: TreeNode<ProjectBucket>): SidebarRow[] => {
        const own = nest?.rawProjectRows.get(n.item.key) ?? n.item.rows;
        return n.children.length ? own.concat(...n.children.map(subtreeRows)) : own;
    };
    const toSection = (n: TreeNode<ProjectBucket>, nested: boolean, inheritedExclude?: ReadonlySet<string>): SectionPlan => {
        const { section: s, exclude } = buildProject(n.item, subtreeRows(n), inheritedExclude);
        if (nested) s.nested = true;
        if (n.children.length && !s.collapsed) s.children = n.children.map((k) => toSection(k, true, exclude));
        return s;
    };
    return nestByParent(buckets, (b) => b.key, parentKey).map((n) => toSection(n, false, parentExclude));
}

function companyNode(
    ctx: Ctx, n: TreeNode<CompanyBucket<SidebarRow>>, leaderRows: Map<number, SidebarRow>, source: CompanySource,
    nest: NestCtx, scopeByCompany: ReadonlyMap<string, SidebarRow[]>, parentExclude?: ReadonlySet<string>,
): CompanyPlan {
    const c = n.item;
    const own = nestedGroupsFor(ctx, c.key, scopeByCompany.get(c.key) ?? [], nest, false);
    const exclude = mergeExclude(parentExclude, own.claimed);
    const plan = companyPlan(ctx, c, c.companyId === null ? undefined : leaderRows.get(c.companyId), source, nest, exclude);
    if (plan.open && own.sections.length) {
        plan.groups = own.sections;
        plan.empty = false;
    }
    if (plan.open && n.children.length) {
        plan.children = n.children.map((k) => companyNode(ctx, k, leaderRows, source, nest, scopeByCompany, exclude));
        plan.empty = false;
    }
    return plan;
}

function companyParts(
    ctx: Ctx, list: SidebarRow[], override: ProjectBucket[] | undefined, leaderRows: Map<number, SidebarRow>,
    nest: NestCtx, allLeaders: ReadonlyMap<number, SidebarRow>,
): BandPart[] {
    const source = companySource();
    const rawBuckets = withInactiveProjects(list.length ? projectBuckets(list) : [], source.knownProjects ?? []);
    const rawProjectRows = new Map<string, SidebarRow[]>(rawBuckets.map((b) => [b.key, b.rows]));
    const companyNest: NestCtx = { ...nest, rawProjectRows };
    const buckets = override ?? rawBuckets;
    const filed = companyBuckets(buckets, source.companies, source.companyOf);
    const rawFiled = override ? companyBuckets(rawBuckets, source.companies, source.companyOf) : filed;
    const parentOf = source.parentOf;
    const toParent = (c: CompanyBucket<SidebarRow>): string | null => {
        const parent = parentOf && c.companyId !== null ? parentOf(c.companyId) : null;
        return parent === null ? null : `c:${parent}`;
    };
    const rawTree = nestByParent(rawFiled.companies, (c) => c.key, toParent);
    const scopeByCompany = new Map<string, SidebarRow[]>();
    const collectScope = (n: TreeNode<CompanyBucket<SidebarRow>>): SidebarRow[] => {
        const own = n.item.projects.flatMap((p) => p.rows);
        const leader = n.item.companyId !== null ? allLeaders.get(n.item.companyId) : undefined;
        const rows = (leader ? [leader, ...own] : own).concat(...n.children.map(collectScope));
        scopeByCompany.set(n.item.key, rows);
        return rows;
    };
    for (const root of rawTree) collectScope(root);
    const tree = nestByParent(filed.companies, (c) => c.key, toParent);
    const shown = override
        ? pruneTree(tree, (c) => (
            !!c.projects.length
            || (c.companyId !== null && leaderRows.has(c.companyId))
            || nestedGroupsFor(ctx, c.key, scopeByCompany.get(c.key) ?? [], companyNest, false).sections.length > 0
        ))
        : tree;
    const parts: BandPart[] = [];
    if (shown.length) {
        const open = !ctx.isFolded(COMPANIES_KEY);
        const label = t('sidebar.companies.heading');
        const allCompanyRows = [...scopeByCompany.values()].flat();
        const uniqueCompanyRows = Array.from(new Map(allCompanyRows.map((r) => [r.name, r])).values());
        const liveCompanies = uniqueCompanyRows.filter((r) => !r.asleep && r.status !== 'asleep' && !r.closed && !r.archived).length;
        parts.push({
            type: 'companies',
            key: COMPANIES_KEY,
            open,
            heading: {
                toggle: 'group',
                key: COMPANIES_KEY,
                bandKind: 'reserved',
                expanded: open,
                bodyId: `session-sidebar-group-body-${COMPANIES_KEY}`,
                title: t(open ? 'sidebar.companies.collapse' : 'sidebar.companies.expand'),
                label,
                iconHtml: ctx.L.projectHeader!.iconHtml('building'),
                ledHtml: '',
                pickedIconHtml: '',
                rollupHtml: '',
                countSummary: { live: liveCompanies, total: uniqueCompanyRows.length },
            },
        });
        if (open) {
            parts.push(...shown.map((n) => companyNode(ctx, n, leaderRows, source, companyNest, scopeByCompany)));
        }
    }
    const rawRogue = rawFiled.rogue?.rows ?? [];
    const rogueNested = nestedGroupsFor(ctx, 'rogue', rawRogue, companyNest, true);
    if (filed.rogue || rogueNested.sections.length) {
        const rogueSection = sectionPlan(
            ctx, filed.rogue?.key ?? 'rogue', filed.rogue?.rows ?? [],
            { labelOverride: filed.rogue?.label ?? labelFor('rogue'), excludeNames: rogueNested.claimed },
        );
        if (!rogueSection.collapsed && rogueNested.sections.length) rogueSection.groups = rogueNested.sections;
        parts.push(rogueSection);
    }
    return parts;
}

function kindPlan(
    ctx: Ctx, key: string, label: string, rows: SidebarRow[], query: string, nest?: NestCtx,
    subtitleFor?: (row: SidebarRow) => string | null, emptyText?: string,
): SectionPlan | null {
    const nested = nest ? nestedGroupsFor(ctx, key, rows, nest, true) : { sections: [], claimed: new Set<string>() };
    if (!rows.length && !nested.sections.length && (!emptyText || query || ctx.hideEmptyKinds)) return null;
    const narrowed = query ? narrow(label, rows, query) : rows;
    if (query && !narrowed.length && !nested.sections.length) return null;
    const plan = sectionPlan(ctx, key, narrowed, { labelOverride: label, subtitleFor, noLight: true, excludeNames: nested.claimed });
    if (!plan.collapsed && nested.sections.length) plan.groups = nested.sections;
    return !narrowed.length && !nested.sections.length && !plan.collapsed && emptyText ? { ...plan, empty: emptyText } : plan;
}

function packPlan(ctx: Ctx, query: string, rows: readonly SidebarRow[], off: ReadonlySet<string>): PackPlan | null {
    const roster = packSource();
    if (roster.length < 2 || activeCountFilter()) return null;
    const ordered = [...roster].sort((a, b) => {
        const la = (a.label ?? '').toLowerCase();
        const lb = (b.label ?? '').toLowerCase();
        return la < lb ? -1 : la > lb ? 1 : a.install_id < b.install_id ? -1 : a.install_id > b.install_id ? 1 : 0;
    });
    const shown = query ? ordered.filter((m) => matchesLabel(m.label, query)) : ordered;
    if (query && !shown.length) return null;
    const open = !ctx.isFolded(PACK_KEY);
    const avg = averagePackStats(shown);
    return {
        type: 'pack',
        key: PACK_KEY,
        open,
        density: ctx.density,
        count: shown.length,
        heading: {
            toggle: 'group',
            key: PACK_KEY,
            bandKind: 'reserved',
            expanded: open,
            bodyId: `session-sidebar-group-body-${PACK_KEY}`,
            title: t(open ? 'sidebar.pack.collapse' : 'sidebar.pack.expand'),
            label: t('sidebar.pack.heading'),
            iconHtml: ctx.L.projectHeader!.iconHtml('wolf'),
            ledHtml: '',
            pickedIconHtml: '',
            rollupHtml: '',
            packHeaderStats: { open, ...avg },
        },
        rows: open
            ? shown.map((m) => ({
                id: m.install_id,
                label: m.label,
                alpha: m.is_master === true,
                self: m.is_self === true,
                link: m.is_self ? null : linkMarkFor(m),
                machine: m,
                off: off.has(m.install_id),
                lightHtml: hostLightHtml(m, rows),
            }))
            : [],
    };
}

function layoutsPlan(ctx: Ctx, list: SidebarRow[], query: string, nest: NestCtx): SectionPlan | null {
    const band = ctx.L.layouts ? ctx.L.layouts.bandRows(list) : null;
    const layoutRows = band ? band.rows : list.filter((r) => kindOf(r) === KIND_LAYOUT);
    const sub = nestedGroupsFor(ctx, LAYOUTS_KEY, layoutRows, nest, true);
    if ((!band || !band.rows.length) && !sub.sections.length) return null;
    const label = band?.label || t('layout.section.heading');
    const narrowed = query ? narrow(label, band?.rows ?? [], query) : (band?.rows ?? []);
    if (query && !narrowed.length && !sub.sections.length) return null;
    const s = sectionPlan(ctx, LAYOUTS_KEY, narrowed, { labelOverride: label, noLight: true, excludeNames: sub.claimed });
    if (!s.collapsed && sub.sections.length) s.groups = sub.sections;
    if (!s.collapsed) {
        const byName = new Map(layoutRows.map((r) => [r.name, r]));
        const foldSleep = sleepingFolded() && !query && !activeCountFilter();
        const isAsleep = (r: SidebarRow): boolean => Boolean(r.asleep || r.status === 'asleep');
        for (const row of s.rows) {
            if (row.type !== 'layout' || !row.members?.expanded) continue;
            const src = byName.get(row.key) as (SidebarRow & { _members?: SidebarRow[] }) | undefined;
            const scope = Array.isArray(src?._members) ? src._members : [];
            const lg = nestedGroupsFor(ctx, row.key, scope, nest, true);
            if (lg.sections.length) {
                row.members.groups = lg.sections;
                if (lg.claimed.size) {
                    row.members.rows = row.members.rows.filter((m) => !lg.claimed.has(m.key));
                }
            }
            if (foldSleep && row.members.rows.length) {
                const asleepNames = new Set(scope.filter(isAsleep).map((m) => m.name));
                const liveRows: RowPlan[] = [];
                const sleepRows: RowPlan[] = [];
                for (const m of row.members.rows) {
                    const mAsleep = m.type === 'session' && (m.attrs['data-asleep'] === '1' || asleepNames.has(m.key));
                    if (mAsleep) sleepRows.push(m);
                    else liveRows.push(m);
                }
                if (sleepRows.length) {
                    row.members.rows = liveRows;
                    row.members.sleepingRows = sleepRows;
                }
            }
        }
    }
    return s;
}

function groupsPlan(ctx: Ctx, drawn: SectionPlan[], dragging: boolean): GroupsPlan | null {
    if (!drawn.length) return null;
    const open = !ctx.isFolded(GROUPS_KEY) || dragging;
    return {
        type: 'groups',
        key: GROUPS_KEY,
        open,
        heading: {
            toggle: 'group',
            key: GROUPS_KEY,
            bandKind: 'reserved',
            expanded: open,
            bodyId: `session-sidebar-group-body-${GROUPS_KEY}`,
            title: t(open ? 'sidebar.groups.collapse' : 'sidebar.groups.expand'),
            label: t('sidebar.groups.heading'),
            iconHtml: ctx.L.projectHeader!.iconHtml('agent-group'),
            ledHtml: '',
            pickedIconHtml: '',
            rollupHtml: '',
        },
        sections: open ? drawn : [],
    };
}

/* nothing at all */
function bodyParts(ctx: Ctx, list: SidebarRow[], query: string, dragging: boolean, order: readonly SectionId[], packRows: readonly SidebarRow[], off: ReadonlySet<string>): BandPart[] {
    const { L } = ctx;
    const rawBands = bands(list);
    const sections = filteredBandSections(rawBands, labelFor, query);
    const rawByKey = new Map(rawBands.map((b) => [b.key, b.rows]));
    const hideEmpty = emptySectionsHidden();
    const nest: NestCtx = { allRows: list, query, dragging, rawProjectRows: new Map() };
    const pinnedBand = sections.find((s) => s.key === 'pinned');
    const pinnedNested = nestedGroupsFor(ctx, 'pinned', rawByKey.get('pinned') ?? [], nest, true);
    const pinnedSections: SectionPlan[] = [];
    if (pinnedBand && (keepBandSection('pinned', pinnedBand.rows, dragging, query, hideEmpty) || pinnedNested.sections.length)) {
        const p = sectionPlan(ctx, 'pinned', pinnedBand.rows, { noLight: true, excludeNames: pinnedNested.claimed });
        if (!p.collapsed && pinnedNested.sections.length) p.groups = pinnedNested.sections;
        pinnedSections.push(p);
    }
    const topGroupSections: SectionPlan[] = [];
    for (const b of sections) {
        if (b.key === 'pinned') continue;
        const sub = nestedGroupsFor(ctx, b.key, rawByKey.get(b.key) ?? [], nest, true);
        if (!keepBandSection(b.key, b.rows, dragging, query, hideEmpty) && !sub.sections.length) continue;
        const s = sectionPlan(ctx, b.key, b.rows, { excludeNames: sub.claimed });
        if (!s.collapsed && sub.sections.length) s.groups = sub.sections;
        topGroupSections.push(s);
    }
    const parts: BandPart[] = [];
    const alphaRow = ctx.leaders.empty ? null : placeLeaders(list, ctx.leaders).alpha;
    if (alphaRow && (!query || narrow('', [alphaRow], query).length)) {
        parts.push({ type: 'leader', key: 'leader:alpha', row: rowPlan(ctx, alphaRow, 'leader') });
    }
    const placed = placeLeaders(list, ctx.leaders);
    const shownCompany = new Map<number, SidebarRow>();
    for (const [id, row] of placed.companies) if (!query || narrow('', [row], query).length) shownCompany.set(id, row);
    const override = query ? filteredProjectBuckets(projectBuckets(placed.rest), query) : undefined;
    const companyUnit = companyParts(ctx, placed.rest, override, shownCompany, nest, placed.companies);
    const browserLabel = L.i18n && typeof L.i18n.t === 'function' ? L.i18n.t('browser.section') : 'browsers';
    const filesLabel = L.i18n && typeof L.i18n.t === 'function' ? L.i18n.t('files.section') : 'files';
    const one = (part: BandPart | null): BandPart[] => (part ? [part] : []);
    const units: Record<SectionId, () => BandPart[]> = {
        pinned: () => pinnedSections,
        layouts: () => one(layoutsPlan(ctx, list, query, nest)),
        groups: () => [
            ...one(groupsPlan(ctx, topGroupSections, dragging)),
            ...(dragging && groupsUsable() ? [{ type: 'newgroup' as const, key: NEW_GROUP_KEY }] : []),
        ],
        companies: () => companyUnit.filter((p) => p.key !== 'rogue'),
        rogue: () => companyUnit.filter((p) => p.key === 'rogue'),
        terminals: () => one(kindPlan(ctx, BAND_TERMINALS, TERMINALS_LABEL, terminalRows(list), query, nest, folderLabel, t('sidebar.terminals.empty'))),
        browsers: () => one(kindPlan(ctx, BAND_BROWSERS, browserLabel, list.filter(isBrowserBand), query, nest, undefined, t('sidebar.browsers.empty'))),
        files: () => one(kindPlan(ctx, BAND_FILES, filesLabel, list.filter(isFileRow), query, nest, undefined, t('sidebar.files.empty'))),
        [PAGE_SECTION_SLOT]: () => pageSectionIds(list).flatMap((id) => {
            const meta = pageSectionMeta(id);
            const label = meta && L.i18n && typeof L.i18n.t === 'function' ? L.i18n.t(meta.labelKey) : id;
            return one(kindPlan(ctx, id, label, pageSectionRows(list, id), query, nest));
        }),
        pack: () => one(packPlan(ctx, query, packRows, off)),
    };
    for (const id of order) parts.push(...units[id]());
    return parts;
}

export function buildListPlan(L: LegacyDrawer, input: PaintInput): ListPlan | null {
    if (!L.projectHeader) return null;
    const attention = attentionHtml(input.listing);
    const notice = arrangementNoticeHtml(input.arrangement);
    const listed = Array.isArray(input.rows) ? input.rows : [];
    const leaders = leaderIndex();
    const rows = !(leadersShown() && swarmIsOn()) ? (leaders.empty ? listed : listed.filter((r) => !leaders.of(r)))
        : input.listing && !input.listing.ok ? listed
        : [...listed, ...ghostLeaderRows(leaderRoster(), listed, leaders, (id) => projectNameOf(id))];
    const dragging = !!(input.opts && input.opts.dragging);
    const query = (input.opts && input.opts.query) || '';
    const folded = (input.arrangement && Array.isArray(input.arrangement.collapsed))
        ? input.arrangement.collapsed
        : [];
    const off = offMachineIds(folded);
    const shown = filterRowsByHost(rows, packSource(), off);
    const ctx: Ctx = {
        L, density: input.density, isFolded: (key) => foldPresent(key, folded.indexOf(key) !== -1, query !== ''), host: rowHost(), leaders, query,
        hideEmptyKinds: emptySectionsHidden() && !dragging,
    };
    if (query && query !== FILTER_ONLY_QUERY && !dragging && input.opts?.searchList === true) {
        return { leadHtml: notice + attention, parts: searchParts(shown, query, (r) => rowPlan(ctx, r, SEARCH_AGENTS_BAND)), tailHtml: '' };
    }
    watchPack();
    if (shown.length === 0) {
        if (input.listing && !input.listing.ok) return { leadHtml: notice + attention, parts: [], tailHtml: '' };
        const pack = packPlan(ctx, query, rows, off);
        return { leadHtml: notice + (rows.length ? '' : EMPTY_HTML), parts: pack ? [pack] : [], tailHtml: '' };
    }
    watchCompanies();
    watchLeaders();
    const order = previewOrder() ?? resolveSectionOrder(input.arrangement?.sections);
    const parts = bodyParts(ctx, shown, query, dragging, order, rows, off);
    if (query && !parts.length) {
        return { leadHtml: notice + noMatchesHtml(query), parts: [], tailHtml: '' };
    }
    return { leadHtml: notice + attention, parts, tailHtml: '' };
}
