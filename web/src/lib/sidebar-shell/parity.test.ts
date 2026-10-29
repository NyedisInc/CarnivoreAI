/** @vitest-environment jsdom */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { canonicalDom, loadLegacyDrawer, paintDrawer, type LegacyWindow } from './legacy-fixture';
import { legacyAnswer } from './goldens';
import { unmountPanel } from '../mount';
import * as Density from '../drawer/density';
import { timerChip } from '../timers/timers';
import { SHELL_ATTR, sidebarShell } from './shell.svelte';

let w: LegacyWindow;

const LAYOUTS = [
    { layout_uuid: 'l1', name: 'focus', members: [{ session_uuid: 'su-a' }], colour: 'teal', gradient: null, animation: 'none' },
    { layout_uuid: 'l2', name: 'review', members: [], colour: null, gradient: null, animation: 'none' },
];

function row(name: string, over: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        name, label: name.replace('cloude_', ''), created_by_cloude: true, status: 'idle',
        unread: false, is_pinned: false, project_id: 10, project_name: 'ProjectFoo',
        session_id: `ses_${name}`, session_uuid: `su-${name.slice(-1)}`, kind: 'agent', ...over,
    };
}

function baseRows(): Record<string, unknown>[] {
    return [
        row('cloude_a', { is_pinned: true, status: 'working', subagents_running: 2 }),
        row('cloude_b', { status: 'question', unread: true }),
        row('cloude_c', { project_id: 20, project_name: 'Studio', status: 'finished_unread' }),
        row('cloude_d', { project_id: 20, project_name: 'Studio', subagents_running: 1 }),
        row('cloude_e', { project_id: null, project_name: null, status: 'dead' }),
        row('cloude_t', { agent_family: 'shell', working_dir: '/Users/x/dev', project_id: null }),
        row('browser:0123456789abcdef', { kind: 'browser', label: 'docs', url: 'https://example.com/a', project_id: null }),
    ];
}

function withLayouts(rows: Record<string, unknown>[]): Record<string, unknown>[] {
    return rows.concat(w.SessionSidebarLayouts.rows(rows));
}

function applyGroups(): void {
    w.SessionSidebarGroupStore.apply({
        status: 'ok',
        groups: [
            { group_uuid: 'g1', name: 'work stuff', position: 0, members: ['cloude_b', 'cloude_c'], colour: 'violet', gradient: 'tide', animation: 'pulse' },
            { group_uuid: 'g2', name: 'empty one', position: 1, members: ['cloude_d'] },
        ],
    });
}

function ctrl(listEl: Element, rows: Record<string, unknown>[], extra: Record<string, unknown> = {}) {
    return { _rows: rows, _listing: { ok: true }, _lastSig: null, _dragging: false, _missing: [], listEl, ...extra };
}

function paintBoth(rows: Record<string, unknown>[], extra: Record<string, unknown> = {}) {
    const shellEl = document.getElementById('session-sidebar-list') as HTMLElement;
    unmountPanel(shellEl.id);
    paintDrawer(ctrl(shellEl, rows, extra));
    const shellHtml = shellEl.innerHTML.replace(/<!--[^>]*-->/g, '');
    const legacyEl = document.createElement('div');
    legacyEl.className = 'session-sidebar-list';
    legacyEl.innerHTML = legacyAnswer('parity', shellHtml);
    return { legacyEl, shellEl };
}

function expectParity(rows: Record<string, unknown>[], extra: Record<string, unknown> = {}) {
    const { legacyEl, shellEl } = paintBoth(rows, extra);
    expect(shellEl.getAttribute(SHELL_ATTR)).toBe('svelte');
    expect(legacyEl.getAttribute(SHELL_ATTR)).toBeNull();
    expect(canonicalDom(shellEl)).toBe(canonicalDom(legacyEl));
    expect(shellEl.innerHTML.replace(/<!--[^>]*-->/g, '')).toBe(legacyEl.innerHTML);
    return { legacyEl, shellEl };
}

