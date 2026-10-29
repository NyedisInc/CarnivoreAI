/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadLegacyDrawer, paintDrawer, type LegacyWindow } from './legacy-fixture';
import { unmountPanel } from '../mount';
import { sidebarShell } from './shell.svelte';

vi.mock('./company-source.svelte', () => ({
    companySource: () => ({ companies: [{ id: 7, name: 'acme' }], companyOf: (id: string) => (String(id) === '1' ? 7 : null) }),
    watchCompanies: () => {},
}));

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const CSS = fs.readFileSync(path.join(ROOT, 'client', 'css', 'session-sidebar-band-structure.css'), 'utf8');

let w: LegacyWindow;
let listEl: HTMLElement;

function dividerSelector(): string {
    const m = CSS.match(/\n((?:[^\n{}]+::before,\n)*[^\n{}]+::before) \{\n\s*content: "";\n\s*position: absolute;/);
    expect(m, 'the divider rule').not.toBeNull();
    return m![1]!.split(',\n').map((s) => s.replace('::before', '').trim()).join(', ');
}

function session(name: string, over: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        name, label: name, created_by_cloude: true, status: 'idle', unread: false, is_pinned: false,
        session_id: `ses_${name}`, session_uuid: `su-${name}`, kind: 'agent', agent_family: 'claude', ...over,
    };
}

function bands(layouts: boolean): [string, boolean][] {
    w.CloudeWeb = {
        layouts: {
            list: () => (layouts ? [{ layout_uuid: 'l1', name: 'focus', members: [{ session_uuid: 'su-a' }], colour: null, gradient: null, animation: 'none' }] : []),
            get: () => null,
            isUnavailable: () => false,
        },
        sidebarShell,
    };
    w.SessionSidebarStore.save([], [], [], {}, {});
    w.SessionSidebarGroupStore.apply({ status: 'ok', groups: [{ group_uuid: 'g1', name: 'crew', position: 0, members: ['b'] }] });
    w.SessionSidebarArrangement.togglePin('a', ['a']);
    const base = [
        session('a', { project_id: 1, project_name: 'one' }), session('b', { project_id: 1, project_name: 'one' }),
        session('c', { project_id: 1, project_name: 'one' }), session('d', { project_id: 9, project_name: 'loose' }),
    ];
    const rows = base.concat(w.SessionSidebarLayouts.rows(base));
    const ctrl: Record<string, unknown> = { _rows: rows, _listing: { ok: true }, _lastSig: null, _dragging: false, _missing: [], listEl };
    ctrl.repaint = () => paintDrawer(ctrl);
    w.SessionSidebar = ctrl;
    unmountPanel(listEl.id);
    paintDrawer(ctrl);
    const sel = dividerSelector();
    return Array.from(listEl.querySelectorAll(':scope > .session-sidebar-group')).map((el) => {
        const label = el.classList.contains('session-sidebar-companies') ? 'companies' : (el.getAttribute('data-group') ?? '?');
        return [label, el.matches(sel)];
    });
}

beforeAll(() => {
    listEl = document.createElement('div');
    listEl.id = 'session-sidebar-list';
    listEl.className = 'session-sidebar-list';
    document.body.appendChild(listEl);
    w = loadLegacyDrawer();
});

beforeEach(() => {
    w.SessionSidebarSearch.setQuery('');
});

describe('drawer band dividers', () => {
    it('draws exactly one divider between each pair of different groupings, none for an absent band', () => {
        const withLayouts = bands(true);
        const names = withLayouts.map(([n]) => n);
        expect(names.slice(0, 2)).toEqual(['pinned', 'layouts']);
        const at = (n: string): [string, boolean] => withLayouts.find(([k]) => k === n)!;
        expect(at('pinned')[1], 'nothing above the first band').toBe(false);
        expect(at('layouts')[1]).toBe(true);
        const group = withLayouts.find(([k]) => k !== 'pinned' && k !== 'layouts' && k !== 'companies')!;
        expect(group[1], 'LAYOUTS to GROUPS').toBe(true);
        expect(names.indexOf('companies')).toBeGreaterThan(names.indexOf(group[0]));
        expect(at('companies')[1], 'GROUPS to COMPANIES').toBe(true);
        const after = withLayouts[names.indexOf('companies') + 1];
        if (after) expect(after[1], 'COMPANIES to the next band').toBe(true);

        const noLayouts = bands(false);
        expect(noLayouts.map(([n]) => n)).not.toContain('layouts');
        expect(noLayouts.filter(([n]) => n === 'pinned')[0]![1]).toBe(false);
        expect(noLayouts.filter(([, d]) => d).length).toBe(noLayouts.length - 1);
    });

    it('keeps the line between two companies lighter than a band divider and still inset', () => {
        const rule = CSS.slice(CSS.indexOf('.session-sidebar-company .session-sidebar-group + .session-sidebar-company::before {'));
        const body = rule.slice(0, rule.indexOf('}'));
        expect(body).toMatch(/left:\s*0;/);
        expect(body).toMatch(/right:\s*var\(--sidebar-tree-step\)/);
        expect(body).toMatch(/border-top-color:\s*var\(--sidebar-divider-minor\)/);
        expect(CSS).toMatch(/--sidebar-divider-minor:\s*color-mix\(in srgb, var\(--sidebar-divider\) \d+%, transparent\)/);
    });

    it('puts the folders-to-nested-company line at its own level, one tree step per depth', () => {
        const sel = CSS.match(/\n((?:[^\n{}]+::before,\n)*[^\n{}]*\.session-sidebar-company \.session-sidebar-group \+ \.session-sidebar-company::before) \{([^}]*)\}/);
        expect(sel, 'the nested company divider rule').not.toBeNull();
        expect(sel![2]).toMatch(/left:\s*0;/);
        expect(sel![2]).toMatch(/border-top-color:\s*var\(--sidebar-divider-minor\)/);
        document.body.insertAdjacentHTML('beforeend', '<div class="session-sidebar-company"><div class="session-sidebar-group"></div><div id="d1" class="session-sidebar-company"><div class="session-sidebar-group"></div><div id="d2" class="session-sidebar-company"></div></div></div>');
        const rule = sel![1]!.split(',\n').map((x) => x.replace('::before', '').trim());
        expect(document.getElementById('d1')!.matches(rule.join(', '))).toBe(true);
        expect(document.getElementById('d2')!.matches(rule.join(', '))).toBe(true);
    });
});
