/** @vitest-environment jsdom */
import { beforeAll, expect, it } from 'vitest';
import { loadRowInteractions } from './row-interaction-fixture';
import { play } from './row-interaction-play';
import { sidebarShell } from './shell.svelte';

let w: Record<string, any>;

beforeAll(() => { w = loadRowInteractions(sidebarShell); });

function file(id: string, epoch: number): Record<string, unknown> {
    return {
        name: `browser:${id}`, kind: 'browser', browser_id: id, file: true, file_kind: 'file', path: `${id}.md`, label: `${id}.md`,
        dirty: false, url: null, status: 'file', created_at_epoch: epoch, last_work_at: null,
        project_id: null, project_name: null, working_dir: null,
    };
}

const A = '0000000000000001';
const B = '0000000000000002';
const C = '0000000000000003';
const rowsOf = (): Record<string, unknown>[] => [file(A, 1), file(B, 2), file(C, 3)];

function drawn(): string[] {
    return Array.from(document.querySelectorAll<HTMLElement>('.session-sidebar-row[data-band="files"]')).map((e) => e.dataset.name || '');
}

it('dragging a file row reorders the files band, and the order survives a listing refresh', async () => {
    let after: string[] = [];
    let refreshed: string[] = [];
    await play(w, async (g) => {
        const ctrl = w.SessionSidebar;
        ctrl._rows = rowsOf();
        ctrl.repaint();
        expect(drawn()).toEqual([`browser:${A}`, `browser:${B}`, `browser:${C}`]);
        const idx = Array.from(document.querySelectorAll('#session-sidebar-list .session-sidebar-row')).findIndex((e) => (e as HTMLElement).dataset.name === `browser:${C}`);
        await g.drag(`.session-sidebar-row[data-name="browser:${A}"]`, idx);
        after = drawn();
        ctrl._rows = rowsOf();
        ctrl.repaint();
        refreshed = drawn();
    });
    expect(after).toEqual([`browser:${B}`, `browser:${C}`, `browser:${A}`]);
    expect(refreshed).toEqual(after);
});