beforeAll(() => {
    const list = document.createElement('div');
    list.id = 'session-sidebar-list';
    list.className = 'session-sidebar-list';
    document.body.appendChild(list);
    w = loadLegacyDrawer();
    w.CloudeWeb = {
        ...w.CloudeWeb,
        layouts: { list: () => LAYOUTS, get: () => null, isUnavailable: () => false },
        timerChip,
        sidebarShell,
    };
});

beforeEach(() => {
    w.SessionSidebarStore.save([], [], [], {}, {});
    w.SessionSidebarSearch.setQuery('');
    if (!w.SessionSidebarGroupStore.isProjectsOpen()) w.SessionSidebarGroupStore.toggleProjectsOpen();
    applyGroups();
    w.SessionSidebarArrangement.togglePin('cloude_a', ['cloude_a']);
});

describe('who handles a heading (issue #726, slice 2)', () => {
    it('a shell heading is the shell\'s, LAYOUTS included; a legacy-painted one is not', () => {
        const { legacyEl, shellEl } = expectParity(withLayouts(baseRows()));
        const shellGroup = shellEl.querySelector('[data-group-toggle="g:g1"]');
        const shellKebab = shellEl.querySelector('[data-group-menu="g1"]');
        const shellProjects = shellEl.querySelector('[data-group-toggle="c:orphaned"]');
        expect(sidebarShell.owns(shellGroup)).toBe(true);
        expect(sidebarShell.owns(shellKebab)).toBe(true);
        expect(sidebarShell.owns(shellProjects)).toBe(true);
        expect(sidebarShell.owns(shellEl.querySelector('[data-group-toggle="layouts"]'))).toBe(true);
        expect(sidebarShell.owns(legacyEl.querySelector('[data-group-toggle="g:g1"]'))).toBe(false);
        expect(sidebarShell.owns(null)).toBe(false);
    });

    it('a row in a shell band is the shell\'s (slice 4), a LAYOUTS band row included; a legacy-painted row is not', () => {
        const { legacyEl, shellEl } = expectParity(withLayouts(baseRows()));
        const shellRow = shellEl.querySelector('[data-group="p:10"] .session-sidebar-row');
        const pinnedRow = shellEl.querySelector('[data-group="pinned"] .session-sidebar-row');
        const layoutsRow = shellEl.querySelector('[data-group="layouts"] .session-sidebar-row');
        expect(shellRow && pinnedRow && layoutsRow).toBeTruthy();
        expect(sidebarShell.owns(shellRow)).toBe(true);
        expect(sidebarShell.owns(shellRow!.querySelector('[data-pin-session]'))).toBe(true);
        expect(sidebarShell.owns(pinnedRow)).toBe(true);
        expect(sidebarShell.owns(layoutsRow)).toBe(true);
        expect(sidebarShell.owns(legacyEl.querySelector('.session-sidebar-row'))).toBe(false);
        expect(sidebarShell.drew(shellEl)).toBe(true);
        expect(sidebarShell.drew(legacyEl)).toBe(false);
    });
});

