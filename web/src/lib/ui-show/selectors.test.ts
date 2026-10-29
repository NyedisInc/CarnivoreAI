/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test, vi } from 'vitest';

const h = vi.hoisted(() => ({
    order: [] as string[],
    select: vi.fn((id: string) => { h.order.push(`select ${id}`); return true; }),
    navigate: vi.fn(async (_id: string, _tmux: string) => true),
    openLayout: vi.fn(async (_uuid: string) => {}),
    showTaskManager: vi.fn(async () => 'raised' as string),
    files: vi.fn(async () => { h.order.push('files'); }),
    browsers: vi.fn(async () => { h.order.push('browsers'); }),
    pages: vi.fn(async () => { h.order.push('pages'); }),
}));

vi.mock('../browser/select-push.svelte', () => ({ selectBrowserItem: h.select }));
vi.mock('../sessions-search/host', () => ({ browserSessionsSearchHost: () => ({ navigate: h.navigate }) }));
vi.mock('../../opscenter/layouts/page.svelte', () => ({ openLayout: h.openLayout }));
vi.mock('../task-manager-reveal/reveal', () => ({ showTaskManager: h.showTaskManager }));
vi.mock('../open-files/api.svelte', () => ({ openFiles: { refresh: h.files } }));
vi.mock('../browser/api.svelte', () => ({ browsers: { refresh: h.browsers } }));
vi.mock('../browser/pages.svelte', () => ({ openPages: { refresh: h.pages } }));

import { browserSelectors } from './selectors';

const ID = '0123456789abcdef';

beforeEach(() => {
    h.order.length = 0;
    vi.clearAllMocks();
});

describe('browserSelectors', () => {
    test('a file re-reads the files list, then selects its row', async () => {
        expect(await browserSelectors().file(ID)).toBe(true);
        expect(h.order).toEqual(['files', `select ${ID}`]);
    });

    test('a browser id re-reads both the browsers and the pages (it may be either), then selects', async () => {
        await browserSelectors().browser(ID);
        expect(h.order.slice(0, 2).sort()).toEqual(['browsers', 'pages']);
        expect(h.order[2]).toBe(`select ${ID}`);
    });

    test('a board is a page row: the pages list, then select', async () => {
        await browserSelectors().board(ID);
        expect(h.order).toEqual(['pages', `select ${ID}`]);
    });

    test('a failed list read still selects the row', async () => {
        vi.spyOn(console, 'warn').mockImplementation(() => {});
        h.files.mockRejectedValueOnce(new Error('offline'));
        expect(await browserSelectors().file(ID)).toBe(true);
        expect(h.select).toHaveBeenCalledWith(ID);
    });

    test('a session goes through the drawer switch, a layout through openLayout, the Task Manager through showTaskManager', async () => {
        const s = browserSelectors();
        expect(await s.session('ses_1', 'carnivore_a')).toBe(true);
        expect(h.navigate).toHaveBeenCalledWith('ses_1', 'carnivore_a');
        expect(await s.layout('5f0c')).toBe(true);
        expect(h.openLayout).toHaveBeenCalledWith('5f0c');
        expect(await s.taskManager()).toBe(true);
        h.showTaskManager.mockResolvedValueOnce('missing');
        expect(await s.taskManager()).toBe(false);
    });
});
