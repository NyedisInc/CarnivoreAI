/** @vitest-environment jsdom */
import { beforeAll, describe, expect, it } from 'vitest';
import { unmountPanel } from '../mount';
import { loadRowInteractions, settle } from './row-interaction-fixture';
import { BOX, play, ROW, type Gestures } from './row-interaction-play';
import { sidebarShell } from './shell.svelte';

type Paint = 'in-place' | 'remount';

let paint: Paint = 'in-place';

let w: Record<string, any>;

beforeAll(() => {
    w = loadRowInteractions(sidebarShell);
});

async function liveUpdate(): Promise<void> {
    const ctrl = w.SessionSidebar;
    ctrl._rows = ctrl._rows.map((r: Record<string, unknown>) => {
        if (r.name === 'cloude_c') return { ...r, status: 'working' };
        if (r.name === 'cloude_b' || r.name === 'cloude_a') return { ...r, unread: true };
        return r;
    }).concat([{ ...ctrl._rows[2], name: 'cloude_n', label: 'n', session_id: 'ses_cloude_n', session_uuid: 'su-cloude_n' }]);
    if (paint === 'remount') unmountPanel('session-sidebar-list');
    ctrl.repaint();
    await settle();
}

async function remounting<T>(fn: () => Promise<T>): Promise<T> {
    paint = 'remount';
    try {
        return await fn();
    } finally {
        paint = 'in-place';
    }
}

interface RenameSeen { sameBox: boolean; value: string | null; caret: number | null; focused: boolean }

async function renameThroughUpdate(g: Gestures): Promise<RenameSeen> {
    await g.key(ROW('cloude_b'), 'F2');
    await g.type('half typed');
    const box = g.el(BOX) as HTMLInputElement;
    box.setSelectionRange(4, 4);
    await liveUpdate();
    const after = document.querySelector(`#session-sidebar-list ${BOX}`) as HTMLInputElement | null;
    return {
        sameBox: after === box,
        value: after ? after.value : null,
        caret: after ? after.selectionStart : null,
        focused: !!after && document.activeElement === after,
    };
}

describe('a rename in progress survives a live listing update', () => {
    it('the shell keeps the same box, its text, its caret and its focus; Enter then saves what was typed', async () => {
        let seen: RenameSeen | null = null;
        const run = await play(w, async (g) => {
            seen = await renameThroughUpdate(g);
            expect(g.el(ROW('cloude_c')).querySelector('.status-led')!.getAttribute('data-inner')).toBe('working');
            expect(g.has(ROW('cloude_n'))).toBe(true);
            await g.boxKey('Enter');
        });
        expect(seen).toEqual({ sameBox: true, value: 'half typed', caret: 4, focused: true });
        expect(run.events).toContainEqual(['api.renameSession', 'ses_cloude_b', 'half typed']);
    });

    it('NEGATIVE CONTROL: an update that remounts the list replaces the box', async () => {
        let seen: RenameSeen | null = null;
        await remounting(() => play(w, async (g) => { seen = await renameThroughUpdate(g); }));
        expect(seen!.sameBox).toBe(false);
    });
});

interface DragSeen { sameRow: boolean; held: boolean; order: string[] }

async function dragThroughUpdate(g: Gestures, update: boolean): Promise<DragSeen> {
    const hold = g.press(ROW('cloude_a'));
    hold.moveTo(1);
    const row = g.el('.session-sidebar-group[data-group="p:10"] .session-sidebar-row[data-name="cloude_a"]');
    const held = sidebarShell.isDragging();
    if (update) await liveUpdate();
    const after = document.querySelector('#session-sidebar-list .session-sidebar-group[data-group="p:10"] .session-sidebar-row[data-name="cloude_a"]');
    hold.moveTo(2);
    await hold.release();
    return {
        sameRow: after === row,
        held,
        order: (JSON.parse(JSON.stringify(w.SessionSidebarArrangement.current())).bands['p:10'] || []).slice(0, 3),
    };
}

describe('a drag in progress survives a live listing update', () => {
    it('the shell keeps the dragged row\'s element, the poll holds off, and the drop lands where it would have', async () => {
        const seen: Partial<Record<'with' | 'without', DragSeen>> = {};
        await play(w, async (g) => { seen.with = await dragThroughUpdate(g, true); });
        await play(w, async (g) => { seen.without = await dragThroughUpdate(g, false); });
        expect(seen.with!.sameRow).toBe(true);
        expect(seen.with!.held).toBe(true);
        expect(seen.with!.order).toEqual(seen.without!.order);
        expect(seen.with!.order).toEqual(['cloude_b', 'cloude_c', 'cloude_a']);
    });

    it('NEGATIVE CONTROL: an update that remounts the list replaces the dragged row\'s element', async () => {
        let seen: DragSeen | null = null;
        await remounting(() => play(w, async (g) => { seen = await dragThroughUpdate(g, true); }));
        expect(seen!.sameRow).toBe(false);
    });
});

describe('keyboard focus survives a live listing update', () => {
    async function focusThroughUpdate(): Promise<string> {
        let where = '';
        await play(w, async (g) => {
            await g.key(ROW('cloude_a'), 'ArrowDown');
            await liveUpdate();
            const active = document.activeElement as HTMLElement | null;
            where = active?.dataset?.name || active?.tagName || 'none';
        });
        return where;
    }

    it('the shell leaves focus on the row the user moved to', async () => {
        expect(await focusThroughUpdate()).toBe('cloude_b');
    });

    it('NEGATIVE CONTROL: a remount drops it', async () => {
        expect(await remounting(() => focusThroughUpdate())).toBe('BODY');
    });
});
