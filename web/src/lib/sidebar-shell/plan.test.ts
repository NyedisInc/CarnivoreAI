/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as GroupStore from '../drawer/group-store';
import * as Store from '../drawer/store';
import { setQuery } from '../drawer/search';
import { buildListPlan, parseAttrs, type ListPlan, type PaintInput, type SectionPlan } from './plan';
import { setPreviewOrder } from '../drawer/section-order';
import type { LegacyDrawer, SidebarRow } from './legacy';
import { setCountFilter } from '../drawer/count-filter.svelte';
import type { PackMachine } from '../pack-machines/pack-machines-store.svelte';

let roster: Array<Partial<PackMachine>> = [];
vi.mock('./pack-source.svelte', () => ({ packSource: () => roster, watchPack: () => {} }));

function stubs(over: Partial<LegacyDrawer> = {}): LegacyDrawer {
    return {
        groups: {},
        projectHeader: {
            ledHtml: (_r, collapsed, show) => (collapsed && show !== false ? '<led>' : ''),
            iconHtml: (n) => (n ? `<i ${n}>` : ''),
            iconForBand: (k, p) => (p ? 'folder' : k === 'pinned' ? 'pin' : null),
        },
        ...over,
    };
}

function input(rows: SidebarRow[], over: Partial<PaintInput> = {}): PaintInput {
    return { rows, density: 'compact', listing: { ok: true }, missing: [], arrangement: null, opts: {}, ...over };
}

const A: SidebarRow = { name: 'a', is_pinned: true, project_id: 1, project_name: 'one' };
const B: SidebarRow = { name: 'b', project_id: 1, project_name: 'one' };
const T: SidebarRow = { name: 't', agent_family: 'shell', project_id: null };
const W: SidebarRow = { name: 'browser:1', kind: 'browser', project_id: null };

function folded(keys: string[]): PaintInput['arrangement'] {
    return { ...Store.current(), collapsed: keys };
}

function groupBand(plan: ListPlan, key: string): SectionPlan | undefined {
    const part = plan.parts.find((p) => p.type === 'groups');
    return part?.type === 'groups' ? part.sections.find((s) => s.key === key) : undefined;
}

beforeEach(() => {
    roster = [{ install_id: 'self', label: 'this one', is_self: true }];
    setCountFilter(null);
    localStorage.clear();
    Store.load();
    setQuery('');
    GroupStore.apply({ status: 'ok', groups: [{ group_uuid: 'x', name: 'x crew', position: 0, members: ['b'] }] });
});

