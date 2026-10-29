import {
    BAND_BROWSERS, BAND_FILES, BAND_TERMINALS, bands, companyBuckets, filteredBandSections, filteredProjectBuckets,
    folderLabel, isBrowserBand, isFileRow, pageSectionIds, pageSectionRows, keepBandSection, labelFor, narrow, projectBuckets, terminalRows,
    type CompanyBucket,
} from '../drawer/bucketing';
import { orderBand } from '../drawer/arrangement';
import { nestByParent, pruneTree, type TreeNode } from '../drawer/lineage-tree';
import { BAND_PROJECT_PREFIX, groupUuidOf } from '../drawer/group-store';
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
import { rowHost, type RowHost } from './row-host';
import { buildRowPlan, type GlyphChip, type RowPlan, type TextChip } from './row-plan';
import { inactiveProjectIcon, movedAwayChip } from './row-chips';
import { ghostLeaderRows, placeLeaders, projectLeaderFirst, type LeaderIndex } from './leaders';
import { GROUPS_FOLD_KEY, SPAWNED_FOLD_SUFFIX } from '../drawer/store-keys';
import { foldPresent } from '../drawer/fold-view';
import { PAGE_SECTION_SLOT, pageSectionMeta } from '../drawer/page-sections';
import { previewOrder, resolveSectionOrder, type SectionId } from '../drawer/section-order';
import { leadersShown } from '../drawer/leader-visibility';
import { emptySectionsHidden } from '../drawer/empty-sections.svelte';
import { companyTint, projectTint } from './tint';
import { archivedLast } from '../drawer/archived-rows';
import { leaderIndex, leaderRoster, projectNameOf, watchLeaders } from './leaders-source.svelte';

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
    fxHtml?: string;
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
    spawned: SpawnedPlan | null;
    children?: SectionPlan[];
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
    heading: HeadingPlan;
    sections: SectionPlan[];
    empty: boolean;
    leader: RowPlan | null;
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

export type BandPart = SectionPlan | CompanyPlan | LeaderPlan | CompaniesPlan | PackPlan | GroupsPlan | SearchAgentsPlan | SearchConversationsPlan;

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

export function parseAttrs(attrs: string): Record<string, string> {
    const out: Record<string, string> = {};
    const decode = (v: string): string => v
        .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
        .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
    for (const m of (attrs || '').matchAll(/([\w:-]+)="([^"]*)"/g)) {
        out[m[1] as string] = decode(m[2] as string);
    }
    return out;
}

interface Ctx {
    L: LegacyDrawer;
    density: string;
    isFolded: (key: string) => boolean;
    host: RowHost;
    leaders: LeaderIndex;
    query: string;
    hideEmptyKinds: boolean;
}

