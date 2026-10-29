/** @vitest-environment jsdom */
import { beforeAll, describe, expect, it } from 'vitest';
import { loadRowInteractions } from './row-interaction-fixture';
import { BOX, ROW, ROW_IN, same, snap } from './row-interaction-play';
import { sidebarShell } from './shell.svelte';

let w: Record<string, any>;

beforeAll(() => {
    w = loadRowInteractions(sidebarShell);
});

function bandOrder(arrangement: string, band: string): string[] {
    return (JSON.parse(arrangement).bands[band] || []) as string[];
}

describe('moving focus', () => {
    it('ArrowDown and ArrowUp move the one tab stop between rows; Home and End jump', async () => {
        const { svelte } = await same(w, async (g) => {
            await g.key(ROW('cloude_a'), 'ArrowDown');
            await g.key(ROW('cloude_b'), 'ArrowDown');
            await g.key(ROW('cloude_c'), 'ArrowUp');
            await g.key(ROW('cloude_b'), 'End');
            snap();
            await g.key(ROW('cloude_z'), 'Home');
        });
        expect(svelte.focus).toBe('DIV|session-sidebar-row|cloude_a');
        expect(svelte.snaps[0]!.match(/tabindex="0"/g)).toHaveLength(1);
    });

    it('a key on a nested control is that control\'s, not the row\'s', async () => {
        const { svelte } = await same(w, async (g) => {
            const pin = g.el(`${ROW('cloude_c')} [data-pin-session]`);
            pin.focus();
            pin.dispatchEvent(new KeyboardEvent('keydown', { key: 'p', bubbles: true, cancelable: true }));
        });
        expect(JSON.parse(svelte.arrangement).pinned).toEqual([]);
    });
});

describe('Alt+Arrow moves a row, and p pins it', () => {
    it('Alt+ArrowDown moves a row inside its band and keeps focus on it', async () => {
        const { svelte } = await same(w, async (g) => { await g.key(ROW('cloude_a'), 'ArrowDown', { altKey: true }); });
        expect(svelte.focus).toContain('cloude_a');
        expect(bandOrder(svelte.arrangement, 'p:10').slice(0, 2)).toEqual(['cloude_b', 'cloude_a']);
        expect(svelte.live).toBe('cloude_a moved to position 2 of 6');
    });

    it('held down: Alt+ArrowDown three times moves the row three slots', async () => {
        const { svelte } = await same(w, async (g) => {
            for (let i = 0; i < 3; i += 1) await g.key(ROW('cloude_a'), 'ArrowDown', { altKey: true });
        });
        expect(bandOrder(svelte.arrangement, 'p:10').indexOf('cloude_a')).toBe(3);
    });

    it('Alt+ArrowUp at the top of its band is refused, out loud', async () => {
        const { svelte } = await same(w, async (g) => { await g.key(ROW('cloude_a'), 'ArrowUp', { altKey: true }); });
        expect(svelte.live).toBe('cloude_a is already at the top of its group');
    });

    it('p pins the focused row; in PINNED, Alt+ArrowDown past the band edge unpins it and says so', async () => {
        const { svelte } = await same(w, async (g) => {
            await g.key(ROW('cloude_c'), 'p');
            snap();
            await g.key(ROW_IN('pinned', 'cloude_c'), 'ArrowDown', { altKey: true });
        });
        expect(svelte.snaps[0]).toContain('data-band="pinned"');
        expect(svelte.live).toMatch(/^cloude_c unpinned, now at position \d+ of \d+$/);
        expect(JSON.parse(svelte.arrangement).pinned).toEqual([]);
    });
});

describe('the inline rename', () => {
    it('F2 opens the box on the row (same DOM as the legacy box); Enter saves through the rename route', async () => {
        const { svelte } = await same(w, async (g) => {
            await g.key(ROW('cloude_b'), 'F2');
            snap();
            await g.type('renamed');
            await g.boxKey('Enter');
        });
        expect(svelte.snaps[0]).toContain('session-sidebar-rename-input');
        expect(svelte.snaps[0]).toContain('data-editing="1"');
        expect(svelte.events).toContainEqual(['api.renameSession', 'ses_cloude_b', 'renamed']);
        expect(svelte.live).toBe('renamed b to renamed');
    });

    it('Escape cancels; an unchanged name writes nothing', async () => {
        const { svelte } = await same(w, async (g) => {
            await g.key(ROW('cloude_b'), 'F2');
            await g.type('never saved');
            await g.boxKey('Escape');
            await g.key(ROW('cloude_b'), 'F2');
            await g.boxKey('Enter');
        });
        expect(svelte.events).toEqual([]);
        expect(svelte.live).toBe('rename canceled, b unchanged');
    });

    it('a name the label rule refuses stays in the box with the reason', async () => {
        const { svelte } = await same(w, async (g) => {
            await g.key(ROW('cloude_b'), 'F2');
            await g.type('x'.repeat(300));
            await g.boxKey('Enter');
            snap();
        });
        expect(svelte.events).toEqual([]);
        expect(svelte.snaps[0]).toContain('role="alert"');
    });

    it('a refusal from the server reopens the box with the typed text and the reason', async () => {
        const rename = w.API.renameSession;
        w.API.renameSession = async () => { throw new Error('name taken'); };
        try {
            const { svelte } = await same(w, async (g) => {
                await g.key(ROW('cloude_b'), 'F2');
                await g.type('taken');
                await g.boxKey('Enter');
                expect((g.el(BOX) as HTMLInputElement).value).toBe('taken');
                snap();
            });
            expect(svelte.snaps[0]).toContain('"rename failed: name taken"');
            expect(svelte.live).toBe('rename failed, b is unchanged: name taken');
        } finally {
            w.API.renameSession = rename;
        }
    });

    it('a row that cannot be renamed says why and opens nothing', async () => {
        const { svelte } = await same(w, async (g) => {
            w.SessionSidebar._rows = w.SessionSidebar._rows.map((r: Record<string, unknown>) =>
                (r.name === 'cloude_b' ? { ...r, session_id: null } : r));
            w.SessionSidebar.repaint();
            await g.key(ROW('cloude_b'), 'F2');
        });
        expect(svelte.dom).not.toContain('session-sidebar-rename-input');
        expect(svelte.live).not.toBe('');
    });
});