describe('buildListPlan', () => {
    it('TERMINALS and BROWSERS always draw, with a quiet line while open and empty (#1804)', () => {
        const plan = buildListPlan(stubs(), input([A, B]))!;
        const kinds = plan.parts.filter((p) => p.key === 'terminals' || p.key === 'browsers');
        expect(kinds.map((p) => p.key)).toEqual(['terminals', 'browsers']);
        expect(kinds.map((p) => (p as { empty?: string }).empty)).toEqual(['no terminals open', 'no browsers open']);
        const foldedPlan = buildListPlan(stubs(), input([A, B], { arrangement: folded(['terminals']) }))!;
        expect((foldedPlan.parts.find((p) => p.key === 'terminals') as { empty?: string }).empty).toBeUndefined();
        const withRow = buildListPlan(stubs(), input([A, T]))!;
        expect((withRow.parts.find((p) => p.key === 'terminals') as { empty?: string }).empty).toBeUndefined();
        setQuery('zzz-no-match');
        expect(buildListPlan(stubs(), input([A, B], { opts: { query: 'zzz-no-match' } }))!.parts.some((p) => p.key === 'terminals')).toBe(false);
    });

    it('keeps the contract order: pinned, layouts, groups, companies, then the kind bands', () => {
        const layout: SidebarRow = { name: 'layout:l1', kind: 'layout', label: 'focus', project_id: null };
        const plan = buildListPlan(stubs({ layouts: { bandRows: () => ({ label: 'layouts', rows: [layout] }) } }), input([A, B, T, W]))!;
        expect(plan.parts.map((p) => p.key)).toEqual(['pinned', 'layouts', 'groups', 'companies', 'c:orphaned', 'terminals', 'browsers']);
    });

    it('draws the sections in the user\'s stored order, a hidden one keeping its place, and a drag preview wins (#1687)', () => {
        const layout: SidebarRow = { name: 'layout:l1', kind: 'layout', label: 'focus', project_id: null };
        const drawer = stubs({ layouts: { bandRows: () => ({ label: 'layouts', rows: [layout] }) } });
        const stored = { ...Store.current(), sections: ['browsers', 'terminals', 'companies', 'groups', 'layouts', 'pinned'] };
        const plan = buildListPlan(drawer, input([A, B, T, W], { arrangement: stored }))!;
        const keys = plan.parts.map((p) => p.key);
        expect(keys).toEqual(['browsers', 'terminals', 'companies', 'c:orphaned', 'groups', 'layouts', 'pinned']);
        expect(keys.length).toBeGreaterThan(5);
        expect(keys.indexOf('c:orphaned')).toBe(keys.indexOf('companies') + 1);
        setPreviewOrder(['pack', 'pinned', 'layouts', 'groups', 'companies', 'rogue', 'terminals', 'browsers']);
        try {
            expect(buildListPlan(drawer, input([A, B, T, W], { arrangement: stored }))!.parts.map((p) => p.key)[0]).toBe('pinned');
        } finally {
            setPreviewOrder(null);
        }
    });

    it('a folded band draws no rows but its heading still gets the rows for its light', () => {
        const plan = buildListPlan(stubs(), input([A, B], { arrangement: folded(['g:x']) }))!;
        const g = groupBand(plan, 'g:x');
        expect(g?.type).toBe('section');
        if (g?.type !== 'section') return;
        expect(g.rows).toEqual([]);
        expect(g.heading.ledHtml).toBe('<led>');
        expect(g.heading.expanded).toBe(false);
        expect(g.heading.title).toBe('Expand the x crew group (1 agent)');
        expect(g.heading.bandKind).toBe('group');
    });

    it('a query that matches nothing is "no matches", not the empty list', () => {
        const plan = buildListPlan(stubs(), input([A, B], { opts: { query: 'zzz' } }))!;
        expect(plan.parts).toEqual([]);
        expect(plan.leadHtml).toContain('data-search-empty="1"');
        expect(plan.leadHtml).not.toContain('no other agents');
    });

    it('an unreadable listing with no rows draws the CANNOT DETERMINE block, never the empty line', () => {
        const plan = buildListPlan(stubs(), input([], { listing: { ok: false, reason: 'timeout', detail: 'x' } }))!;
        expect(plan.leadHtml).toContain('CANNOT DETERMINE');
        expect(plan.leadHtml).not.toContain('no other agents');
        const empty = buildListPlan(stubs(), input([]))!;
        expect(empty.leadHtml).toContain('no other agents');
    });

    it('an unreadable saved order is said out loud above the list', () => {
        const plan = buildListPlan(stubs(), input([A], {
            arrangement: { ...Store.current(), status: 'unreadable', reason: 'stored value is not valid JSON' },
        }))!;
        expect(plan.leadHtml).toContain('CANNOT LOAD your saved order');
        expect(plan.leadHtml).toContain('stored value is not valid JSON');
    });

    it('declines (null) when a render helper it cannot draw without is missing', () => {
        expect(buildListPlan(stubs({ groups: undefined }), input([A]))).toBeNull();
        expect(buildListPlan(stubs({ projectHeader: undefined }), input([A]))).toBeNull();
        expect(buildListPlan(stubs(), input([A]))).not.toBeNull();
    });
});

describe('the heading kebabs (wrapper package S-2)', () => {
    it('a group and a project name their menu and its accessible name; a reserved band and the orphaned company have none', () => {
        const plan = buildListPlan(stubs(), input([A, B, T, W]))!;
        const group = groupBand(plan, 'g:x');
        expect(group?.heading.menu).toEqual({ kind: 'group', id: 'x', label: 'rename, sleep, reorder or remove the x crew group' });
        const pinned = plan.parts.find((p) => p.key === 'pinned');
        expect(pinned?.type === 'section' && pinned.heading.menu).toBeUndefined();
        const orphaned = plan.parts.find((p) => p.type === 'company');
        expect(orphaned?.type === 'company' && orphaned.key).toBe('c:orphaned');
        if (orphaned?.type !== 'company') return;
        expect(orphaned.heading.menu).toBeUndefined();
        const project = orphaned.sections.find((s) => s.key === 'p:1');
        expect(project?.heading.menu).toEqual({ kind: 'project', id: 'p:1', label: 'rename, sleep or remove the one project' });
    });
});