function rowPlan(ctx: Ctx, r: SidebarRow, band: string, subtitle?: string | null): RowPlan {
    const plan = buildRowPlan(r, ctx.density, band, subtitle, ctx.host);
    const info = ctx.leaders.empty || plan.type !== 'session' ? null : ctx.leaders.of(r);
    if (info && plan.type === 'session') {
        plan.leader = { rank: info.rank, label: t(`leader.mark.${info.rank}`) };
        plan.attrs['data-leader'] = info.rank;
        if (typeof r.swarm_agent_id === 'number') {
            plan.ghost = { agentId: r.swarm_agent_id, name: info.name, rank: info.rank };
            plan.attrs['data-ghost'] = '1';
            plan.pin = null;
            plan.keepAwake = null;
            plan.menu = null;
            plan.actions = [];
        }
    }
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
    const heading: HeadingPlan = {
        toggle: 'group',
        key,
        bandKind,
        expanded: !collapsed,
        bodyId,
        title,
        label,
        iconHtml: PH.iconHtml(PH.iconForBand(key, o.isProject)),
        ledHtml: PH.ledHtml(rows, collapsed, showLight),
        pickedIconHtml: PH.pickedIconHtml ? PH.pickedIconHtml({ key, bandKind }) : '',
        rollupHtml: L.subagents && !o.isProject ? L.subagents.rollupHtml(rows) : '',
        ...(menu ? { menu } : {}),
        ...(o.movedTo !== undefined ? { badge: movedAwayChip(o.movedTo) } : o.inactive ? { inactive: inactiveProjectIcon() } : {}),
    };
    const fxHtml = L.groupColour?.groupFxHtml ? L.groupColour.groupFxHtml(key, label) : '';
    if (fxHtml) heading.fxHtml = fxHtml;
    const kids = o.isProject && ctx.leaders.spawned ? rows.filter((r) => ctx.leaders.spawned!(r)) : [];
    const direct = kids.length ? rows.filter((r) => !ctx.leaders.spawned!(r)) : rows;
    const ordered = archivedLast(orderBand(key, direct));
    const drawn = o.isProject ? projectLeaderFirst(ordered, ctx.leaders) : ordered;
    return {
        type: 'section',
        key,
        colourAttrs: parseAttrs(L.groupColour ? L.groupColour.attrsFor(key) : ''),
        ...(o.isProject && projectTint(key) ? { blockColor: projectTint(key) } : {}),
        collapsed,
        count: rows.length,
        bodyId,
        heading,
        rows: collapsed
            ? []
            : uniqueKeys(drawn.map((r) => rowPlan(ctx, r, key, o.subtitleFor ? o.subtitleFor(r) : undefined))),
        spawned: kids.length ? spawnedPlan(ctx, key, kids) : null,
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

function companyPlan(
    ctx: Ctx, c: CompanyBucket<SidebarRow>, leaderRow: SidebarRow | undefined, source?: Pick<CompanySource, 'projectParentOf' | 'projectArchived' | 'projectMovedTo'>,
): CompanyPlan {
    const PH = ctx.L.projectHeader!;
    const open = !ctx.isFolded(c.key);
    const allRows = c.projects.reduce<SidebarRow[]>((acc, b) => acc.concat(b.rows), []);
    const orphaned = c.companyId === null;
    const label = orphaned ? t('sidebar.company.orphaned') : c.label;
    return {
        type: 'company',
        key: c.key,
        open,
        empty: open && !c.projects.length && !leaderRow,
        leader: open && leaderRow ? rowPlan(ctx, leaderRow, 'leader') : null,
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
            ...(orphaned ? {} : { menu: { kind: 'company', id: c.key, label: t('sidebar.company.menu.title', { name: label }) } as HeadingMenuPlan }),
            ...(companyTint(c.companyId) ? { tint: companyTint(c.companyId) } : {}),
        },
        sections: open ? projectSections(ctx, c.projects, source?.projectParentOf, source?.projectArchived, source?.projectMovedTo) : [],
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
    isArchived?: CompanySource['projectArchived'], movedTo?: CompanySource['projectMovedTo'],
): SectionPlan[] {
    const moved = (b: ProjectBucket): string | null => (b.isProject && movedTo ? movedTo(b.key.slice(BAND_PROJECT_PREFIX.length)) : null);
    const archived = (b: ProjectBucket): boolean => !!(b.isProject && isArchived && isArchived(b.key.slice(BAND_PROJECT_PREFIX.length)));
    const inactive = (b: ProjectBucket): boolean => b.isProject && (archived(b) || b.rows.length === 0);
    const plan = (b: ProjectBucket): SectionPlan => sectionPlan(ctx, b.key, b.rows, {
        labelOverride: b.label, isProject: b.isProject, ...(inactive(b) ? { inactive: true } : {}),
        ...(moved(b) !== null ? { movedTo: moved(b) as string } : {}),
    });
    if (!parentOf) return buckets.map(plan);
    const parentKey = (b: ProjectBucket): string | null => {
        const parent = b.isProject ? parentOf(b.key.slice(BAND_PROJECT_PREFIX.length)) : null;
        return parent === null ? null : BAND_PROJECT_PREFIX + parent;
    };
    const toSection = (n: TreeNode<ProjectBucket>, nested: boolean): SectionPlan => {
        const s = plan(n.item);
        if (nested) s.nested = true;
        if (n.children.length && !s.collapsed) s.children = n.children.map((k) => toSection(k, true));
        return s;
    };
    return nestByParent(buckets, (b) => b.key, parentKey).map((n) => toSection(n, false));
}

function companyNode(
    ctx: Ctx, n: TreeNode<CompanyBucket<SidebarRow>>, leaderRows: Map<number, SidebarRow>, source: CompanySource,
): CompanyPlan {
    const c = n.item;
    const plan = companyPlan(ctx, c, c.companyId === null ? undefined : leaderRows.get(c.companyId), source);
    if (plan.open && n.children.length) {
        plan.children = n.children.map((k) => companyNode(ctx, k, leaderRows, source));
        plan.empty = false;
    }
    return plan;
}

function companyParts(
    ctx: Ctx, list: SidebarRow[], override: ProjectBucket[] | undefined, leaderRows: Map<number, SidebarRow>,
): BandPart[] {
    const source = companySource();
    const buckets = override ?? withInactiveProjects(list.length ? projectBuckets(list) : [], source.knownProjects ?? []);
    const filed = companyBuckets(buckets, source.companies, source.companyOf);
    const parentOf = source.parentOf;
    const tree = nestByParent(filed.companies, (c) => c.key, (c) => {
        const parent = parentOf && c.companyId !== null ? parentOf(c.companyId) : null;
        return parent === null ? null : `c:${parent}`;
    });
    const shown = override
        ? pruneTree(tree, (c) => !!c.projects.length || (c.companyId !== null && leaderRows.has(c.companyId)))
        : tree;
    const parts: BandPart[] = [];
    if (shown.length) {
        const open = !ctx.isFolded(COMPANIES_KEY);
        const label = t('sidebar.companies.heading');
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
                },
        });
        if (open) {
            parts.push(...shown.map((n) => companyNode(ctx, n, leaderRows, source)));
        }
    }
    if (filed.rogue) {
        parts.push(sectionPlan(ctx, filed.rogue.key, filed.rogue.rows, { labelOverride: filed.rogue.label }));
    }
    return parts;
}

