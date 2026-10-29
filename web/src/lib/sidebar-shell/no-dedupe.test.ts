/** @vitest-environment jsdom */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadLegacyDrawer, paintDrawer, resetDrawer, type LegacyWindow } from './legacy-fixture';
import { unmountPanel } from '../mount';
import * as Density from '../drawer/density';
import * as Arrangement from '../drawer/arrangement';
import * as Store from '../drawer/store';
import * as GroupStore from '../drawer/group-store';
import { timerChip } from '../timers/timers';
import { sidebarShell } from './shell.svelte';

let w: LegacyWindow;
let listEl: HTMLElement;
let keptAwake = false;
let transport = 'connected';

function row(over: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        name: 'cloude_a', label: 'api', created_by_cloude: true, status: 'idle',
        unread: false, is_pinned: false, is_active: true, is_this_tab: false,
        project_id: 10, project_name: 'ProjectFoo', session_id: 'ses_a',
        session_uuid: 'su-a', kind: 'agent', agent_family: 'claude',
        created_at_epoch: 1790000000, ...over,
    };
}

const OTHER = { name: 'cloude_b', label: 'docs', created_by_cloude: true, status: 'idle',
    project_id: 10, project_name: 'ProjectFoo', session_id: 'ses_b', session_uuid: 'su-b', kind: 'agent' };

function paint(rows: Record<string, unknown>[]): string {
    paintDrawer({ listEl, _rows: rows, _listing: { ok: true }, _dragging: false });
    return listEl.innerHTML.replace(/<!--[^>]*-->/g, '');
}

function repaintWith(before: Record<string, unknown>, after: Record<string, unknown>,
    density = 'compact', between: () => void = () => {}, setup: () => void = () => {},
): { a: string; b: string; samePanel: boolean } {
    Density.setMode(density);
    setup();
    unmountPanel(listEl.id);
    const a = paint([before, OTHER]);
    const neighbour = () => listEl.querySelector('.session-sidebar-row[data-name="cloude_b"]');
    const first = neighbour();
    between();
    const b = paint([after, OTHER]);
    return { a, b, samePanel: first !== null && neighbour() === first };
}

beforeAll(() => {
    listEl = document.createElement('div');
    listEl.id = 'session-sidebar-list';
    listEl.className = 'session-sidebar-list';
    document.body.appendChild(listEl);
    w = loadLegacyDrawer();
    w.CloudeWeb = {
        layouts: { list: () => [], get: () => null, isUnavailable: () => false },
        timerChip,
        sidebarShell,
        autoSleep: { isKeptAwake: () => keptAwake },
    };
    w.SessionTransport = { stateFor: () => transport };
});

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-09-27T12:00:00Z'));
    resetDrawer();
    keptAwake = false;
    transport = 'connected';
});

const FIELDS: [string, Record<string, unknown>, Record<string, unknown>, string?][] = [
    ['label', {}, { label: 'renamed' }],
    ['status', {}, { status: 'working' }],
    ['status source (the tooltip)', { status: 'working', status_source: 'registry' }, { status: 'working', status_source: 'pane' }],
    ['unread', {}, { unread: true }],
    ['this tab', {}, { is_this_tab: true }],
    ['name', {}, { name: 'cloude_z' }],
    ['rename state', {}, { session_id: null }],
    ['origin badge (unknown to external)', { agent_family: 'shell', created_by_cloude: null }, { agent_family: 'shell', created_by_cloude: false }, 'cozy'],
    ['age', { agent_family: 'shell' }, { agent_family: 'shell', created_at_epoch: 1790000000 - 7 * 86400 }, 'detailed'],
    ['last-worked stamp', { last_work_at: '2026-09-27T11:58:00Z' }, { last_work_at: '2026-09-27T05:00:00Z' }, 'cozy'],
    ['resting hint', { status: 'idle' }, { status: 'idle', activity_hint: 'shell' }, 'detailed'],
    ['project name', {}, { project_name: 'Renamed' }],
    ['project id (re-filed)', { project_id: null, project_name: null }, { project_id: 10, project_name: 'ProjectFoo' }],
    ['running model', {}, { running_model: 'opus', running_model_tier: 5, running_model_effort: 'high' }, 'cozy'],
    ['share', {}, { spectator_expires_at: '2026-10-01T12:00:00Z' }],
    ['subagents', {}, { subagents_running: 2 }, 'cozy'],
    ['workflow colour', { subagents_running: 2 }, { subagents_running: 2, workflow_active: true }, 'detailed'],
    ['timers', {}, { timers_live: 1 }, 'cozy'],
    ['family', { agent_family: null }, { agent_family: 'claude' }],
    ['startup gate', { startup_gate: 'ready' }, { startup_gate: 'awaiting_startup_prompt' }],
];

