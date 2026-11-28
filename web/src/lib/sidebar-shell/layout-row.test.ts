/** @vitest-environment jsdom */
import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { loadLegacyDrawer, paintDrawer, type LegacyWindow } from './legacy-fixture';
import { setSleepingFolded } from '../drawer/sleep-fold.svelte';
import { unmountPanel } from '../mount';
import { sidebarShell } from './shell.svelte';

let w: LegacyWindow;
let listEl: HTMLElement;

function paint(): void {
    const base = [{
        name: 'cloude_a', label: 'a', created_by_cloude: true, status: 'idle', unread: false, is_pinned: false, project_id: 10,
        project_name: 'ProjectFoo', session_id: 'ses_a', session_uuid: 'su-a', kind: 'agent', agent_family: 'claude',
    }];
    const rows = base.concat(w.SessionSidebarLayouts.rows(base));
    const ctrl: Record<string, unknown> = { _rows: rows, _listing: { ok: true }, _dragging: false, _missing: [], listEl };
    ctrl.repaint = () => paintDrawer(ctrl);
    w.SessionSidebar = ctrl;
    unmountPanel(listEl.id);
    paintDrawer(ctrl);
}

const layoutRow = (): HTMLElement => listEl.querySelector('[data-group="layouts"] .session-sidebar-row[data-kind="layout"]') as HTMLElement;

