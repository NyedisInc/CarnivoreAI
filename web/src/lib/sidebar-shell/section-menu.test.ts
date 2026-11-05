/** @vitest-environment jsdom */
import { beforeAll, describe, expect, it, vi } from 'vitest';

const editor = vi.hoisted(() => ({ canEdit: false, active: false, toggle: vi.fn(async () => undefined) }));
vi.mock('../../opscenter/layout-editor/empty-space-menu.svelte', async (orig) => ({
    ...(await orig<typeof import('../../opscenter/layout-editor/empty-space-menu.svelte')>()), canOpen: () => editor.canEdit,
}));
vi.mock('../../opscenter/layout-editor/editor.svelte', async (orig) => {
    const real = await orig<typeof import('../../opscenter/layout-editor/editor.svelte')>();
    return { ...real, layoutEditor: { get active() { return editor.active; } }, toggleLayoutEditor: editor.toggle };
});
import { loadShell, play, settle, TOGGLE } from './interaction-play';
import type { Gestures } from './interaction-play';

beforeAll(() => { loadShell(); });

const toggleOf = (key: string): Element | null => document.querySelector(TOGGLE(key));

describe('the section heading menu (right-click and Shift+F10 only, no kebab; issue #1785, Q14)', () => {
    async function rightClick(g: Gestures, key: string): Promise<boolean> {
        const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 30, clientY: 40 });
        g.el(TOGGLE(key)).dispatchEvent(event);
        await settle();
        return event.defaultPrevented;
    }

    async function shiftF10(g: Gestures, key: string): Promise<void> {
        g.el(TOGGLE(key)).dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true }));
        await settle();
    }

    const drawnOrder = (): string[] => Array.from(document.querySelectorAll('#session-sidebar-list [data-section]')).map((el) => el.getAttribute('data-section') ?? '');

    it('a section heading draws no kebab, and a right-click opens fold, fold everything inside, both moves and edit layout', async () => {
        let prevented = false;
        const run = await play(async (_h, g) => {
            expect(document.querySelector('#session-sidebar-list [data-section] > .session-sidebar-group__headerrow .session-sidebar-group__menu')).toBeNull();
            prevented = await rightClick(g, 'terminals');
            g.snap('terminals');
        });
        expect(prevented).toBe(true);
        const items = run.snaps[0]!.menu!.split('|');
        expect(items.slice(0, 4).map((x) => x.split(' (')[0])).toEqual(['fold', 'fold everything inside', 'move section up', 'move section down']);
    });

    it('Shift+F10 on a section heading opens the same menu as a right-click', async () => {
        const run = await play(async (_h, g) => {
            await rightClick(g, 'terminals');
            g.snap('right-click');
            await g.key('Escape');
            await shiftF10(g, 'terminals');
            g.snap('shift-f10');
        });
        expect(run.snaps[1]!.menu).not.toBeNull();
        expect(run.snaps[1]!.menu).toBe(run.snaps[0]!.menu);
    });

    it('move section up is inert at the top with its reason; move section down is inert at the bottom', async () => {
        const run = await play(async (_h, g) => {
            const order = drawnOrder();
            await rightClick(g, order[0]!);
            g.snap('first');
            await g.key('Escape');
            await rightClick(g, order[order.length - 1]!);
            g.snap('last');
        });
        expect(run.snaps[0]!.menu).toContain('move section up (already first)');
        expect(run.snaps[0]!.menu).toContain('move section down');
        expect(run.snaps[1]!.menu).toContain('move section down (already last)');
        expect(run.snaps[1]!.menu!.split('|')).toContain('move section up');
    });

    it('picking move section down swaps the section with its neighbor through the stored order, the writer the drag uses', async () => {
        let before: string[] = [];
        let after: string[] = [];
        const run = await play(async (_h, g) => {
            before = drawnOrder();
            await rightClick(g, before[0]!);
            await g.pick('move section down');
            after = drawnOrder();
            g.snap('moved');
        });
        expect(after.slice(0, 2)).toEqual([before[1], before[0]]);
        expect(after.slice(2)).toEqual(before.slice(2));
        expect(run.snaps[0]!.focus).toContain(`${before[0]}`);
        expect(run.events).toContainEqual(['live', expect.stringContaining('moved')]);
    });

    it('fold folds the section and then reads unfold; an orphaned company keeps the browser menu', async () => {
        const run = await play(async (_h, g) => {
            await rightClick(g, 'terminals');
            await g.pick('fold');
            g.snap('folded');
            await rightClick(g, 'terminals');
            g.snap('reopened');
            await g.key('Escape');
        });
        expect(run.snaps[0]!.collapsed).toContain('terminals');
        expect(run.snaps[1]!.menu).toContain('unfold');
        let prevented = true;
        const nested = await play(async (_h, g) => {
            prevented = await rightClick(g, 'c:orphaned');
            g.snap('orphaned');
        });
        expect(prevented).toBe(false);
        expect(nested.snaps[0]!.menu).toBeNull();
    });

    it('BROWSERS also offers new browser; TERMINALS does not', async () => {
        const run = await play(async (_h, g) => {
            await rightClick(g, 'browsers');
            g.snap('browsers');
            await g.key('Escape');
            await rightClick(g, 'terminals');
            g.snap('terminals');
        });
        expect(run.snaps[0]!.menu).toContain('new browser');
        expect(run.snaps[1]!.menu).not.toContain('new browser');
    });

    it('focus returns to the heading toggle after Escape, however the menu was opened', async () => {
        await play(async (_h, g) => {
            await shiftF10(g, 'terminals');
            await g.key('Escape');
            expect(document.activeElement, 'Shift+F10 then Escape').toBe(toggleOf('terminals'));
            (document.activeElement as HTMLElement | null)?.blur();
            await rightClick(g, 'terminals');
            await g.key('Escape');
            expect(document.activeElement, 'right-click then Escape').toBe(toggleOf('terminals'));
        });
    });

    it('focus returns to the heading toggle after a pick that stays on the heading (fold)', async () => {
        await play(async (_h, g) => {
            await shiftF10(g, 'terminals');
            await g.pick('fold');
            expect(document.activeElement, 'Shift+F10 then fold').toBe(toggleOf('terminals'));
        });
    });

    it('a second menu opened in the same task keeps focus; the first one\'s deferred restore does not steal it', async () => {
        const run = await play(async (_h, g) => {
            g.el(TOGGLE('terminals')).dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true }));
            g.el(TOGGLE('browsers')).dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 5, clientY: 5 }));
            await settle();
            g.snap('browsers');
        });
        expect(run.snaps[0]!.menu).toContain('new browser');
        expect(run.snaps[0]!.focus.startsWith('item:')).toBe(true);
    });

    it('fold everything inside reads unfold everything inside while the heading is folded', async () => {
        const run = await play(async (_h, g) => {
            await rightClick(g, 'terminals');
            g.snap('open');
            await g.pick('fold');
            await rightClick(g, 'terminals');
            g.snap('folded');
            await g.key('Escape');
        });
        expect(run.snaps[0]!.menu!.split('|')).toContain('fold everything inside');
        expect(run.snaps[1]!.menu!.split('|')).toContain('unfold everything inside');
        expect(run.snaps[1]!.menu!.split('|')).not.toContain('fold everything inside');
    });

    it('edit layout is offered where the page can edit, reads done editing while editing, and runs the editor toggle', async () => {
        editor.canEdit = true;
        try {
            const run = await play(async (_h, g) => {
                await rightClick(g, 'terminals');
                g.snap('can edit');
                await g.pick('edit layout');
                editor.active = true;
                await rightClick(g, 'terminals');
                g.snap('editing');
                await g.key('Escape');
            });
            expect(run.snaps[0]!.menu!.split('|').at(-1)).toBe('edit layout');
            expect(editor.toggle).toHaveBeenCalledTimes(1);
            expect(run.snaps[1]!.menu!.split('|').at(-1)).toBe('done editing');
        } finally {
            editor.canEdit = false;
            editor.active = false;
        }
    });

    it('edit layout is left out where the page cannot edit', async () => {
        const run = await play(async (_h, g) => { await rightClick(g, 'terminals'); g.snap('open'); });
        expect(run.snaps[0]!.menu).not.toContain('edit layout');
    });
});