function kindPlan(
    ctx: Ctx, key: string, label: string, rows: SidebarRow[], query: string,
    subtitleFor?: (row: SidebarRow) => string | null, emptyText?: string,
): SectionPlan | null {
    if (!rows.length && (!emptyText || query || ctx.hideEmptyKinds)) return null;
    const narrowed = query ? narrow(label, rows, query) : rows;
    if (query && !narrowed.length) return null;
    const plan = sectionPlan(ctx, key, narrowed, { labelOverride: label, subtitleFor, noLight: true });
    return !narrowed.length && !plan.collapsed && emptyText ? { ...plan, empty: emptyText } : plan;
}

function packPlan(ctx: Ctx, query: string, rows: readonly SidebarRow[], off: ReadonlySet<string>): PackPlan | null {
    const roster = packSource();
    if (roster.length < 2 || activeCountFilter()) return null;
    const ordered = [...roster].sort((a, b) => Number(b.is_self) - Number(a.is_self));
    const shown = query ? ordered.filter((m) => matchesLabel(m.label, query)) : ordered;
    if (query && !shown.length) return null;
    const open = !ctx.isFolded(PACK_KEY);
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

function layoutsPlan(ctx: Ctx, list: SidebarRow[], query: string): SectionPlan | null {
    const band = ctx.L.layouts ? ctx.L.layouts.bandRows(list) : null;
    if (!band || !band.rows.length) return null;
    const narrowed = query ? narrow(band.label, band.rows, query) : band.rows;
    if (query && !narrowed.length) return null;
    return sectionPlan(ctx, LAYOUTS_KEY, narrowed, { labelOverride: band.label, noLight: true });
}

function groupsPlan(ctx: Ctx, drawn: Array<{ key: string; rows: SidebarRow[] }>, dragging: boolean): GroupsPlan | null {
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
            iconHtml: ctx.L.projectHeader!.iconHtml('users'),
            ledHtml: '',
            pickedIconHtml: '',
            rollupHtml: '',
        },
        sections: open ? drawn.map((b) => sectionPlan(ctx, b.key, b.rows, {})) : [],
    };
}

