/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { loadLegacyDrawer, type LegacyWindow } from './legacy-fixture';
import { rowMenuItems } from '../item-menu/menus/row';
import { contextFromTrigger } from '../item-menu/row-context';
import { rowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

let w: LegacyWindow;
let mounted: Array<{ app: unknown; target: HTMLElement }> = [];

beforeAll(() => { w = loadLegacyDrawer(); });

afterEach(() => {
    for (const m of mounted) { unmount(m.app as never); m.target.remove(); }
    mounted = [];
});

function row(overrides: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        name: 'cloude_api', status: 'working', created_by_cloude: true, is_active: true,
        is_this_tab: false, unread: false, session_id: null, agent_family: 'claude', ...overrides,
    };
}

function draw(r: Record<string, unknown>, band?: string): HTMLElement {
    const target = document.body.appendChild(document.createElement('div'));
    const app = mount(SessionRow, { target, props: { p: buildRowPlan(r as never, 'compact', band, null, rowHost()) as never } });
    flushSync();
    mounted.push({ app, target });
    return target.querySelector('.session-sidebar-row') as HTMLElement;
}

function offered(r: Record<string, unknown>): { inline: string[]; menu: string[]; all: string[] } {
    const el = draw(r);
    const inline = Array.from(el.querySelectorAll('[data-session-action]')).map((b) => b.getAttribute('data-session-action') as string);
    const trigger = el.querySelector('[data-row-menu]');
    const menu: string[] = trigger
        ? rowMenuItems(contextFromTrigger(trigger)!).map((i) => i.id)
        : [];
    return { inline, menu, all: [...inline, ...menu] };
}

describe('what a row offers', () => {
    it('a live row draws pin inline and everything else in ONE menu', () => {
        for (const status of ['working', 'idle', 'question', 'unknown']) {
            const el = draw(row({ status, is_pinned: true, unread: true }));
            expect(el.querySelectorAll('[data-row-menu]'), status).toHaveLength(1);
            expect(el.querySelectorAll('[data-pin-session]'), status).toHaveLength(1);
            expect(el.querySelectorAll('[data-mark-unread], [data-group-pick], [data-session-action]'), status).toHaveLength(0);
        }
    });

    it('a DEAD row keeps its inline restart and remove and draws no menu', () => {
        const el = draw(row({ status: 'dead', is_pinned: true }));
        expect(el.querySelector('[data-row-menu]')).toBeNull();
        const o = offered(row({ status: 'dead' }));
        expect([...o.inline].sort()).toEqual(['remove', 'restart']);
        expect(o.menu).toEqual([]);
    });

    it('every row offers exactly one DESTRUCTIVE control, inline or in its menu', () => {
        for (const status of ['working', 'dead', 'idle', 'question']) {
            const destructive = offered(row({ status })).all.filter((a) => a === 'close' || a === 'remove');
            expect(destructive, status).toHaveLength(1);
        }
    });

    it('a LIVE row offers restart through its menu, never inline; a dead row keeps it inline', () => {
        for (const status of ['working', 'working_subagent', 'question', 'notice', 'finished_unread', 'idle']) {
            const o = offered(row({ status }));
            expect(o.menu, status).toContain('restart');
            expect(o.inline, status).not.toContain('restart');
        }
        expect(offered(row({ status: 'dead' })).inline).toContain('restart');
    });

    it('an UNDETERMINED row we did not create is offered no restart anywhere', () => {
        for (const status of ['unknown', undefined, null, '']) {
            for (const created of [false, null]) {
                expect(offered(row({ status, created_by_cloude: created })).all, `${String(status)} ${String(created)}`).not.toContain('restart');
            }
        }
    });

    it('an UNDETERMINED row we created offers restart and close in its MENU only', () => {
        for (const status of ['unknown', undefined, null, '']) {
            const o = offered(row({ status, created_by_cloude: true }));
            expect(o.menu, String(status)).toEqual(expect.arrayContaining(['restart', 'close']));
            expect(o.inline, String(status)).not.toContain('restart');
        }
    });

    it('the trigger carries the row state its menu is built from', () => {
        const trigger = draw(row({ is_pinned: true, unread: true, status: 'working' })).querySelector('[data-row-menu]')!;
        expect(trigger.getAttribute('data-row-menu-status')).toBe('working');
        expect(trigger.getAttribute('data-row-menu-unread')).toBe('1');
    });
});

describe('what a row carries', () => {
    it('session_id is stamped only when the row has one', () => {
        expect(draw(row()).hasAttribute('data-session-id')).toBe(false);
        expect(draw(row({ session_id: 'sid-1' })).getAttribute('data-session-id')).toBe('sid-1');
    });

    it('a hostile session name or id never becomes an attribute or an element', () => {
        const el = draw(row({ name: 'evil" onclick="x', session_id: 'a" onload="y', label: '<script>x</script>' }));
        const handlers = Array.from(el.querySelectorAll('*')).concat(el)
            .flatMap((n) => Array.from(n.attributes).map((a) => a.name)).filter((n) => n.startsWith('on'));
        expect(handlers).toEqual([]);
        expect(el.querySelector('script')).toBeNull();
        expect(el.getAttribute('data-name')).toBe('evil" onclick="x');
    });

    it('the row renders the label, while data-name stays the tmux handle', () => {
        const handle = 'cloude_Media_Compression_v1_2_final_5';
        const label = 'Media Compression: v1.2 "final" $5';
        const el = draw(row({ name: handle, label, session_id: 'sess-1', status: 'idle' }));
        expect(el.querySelector('.session-sidebar-row-name')!.textContent).toBe(label);
        expect(el.getAttribute('data-name')).toBe(handle);
        const bare = draw(row({ name: handle, label: null, session_id: 'sess-1', status: 'idle' }));
        expect(bare.querySelector('.session-sidebar-row-name')!.textContent).toBe('Media Compression v1 2 final 5');
        expect(bare.getAttribute('data-name')).toBe(handle);
    });

    it('the row carries its rename state: a live id renames, unknown ownership is unknown', () => {
        expect(draw(row({ session_id: 'sess-1' })).getAttribute('data-rename-state')).toBe('renameable');
        expect(draw(row({ session_id: null, created_by_cloude: null })).getAttribute('data-rename-state')).toBe('unknown');
    });

    it('the row carries its work stamp: unrecorded with no last_work_at, recorded with one', () => {
        expect(draw(row({ status: 'idle', last_work_at: null })).getAttribute('data-work')).toBe('unrecorded');
        expect(draw(row({ status: 'idle', last_work_at: '2026-09-03T10:00:00Z' })).getAttribute('data-work')).toBe('recorded');
    });

    it('a row drawn under a band carries the band and a per-band id; with no band, neither', () => {
        const banded = draw(row(), 'pinned');
        expect(banded.getAttribute('data-band')).toBe('pinned');
        expect(banded.id).toBe('session-sidebar-row__cloude_api__pinned');
        const bare = draw(row());
        expect(bare.hasAttribute('data-band')).toBe(false);
        expect(bare.id).toBe('');
    });
});