describe('the shell and the legacy paint draw the same drawer', () => {
    it('every band open: pinned, layouts, groups, projects, rogue, terminals', () => {
        const { shellEl } = expectParity(withLayouts(baseRows()));
        const bands = Array.from(shellEl.querySelectorAll('[data-group]')).map((e) => e.getAttribute('data-group'));
        expect(bands).toEqual(['pinned', 'layouts', 'g:g1', 'g:g2', 'p:10', 'p:20', 'rogue', 'terminals', 'browsers']);
        expect(shellEl.querySelector('[data-group="g:g1"]')!.getAttribute('data-group-colour')).toBe('violet');
    });

    it('a group icon (issue #769): expanded and collapsed, and no icon draws nothing', () => {
        w.SessionSidebarGroupStore.apply({
            status: 'ok',
            groups: [
                { group_uuid: 'g1', name: 'work stuff', position: 0, members: ['cloude_b', 'cloude_c'], colour: 'violet', gradient: 'tide', animation: 'pulse', icon: 'flask' },
                { group_uuid: 'g2', name: 'empty one', position: 1, members: ['cloude_d'], icon: 'from-the-future' },
            ],
        });
        let { shellEl } = expectParity(withLayouts(baseRows()));
        const mark = shellEl.querySelector('[data-group="g:g1"] [data-group-icon="flask"]');
        expect(mark).not.toBeNull();
        expect(mark!.nextElementSibling!.className).toBe('session-sidebar-group__label');
        expect(shellEl.querySelector('[data-group="g:g2"] [data-group-icon]')).toBeNull();
        w.SessionSidebarArrangement.toggleCollapsed('g:g1');
        ({ shellEl } = expectParity(withLayouts(baseRows())));
        const folded = shellEl.querySelector('[data-group="g:g1"] [data-group-icon="flask"]');
        expect(folded!.previousElementSibling!.className).toBe('session-sidebar-group__project-led');
    });

    it('folded bands draw no rows and show their summary light', () => {
        for (const key of ['pinned', 'g:g1', 'p:20', 'rogue', 'terminals', 'browsers', 'layouts']) {
            w.SessionSidebarArrangement.toggleCollapsed(key);
        }
        const { shellEl } = expectParity(withLayouts(baseRows()));
        expect(shellEl.querySelector('[data-group="p:20"]')!.getAttribute('data-collapsed')).toBe('1');
        expect(shellEl.querySelector('[data-group="p:20"] .session-sidebar-group__project-led')).not.toBeNull();
    });

    it('a folded company heading hides its project sections (#1338)', () => {
        w.SessionSidebarStore.toggleCollapsed('c:orphaned');
        const { shellEl } = expectParity(withLayouts(baseRows()));
        expect(shellEl.querySelector('[data-company="c:orphaned"][data-company-open="0"]')).not.toBeNull();
    });


    it('a drag in flight draws an empty PINNED as the drop target', () => {
        const rows = baseRows().map((r) => ({ ...r, is_pinned: false }));
        const { shellEl } = expectParity(rows, { _dragging: true });
        expect(shellEl.querySelector('[data-group="pinned"]')).not.toBeNull();
    });

    it('no rows: the empty line when the listing answered, CANNOT DETERMINE when not', () => {
        expectParity([]);
        expectParity([], { _listing: { ok: false, reason: 'timeout', detail: 'no answer' } });
    });

    it('groups unreadable: pinned and projects only', () => {
        w.SessionSidebarGroupStore.apply({ status: 'unavailable', detail: 'down' });
        expectParity(baseRows());
    });

    it('a saved per-band order is honoured inside the band', () => {
        w.SessionSidebarStore.saveBandOrder('p:20', ['cloude_d', 'cloude_c']);
        const { shellEl } = expectParity(baseRows());
        const names = Array.from(shellEl.querySelectorAll('[data-group="p:20"] .session-sidebar-row'))
            .map((e) => e.getAttribute('data-name'));
        expect(names).toEqual(['cloude_d', 'cloude_c']);
    });

    it('every density draws the same rows (slice 3: the rows are Svelte)', () => {
        vi.useFakeTimers({ toFake: ['Date'] });
        vi.setSystemTime(new Date('2026-09-27T12:00:00Z'));
        const rich = baseRows().map((r, i) => ({
            ...r, last_work_at: new Date(Date.now() - (i + 1) * 3700 * 1000).toISOString(),
            created_at_epoch: Date.now() / 1000 - 90000, running_model: 'opus',
            running_model_tier: 5, running_model_effort: i % 2 ? 'max' : 'high', timers_live: i % 3 ? 1 : 0,
            workflow_active: i === 0, spectator_expires_at: i === 1 ? '2026-10-01T12:00:00Z' : null,
        }));
        try {
            Density.setMode('compact');
            const { shellEl } = expectParity(withLayouts(rich));
            expect(shellEl.getAttribute('data-density')).toBe('compact');
            expect(shellEl.querySelector('.session-sidebar-row-model__spark')).not.toBeNull();
        } finally {
            Density.setMode('compact');
            vi.useRealTimers();
        }
    });

    it('the role marks on the provider icon match the legacy markup, and null draws nothing', () => {
        const rows = baseRows().map((r, i) => ({
            ...r, task_lead: i === 0 || i === 2 ? true : i === 1 ? false : null, do_not_disturb: i === 1 || i === 2 ? true : null,
        }));
        const { shellEl } = expectParity(withLayouts(rows));
        expect(shellEl.querySelectorAll('.session-sidebar-row-provider__lead').length).toBeGreaterThan(0);
        expect(shellEl.querySelector('.session-sidebar-row-provider[data-dnd], .session-sidebar-row-provider__dnd')).toBeNull();
    });

    it('the shell updates rows IN PLACE (slice 4): a paint keeps each row element, and a changed field shows', () => {
        const el = document.getElementById('session-sidebar-list') as HTMLElement;
        const c = ctrl(el, baseRows());
        paintDrawer(c);
        const first = el.querySelector('.session-sidebar-row[data-name="cloude_b"]');
        paintDrawer(c);
        expect(el.querySelector('.session-sidebar-row[data-name="cloude_b"]')).toBe(first);
        c._rows = baseRows().map((r) => (r.name === 'cloude_b' ? { ...r, status: 'working' } : r));
        paintDrawer(c);
        const again = el.querySelector('.session-sidebar-row[data-name="cloude_b"]');
        expect(again).toBe(first);
        expect(again!.querySelector('.status-led')!.getAttribute('data-inner')).toBe('working');
        expect(c._lastSig).toBeNull();
    });

    it('a group rename repaints the heading (the legacy defect #726 slice 4 fixed in both renderers)', () => {
        const el = document.getElementById('session-sidebar-list') as HTMLElement;
        const before = paintBoth(baseRows());
        expect(canonicalDom(before.shellEl)).toContain('work stuff');
        w.SessionSidebarGroupStore.apply({
            status: 'ok',
            groups: [
                { group_uuid: 'g1', name: 'renamed', position: 0, members: ['cloude_b', 'cloude_c'], colour: 'violet', gradient: 'tide', animation: 'pulse' },
                { group_uuid: 'g2', name: 'empty one', position: 1, members: ['cloude_d'] },
            ],
        });
        paintDrawer(ctrl(el, baseRows()));
        expect(el.textContent).toContain('renamed');
        expect(el.textContent).not.toContain('work stuff');
        expectParity(baseRows());
    });

    it('NEGATIVE CONTROL: the comparison sees a real difference', () => {
        const { legacyEl, shellEl } = paintBoth(baseRows());
        shellEl.querySelector('[data-group="p:10"] .session-sidebar-group__header')!
            .setAttribute('aria-expanded', 'false');
        expect(canonicalDom(shellEl)).not.toBe(canonicalDom(legacyEl));
    });
});

describe('the retired switch (slice 6)', () => {
    it("the old per-device 'legacy' value is ignored: the shell still draws", () => {
        localStorage.setItem('carnivore.session.sidebar.shell', 'legacy');
        try {
            const { shellEl } = expectParity(baseRows());
            expect(shellEl.getAttribute(SHELL_ATTR)).toBe('svelte');
        } finally {
            localStorage.removeItem('carnivore.session.sidebar.shell');
        }
    });

    it('NEGATIVE CONTROL: a missing recording fails loudly rather than comparing against nothing', () => {
        expect(() => legacyAnswer('no-such-suite', 'x')).toThrow(/no legacy recording/);
    });
});