beforeAll(() => {
    listEl = document.createElement('div');
    listEl.id = 'session-sidebar-list';
    listEl.className = 'session-sidebar-list';
    document.body.appendChild(listEl);
    w = loadLegacyDrawer();
    w.CloudeWeb = {
        layouts: {
            list: () => [{ layout_uuid: 'l1', name: 'focus', members: [{ session_uuid: 'su-a' }], colour: 'teal', gradient: null, animation: 'shimmer' }],
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
    w.SessionSidebarArrangement.toggleCollapsed('layout:l1');
});

describe('a saved Layout row', () => {
    it('wears the session row\'s outer shape, with every chip drawn by the row chip component', () => {
        paint();
        const row = layoutRow();
        expect(row.getAttribute('data-name')).toBe('layout:l1');
        expect(row.getAttribute('data-band')).toBe('layouts');
        expect(row.getAttribute('data-layout-colour')).toBe('teal');
        expect(row.getAttribute('draggable')).toBe('true');
        expect(row.getAttribute('role')).toBe('option');
        const main = row.querySelector(':scope > .session-sidebar-row-main')!;
        const classes = [...main.children].map((c) => c.className.split(' ')[0]);
        expect(classes).toEqual(expect.arrayContaining([
            'session-sidebar-layout__toggle', 'session-sidebar-row-provider', 'session-sidebar-row-name',
            'session-sidebar-row-subtitle', 'session-sidebar-row-pin',
        ]));
        expect(main.querySelector('.session-sidebar-row-provider')!.getAttribute('aria-hidden')).toBe('true');
        expect(main.querySelector('.session-sidebar-row-pin')!.getAttribute('data-pin-session')).toBe('layout:l1');
        expect(main.querySelector('.session-sidebar-row-pin')!.getAttribute('aria-pressed')).toBe('false');
        expect(main.querySelector('[data-row-menu="layout:l1"]')).not.toBeNull();
        expect(row.getAttribute('data-layout-anim')).toBe('shimmer');
        expect(main.querySelectorAll('.band-fx > i')).toHaveLength(0);
    });

    it('NEGATIVE CONTROL: a Layout with no color style paints no color attribute and no shimmer windows', () => {
        w.CloudeWeb.layouts.list = () => [{ layout_uuid: 'l1', name: 'focus', members: [], colour: null, gradient: null, animation: 'none' }];
        paint();
        expect(layoutRow().hasAttribute('data-layout-colour')).toBe(false);
        expect(layoutRow().querySelectorAll('.band-fx')).toHaveLength(0);
    });

    it('a typed search marks the text in the Layout\'s name, as it marks an agent\'s', () => {
        w.CloudeWeb.layouts.list = () => [{ layout_uuid: 'l1', name: 'focus', members: [], colour: null, gradient: null, animation: 'none' }];
        w.SessionSidebarSearch.setQuery('ocu');
        paint();
        const name = listEl.querySelector('.session-sidebar-row[data-kind="layout"] .session-sidebar-row-name')!;
        expect(name.querySelector('mark.sd-mark')!.textContent).toBe('ocu');
        expect(name.textContent).toBe('focus');
    });

    it('orders collapsed Layout icons [caret] [type icon] [status] [name] and folds sleeping members count-only by default (#3391)', () => {
        setSleepingFolded(true);
        const rowsData = [
            { name: 'cloude_live', label: 'live', created_by_cloude: true, status: 'working', unread: false, is_pinned: false, project_id: 10, project_name: 'ProjectFoo', session_id: 'ses_live', session_uuid: 'su-live', kind: 'agent', agent_family: 'claude' },
            { name: 'cloude_nap', label: 'nap', created_by_cloude: true, status: 'asleep', asleep: true, unread: false, is_pinned: false, project_id: 10, project_name: 'ProjectFoo', session_id: 'ses_nap', session_uuid: 'su-nap', kind: 'agent', agent_family: 'claude' },
        ];
        w.CloudeWeb.layouts.list = () => [{ layout_uuid: 'l1', name: 'focus', members: [{ session_uuid: 'su-live' }, { session_uuid: 'su-nap' }], colour: 'coral', gradient: null, animation: 'none' }];
        const paintWith = () => {
            const all = rowsData.concat(w.SessionSidebarLayouts.rows(rowsData));
            const ctrl: Record<string, unknown> = { _rows: all, _listing: { ok: true }, _dragging: false, _missing: [], listEl };
            ctrl.repaint = () => paintDrawer(ctrl);
            w.SessionSidebar = ctrl;
            unmountPanel(listEl.id);
            paintDrawer(ctrl);
        };
        paintWith();
        const members = listEl.querySelector('.session-sidebar-layout__members')!;
        expect(members.querySelector('[data-name="cloude_live"]')).not.toBeNull();
        expect(members.querySelector('[data-name="cloude_nap"]')).toBeNull();
        const fold = members.querySelector('.sb-sleep-fold')!;
        expect(fold).not.toBeNull();
        expect(fold.textContent!.trim()).toBe('1 asleep');
        expect(fold.querySelector('.sb-sleep-fold__names')).toBeNull();
        w.SessionSidebarArrangement.toggleCollapsed('layout:l1');
        paintWith();
        const main = layoutRow().querySelector(':scope > .session-sidebar-row-main')!;
        const leading = [...main.children].slice(0, 4).map((c) => c.className.split(' ')[0]);
        expect(leading).toEqual([
            'session-sidebar-layout__toggle',
            'session-sidebar-row-provider',
            'session-sidebar-group__project-led',
            'session-sidebar-row-name',
        ]);
    });

    it('toggles member fold when clicking the Layout grid icon or member count inside LAYOUTS', () => {
        w.CloudeWeb.layouts.list = () => [{ layout_uuid: 'l1', name: 'focus', members: [{ session_uuid: 'su-a' }], colour: 'teal', gradient: null, animation: 'none' }];
        paint();
        expect(listEl.querySelector('.session-sidebar-layout__members [data-name="cloude_a"]')).not.toBeNull();
        (layoutRow().querySelector('.session-sidebar-row-provider') as HTMLElement).click();
        expect(listEl.querySelector('.session-sidebar-layout__members [data-name="cloude_a"]')).toBeNull();
        (layoutRow().querySelector('.session-sidebar-row-subtitle') as HTMLElement).click();
        expect(listEl.querySelector('.session-sidebar-layout__members [data-name="cloude_a"]')).not.toBeNull();
    });
});