/* nothing at all */
function bodyParts(ctx: Ctx, list: SidebarRow[], query: string, dragging: boolean, order: readonly SectionId[], packRows: readonly SidebarRow[], off: ReadonlySet<string>): BandPart[] {
    const { L } = ctx;
    const sections = filteredBandSections(bands(list), labelFor, query);
    const kept = sections.filter((b) => keepBandSection(b.key, b.rows, dragging, query));
    const parts: BandPart[] = [];
    const alphaRow = ctx.leaders.empty ? null : placeLeaders(list, ctx.leaders).alpha;
    if (alphaRow && (!query || narrow('', [alphaRow], query).length)) {
        parts.push({ type: 'leader', key: 'leader:alpha', row: rowPlan(ctx, alphaRow, 'leader') });
    }
    const placed = placeLeaders(list, ctx.leaders);
    const shownCompany = new Map<number, SidebarRow>();
    for (const [id, row] of placed.companies) if (!query || narrow('', [row], query).length) shownCompany.set(id, row);
    const override = query ? filteredProjectBuckets(projectBuckets(placed.rest), query) : undefined;
    const companyUnit = companyParts(ctx, placed.rest, override, shownCompany);
    const browserLabel = L.i18n && typeof L.i18n.t === 'function' ? L.i18n.t('browser.section') : 'browsers';
    const filesLabel = L.i18n && typeof L.i18n.t === 'function' ? L.i18n.t('files.section') : 'files';
    const one = (part: BandPart | null): BandPart[] => (part ? [part] : []);
    const units: Record<SectionId, () => BandPart[]> = {
        pinned: () => [
            ...kept.filter((s) => s.key === 'pinned').map((b) => sectionPlan(ctx, b.key, b.rows, { noLight: true })),
        ],
        layouts: () => one(layoutsPlan(ctx, list, query)),
        groups: () => one(groupsPlan(ctx, kept.filter((s) => s.key !== 'pinned'), dragging)),
        companies: () => companyUnit.filter((p) => p.key !== 'rogue'),
        rogue: () => companyUnit.filter((p) => p.key === 'rogue'),
        terminals: () => one(kindPlan(ctx, BAND_TERMINALS, TERMINALS_LABEL, terminalRows(list), query, folderLabel, t('sidebar.terminals.empty'))),
        browsers: () => [
            ...one(kindPlan(ctx, BAND_BROWSERS, browserLabel, list.filter(isBrowserBand), query, undefined, t('sidebar.browsers.empty'))),
            ...one(kindPlan(ctx, BAND_FILES, filesLabel, list.filter(isFileRow), query)),
        ],
        [PAGE_SECTION_SLOT]: () => pageSectionIds(list).flatMap((id) => {
            const meta = pageSectionMeta(id);
            const label = meta && L.i18n && typeof L.i18n.t === 'function' ? L.i18n.t(meta.labelKey) : id;
            return one(kindPlan(ctx, id, label, pageSectionRows(list, id), query));
        }),
        pack: () => one(packPlan(ctx, query, packRows, off)),
    };
    for (const id of order) parts.push(...units[id]());
    return parts;
}

export function buildListPlan(L: LegacyDrawer, input: PaintInput): ListPlan | null {
    if (!L.groups || !L.projectHeader) return null;
    const attention = attentionHtml(input.listing);
    const notice = arrangementNoticeHtml(input.arrangement);
    const listed = Array.isArray(input.rows) ? input.rows : [];
    const leaders = leaderIndex();
    //  hidden 
    const rows = !leadersShown() ? (leaders.empty ? listed : listed.filter((r) => !leaders.of(r)))
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
