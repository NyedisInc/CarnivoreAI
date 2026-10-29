/** @vitest-environment jsdom */
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { loadRowInteractions, rec } from './row-interaction-fixture';

const groupWrite = vi.hoisted(() => ({ commit: (..._a: unknown[]): unknown => undefined }));
vi.mock('./group-assign', async (orig) => ({
    ...(await orig<typeof import('./group-assign')>()), commitAssignment: (...a: unknown[]) => groupWrite.commit(...a),
}));
import { names, ROW, same, snap } from './row-interaction-play';
import { sidebarShell } from './shell.svelte';

let w: Record<string, any>;

beforeAll(() => {
    w = loadRowInteractions(sidebarShell);
    groupWrite.commit = rec('groups.commitAssignment', true);
});

const CREW = [{ group_uuid: 'g1', name: 'crew', position: 0, members: ['cloude_b'] }];

function drawn(): string {
    return Array.from(document.querySelectorAll<HTMLElement>('#session-sidebar-list .session-sidebar-row'))
        .map((e) => `${e.dataset.name}@${e.dataset.band}`).join(' ');
}

describe('pointer drag', () => {
    it('dragging a row by its body reorders it within the band', async () => {
        const { legacy, svelte } = await same(w, async (g) => { await g.drag(ROW('cloude_a'), 2); }, { differs: ['focus'] });
        expect(JSON.parse(svelte.arrangement).bands['p:10'].slice(0, 3)).toEqual(['cloude_b', 'cloude_c', 'cloude_a']);
        expect(svelte.live).toBe('cloude_a moved to position 3 of 6');
        expect(legacy.focus).toBe('BODY||');
        expect(svelte.focus).toBe('DIV|session-sidebar-row|cloude_a');
    });

    it('dragging a row into PINNED pins it there, and says so', async () => {
        const { svelte } = await same(w, async (g) => {
            await g.key(ROW('cloude_a'), 'p');
            await g.drag('.session-sidebar-group[data-group="p:10"] .session-sidebar-row[data-name="cloude_c"]', 0);
        }, { differs: ['focus'] });
        expect(JSON.parse(svelte.arrangement).pinned).toContain('cloude_c');
        expect(svelte.live).toMatch(/^cloude_c pinned, now at position \d+ of \d+$/);
    });

    it('dragging a row into a hand-made group moves it there and commits the group once, on release', async () => {
        const { svelte } = await same(w, async (g) => {
            snap();
            const hold = g.press(ROW('cloude_c'));
            hold.moveTo(0);
            expect(drawn()).toContain('cloude_c@g:g1');
            await hold.release();
        }, { groups: CREW, differs: ['focus'] });
        expect(svelte.events.filter((e) => (e as unknown[])[0] === 'groups.commitAssignment'))
            .toEqual([['groups.commitAssignment', 'cloude_c', 'g1']]);
    });

    it('the click that ends a drag belongs to the drag, and never opens the row', async () => {
        const { svelte } = await same(w, async (g) => {
            await g.drag(ROW('cloude_a'), 2);
            await g.click(ROW('cloude_a'));
            await g.click(ROW('cloude_b'));
        }, { differs: ['focus'] });
        expect(names(svelte).filter((n) => n === 'api.getSession')).toHaveLength(1);
        expect(svelte.events).toContainEqual(['api.getSession', 'ses_cloude_b', { includeScrollback: true, parallelHistory: true }]);
    });

    it('a press that starts on a nested control (the pin) never drags', async () => {
        const { svelte } = await same(w, async (g) => { await g.drag(`${ROW('cloude_a')} [data-pin-session]`, 3); });
        expect(JSON.parse(svelte.arrangement).bands).toEqual({});
        expect(svelte.live).toBe('');
    });

    it('under the slop a press is a click: nothing moves and the row opens', async () => {
        const { svelte } = await same(w, async (g) => {
            const hold = g.press(ROW('cloude_b'));
            await hold.release();
            await g.click(ROW('cloude_b'));
        });
        expect(names(svelte)).toEqual(['api.getSession', 'close-after-switch', 'app.returnToExistingTerminal']);
    });
});