describe('the pinned heading and the pack section (#1687)', () => {
    const TWO: Array<Partial<PackMachine>> = [
        { install_id: 'b', label: 'beta', is_self: false, state: 'connected', snapshot: { load: {} } as PackMachine['snapshot'], age_seconds: 1 },
        { install_id: 'a', label: 'alpha-box', is_self: true, is_master: true, state: 'self' },
    ];

    it('a folded pinned heading draws no light, a folded group still does, and pack lists the computers after browsers', () => {
        roster = TWO;
        const plan = buildListPlan(stubs(), input([A, B, T, W], { arrangement: folded(['pinned', 'g:x']) }))!;
        const pinned = plan.parts.find((p) => p.key === 'pinned');
        const group = groupBand(plan, 'g:x');
        expect(pinned?.type === 'section' && pinned.count).toBe(1);
        expect(group?.count).toBe(1);
        if (pinned?.type !== 'section' || !group) return;
        expect(group.heading.ledHtml, 'negative control: a folded group keeps its light').toBe('<led>');
        expect(pinned.heading.ledHtml).toBe('');
        const keys = plan.parts.map((p) => p.key);
        expect(keys.slice(-3)).toEqual(['terminals', 'browsers', 'pack']);
        const pack = plan.parts[plan.parts.length - 1]!;
        expect(pack.type).toBe('pack');
        if (pack.type !== 'pack') return;
        expect(pack.rows.map((r) => r.id), 'this computer first, then the roster order').toEqual(['a', 'b']);
        expect(pack.rows[0]).toMatchObject({ label: 'alpha-box', self: true, alpha: true, link: null });
        expect(pack.rows[1]).toMatchObject({ label: 'beta', self: false, alpha: false, link: 'linked' });
        expect(pack.heading).toMatchObject({ key: 'pack', label: 'pack', ledHtml: '', expanded: true });
        expect(pack.heading.menu, 'a section heading has no menu').toBeUndefined();
        expect(pack.heading.iconHtml).toContain('wolf');
    });

    it('a connected computer with no snapshot or a stale one draws a down link, a fresh one a linked link (#2362)', () => {
        const linkOf = (over: Partial<PackMachine>): unknown => {
            roster = [{ ...TWO[1]! }, { ...TWO[0]!, ...over }];
            const pack = buildListPlan(stubs(), input([A, B, T]))!.parts.find((p) => p.type === 'pack');
            return pack?.type === 'pack' ? pack.rows.find((r) => r.id === 'b')?.link : 'no pack';
        };
        expect(linkOf({}), 'fresh snapshot').toBe('linked');
        expect(linkOf({ snapshot: null }), 'no snapshot').toBe('down');
        expect(linkOf({ age_seconds: 31 }), 'stale snapshot').toBe('down');
    });

    it('one computer is no pack, a search narrows by computer label, a count filter hides it, a fold empties it', () => {
        expect(buildListPlan(stubs(), input([A, B]))!.parts.some((p) => p.type === 'pack'), 'roster of 1').toBe(false);
        roster = [];
        expect(buildListPlan(stubs(), input([A, B]))!.parts.some((p) => p.type === 'pack'), 'no roster').toBe(false);
        roster = TWO;
        const narrowed = buildListPlan(stubs(), input([A, B, T], { opts: { query: 'bet' } }))!.parts.find((p) => p.type === 'pack');
        expect(narrowed?.type === 'pack' && narrowed.rows.map((r) => r.id)).toEqual(['b']);
        expect(buildListPlan(stubs(), input([A, B, T], { opts: { query: 'zzz' } }))!.parts.some((p) => p.type === 'pack')).toBe(false);
        setCountFilter('working');
        expect(buildListPlan(stubs(), input([A, B, T]))!.parts.some((p) => p.type === 'pack'), 'count filter on').toBe(false);
        setCountFilter(null);
        const closed = buildListPlan(stubs(), input([A, B, T], { arrangement: folded(['pack']) }))!.parts.find((p) => p.type === 'pack');
        expect(closed?.type === 'pack' && closed.heading.expanded).toBe(false);
        expect(closed?.type === 'pack' && closed.rows).toEqual([]);
        expect(closed?.type === 'pack' && closed.count).toBe(2);
    });

    it('an empty drawer with two computers still lists the pack (the section does not need an agent)', () => {
        roster = TWO;
        const plan = buildListPlan(stubs(), input([]))!;
        expect(plan.leadHtml).toContain('no other agents');
        expect(plan.parts.map((p) => p.key)).toEqual(['pack']);
        roster = [];
        expect(buildListPlan(stubs(), input([]))!.parts).toEqual([]);
    });
});

describe('parseAttrs', () => {
    it('reads the colour attribute string into a record', () => {
        expect(parseAttrs(' data-group-colour="teal" data-group-anim="pulse"'))
            .toEqual({ 'data-group-colour': 'teal', 'data-group-anim': 'pulse' });
    });
    it('empty is empty, and entities are decoded', () => {
        expect(parseAttrs('')).toEqual({});
        expect(parseAttrs(' data-x="a&amp;b"')).toEqual({ 'data-x': 'a&b' });
    });
});