describe('every field the retired repaint signature carried reaches the drawn row', () => {
    for (const [field, before, after, density] of FIELDS) {
        it(`${field}: changed alone, repainted in place, the drawn list differs`, () => {
            const { a, b, samePanel } = repaintWith(row(before), row(after), density || 'compact');
            expect(samePanel, 'the second paint must be an in-place update, not a remount').toBe(true);
            expect(b).not.toBe(a);
        });
    }

    it('pinned: a pin is the arrangement store\'s, not a listing field, and it moves the row', () => {
        const { a, b, samePanel } = repaintWith(row(), row(), 'compact',
            () => { Arrangement.togglePin('cloude_a', ['cloude_a', 'cloude_b']); });
        expect(samePanel).toBe(true);
        expect(b).not.toBe(a);
        expect(b).toContain('data-band="pinned"');
    });

    it('keep-awake: the cup is drawn from the auto-sleep store, which the listing never reports', () => {
        const { a, b, samePanel } = repaintWith(row(), row(), 'compact', () => { keptAwake = true; });
        expect(samePanel).toBe(true);
        expect(b).not.toBe(a);
        expect(b).toContain('data-keep-awake-session="cloude_a"');
    });

    it('transport: a dropped socket moves nothing the server reports, and still repaints', () => {
        const { a, b, samePanel } = repaintWith(row({ status: 'working' }), row({ status: 'working' }), 'compact',
            () => { transport = 'disconnected'; });
        expect(samePanel).toBe(true);
        expect(b).not.toBe(a);
    });

    it('density: switching mode repaints the same rows', () => {
        const { a, b, samePanel } = repaintWith(row(), row(), 'compact', () => { Density.setMode('detailed'); });
        expect(samePanel).toBe(true);
        expect(b).not.toBe(a);
    });

    it('position: a stored reorder repaints, with no row field moving', () => {
        const { a, b } = repaintWith(row(), row(), 'compact',
            () => { Store.save([], ['cloude_b', 'cloude_a']); });
        expect(b).not.toBe(a);
        expect(b.indexOf('data-name="cloude_b"')).toBeLessThan(b.indexOf('data-name="cloude_a"'));
    });

    it('a band reorder repaints the list, in the band\'s own order', () => {
        const { a, b } = repaintWith(row(), row(), 'compact',
            () => { Store.saveBandOrder('p:10', ['cloude_b', 'cloude_a']); });
        expect(b).not.toBe(a);
        expect(b.indexOf('data-name="cloude_b"')).toBeLessThan(b.indexOf('data-name="cloude_a"'));
    });

    it('changing only a group\'s icon repaints its heading', () => {
        const group = (icon: string | null) => GroupStore.apply({
            status: 'ok',
            groups: [{ group_uuid: 'g1', name: 'research', position: 0, members: ['cloude_a'],
                member_session_uuids: ['su-a'], colour: 'teal', gradient: null, animation: 'none', icon }],
        });
        const { a, b } = repaintWith(row(), row(), 'compact', () => { group('flask'); }, () => { group(null); });
        expect(b).not.toBe(a);
        expect(b).toContain('data-group-icon="flask"');
        expect(a).not.toContain('data-group-icon');
    });

    it('a fold repaints: the folded band draws no rows', () => {
        const { a, b } = repaintWith(row(), row(), 'compact', () => { Store.save([], ['cloude_a', 'cloude_b'], ['p:10']); });
        expect(b).not.toBe(a);
        expect(b).not.toContain('data-name="cloude_a"');
    });

    it('the drag flag repaints: the empty PINNED drop target appears', () => {
        Density.setMode('compact');
        unmountPanel(listEl.id);
        const draw = (dragging: boolean) => {
            paintDrawer({ listEl, _rows: [row(), OTHER], _listing: { ok: true }, _dragging: dragging });
            return listEl.innerHTML.replace(/<!--[^>]*-->/g, '');
        };
        const still = draw(false);
        const dragging = draw(true);
        expect(still).not.toContain('data-group="pinned"');
        expect(dragging).toContain('data-group="pinned"');
    });

    it('the listing verdict: a probe failure paints, and a different reason paints again', () => {
        Density.setMode('compact');
        unmountPanel(listEl.id);
        const draw = (listing: Record<string, unknown>) => {
            paintDrawer({ listEl, _rows: [], _listing: listing, _dragging: false });
            return listEl.innerHTML.replace(/<!--[^>]*-->/g, '');
        };
        const ok = draw({ ok: true });
        const timeout = draw({ ok: false, reason: 'timeout', detail: 'x' });
        const tmux = draw({ ok: false, reason: 'tmux_missing', detail: 'y' });
        expect(timeout).not.toBe(ok);
        expect(tmux).not.toBe(timeout);
    });

    it('held slots: a remembered session that is gone reaches the list element', () => {
        Store.save([], ['ghost', 'cloude_a', 'cloude_b']);
        unmountPanel(listEl.id);
        paint([row(), OTHER]);
        expect(listEl.getAttribute('data-order-missing')).toBe('1');
        Store.save([], ['cloude_a', 'cloude_b']);
        paint([row(), OTHER]);
        expect(listEl.getAttribute('data-order-missing')).toBe('0');
    });

    it('NEGATIVE CONTROL: a field no row renders leaves the DOM byte-identical', () => {
        const { a, b, samePanel } = repaintWith(row(), row({ created_at_epoch: 1, some_server_field: 'x' }));
        expect(samePanel).toBe(true);
        expect(b).toBe(a);
    });

    it('two fields the signature carried that no drawer row draws: is_active and pinned_theme', () => {
        const { a, b } = repaintWith(row(), row({ is_active: false, pinned_theme: 'ascii-amber' }));
        expect(b).toBe(a);
    });
});
