/** @vitest-environment jsdom */
import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { loadLegacyDrawer, paintDrawer, type LegacyWindow } from './legacy-fixture';
import { unmountPanel } from '../mount';
import { sidebarShell } from './shell.svelte';

let w: LegacyWindow;
let listEl: HTMLElement;

function session(pct: number | null): Record<string, unknown> {
    return {
        name: 'cloude_a', label: 'a', created_by_cloude: true, status: 'idle', unread: false,
        is_pinned: false, project_id: 10, project_name: 'ProjectFoo', session_id: 'ses_a',
        session_uuid: 'su-a', kind: 'agent', agent_family: 'claude', running_context_used_pct: pct,
    };
}

function paint(pct: number | null): void {
    const base = [session(pct)];
    const rows = base.concat(w.SessionSidebarLayouts.rows(base));
    const ctrl: Record<string, unknown> = {
        _rows: rows, _listing: { ok: true }, _lastSig: null, _dragging: false, _missing: [], listEl,
    };
    ctrl.repaint = () => paintDrawer(ctrl);
    w.SessionSidebar = ctrl;
    unmountPanel(listEl.id);
    paintDrawer(ctrl);
}

function gaugeUnder(scope: string): Element | null {
    const rowEl = listEl.querySelector(`${scope} .session-sidebar-row[data-name="cloude_a"]`);
    expect(rowEl).not.toBeNull();
    return rowEl!.querySelector('.session-sidebar-row-context');
}

beforeAll(() => {
    listEl = document.createElement('div');
    listEl.id = 'session-sidebar-list';
    listEl.className = 'session-sidebar-list';
    document.body.appendChild(listEl);
    w = loadLegacyDrawer();
    w.CloudeWeb = {
        layouts: {
            list: () => [{ layout_uuid: 'l1', name: 'focus', members: [{ session_uuid: 'su-a' }], colour: null, gradient: null, animation: 'none' }],
            get: () => null,
            isUnavailable: () => false,
        },
        sidebarShell,
    };
});

beforeEach(() => {
    w.SessionSidebarStore.save([], [], [], {}, {});
    w.SessionSidebarSearch.setQuery('');
    w.SessionSidebarGroupStore.apply({ status: 'ok', groups: [] });
    w.SessionSidebarArrangement.togglePin('cloude_a', ['cloude_a']);
    w.SessionSidebarArrangement.toggleCollapsed('layout:l1');
});

describe('a Layout member is the same session row as its pinned copy', () => {
    it('draws the context gauge in the LAYOUTS band as well as in PINNED', () => {
        paint(41);
        const pinned = gaugeUnder('[data-group="pinned"]');
        const member = gaugeUnder('[data-group="layouts"] [data-layout-members="l1"]');
        expect(pinned).not.toBeNull();
        expect(member).not.toBeNull();
        expect(member!.outerHTML).toBe(pinned!.outerHTML);
        const memberRow = listEl.querySelector('[data-layout-members="l1"] .session-sidebar-row');
        expect(memberRow!.getAttribute('data-band')).toBe('layout:l1');
        expect(sidebarShell.owns(memberRow)).toBe(true);
    });

    it('NEGATIVE CONTROL: an unmeasured context draws no gauge in either place', () => {
        paint(null);
        expect(gaugeUnder('[data-group="pinned"]')).toBeNull();
        expect(gaugeUnder('[data-group="layouts"] [data-layout-members="l1"]')).toBeNull();
    });

    it('the Layout row\'s own chevron folds its members away, not opens the Layout', () => {
        paint(41);
        const toggle = listEl.querySelector('[data-group="layouts"] [data-group-toggle="layout:l1"]') as HTMLElement;
        expect(toggle.getAttribute('aria-expanded')).toBe('true');
        toggle.click();
        const body = listEl.querySelector('[data-layout-members="l1"]');
        expect(body).not.toBeNull();
        expect(body!.children.length).toBe(0);
        expect(listEl.querySelector('[data-group-toggle="layout:l1"]')!.getAttribute('aria-expanded')).toBe('false');
    });
});
