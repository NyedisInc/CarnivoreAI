/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => {
    localStorage.setItem('claude_tunnel_token', 'an-access-token');
    return { posts: [] as Record<string, unknown>[] };
});

vi.mock('../../api/auth.svelte', async (importOriginal) => {
    const real = await importOriginal<typeof import('../../api/auth.svelte')>();
    return {
        ...real,
        authFetch: async (p: string, init: RequestInit = {}) => {
            const method = init.method ?? 'GET';
            if (p === '/files/open' && method === 'POST') {
                const body = JSON.parse(String(init.body));
                server.posts.push(body);
                return { file: { id: 'c1b2c3d4e5f60718', ...body, title: 'x', opened_at: 1, seq: 1 }, reused: false };
            }
            if (p === '/files/open') return { files: [] };
            if (p === '/sessions/list') return [{ session_row_id: 3, tmux_session: 'carnivore_a', session: { id: 'ses_1' } }];
            if (p === '/sessions/records') return [{ id: 3, session_uuid: 'u-1', tmux_name: 'carnivore_a' }];
            return {};
        },
    };
});

const STATUS = {
    state: 'ok', repo_root: '/r', working_dir_real: '/r/app', repo_name: 'r', branch: 'main',
    counts: { staged: 0, unstaged: 2, untracked: 0, conflicted: 0 }, truncated: 0,
    files: [
        { path: 'app/src/a.py', orig_path: null, index: ' ', worktree: 'M', kind: 'modified', submodule: false },
        { path: 'docs/b.md', orig_path: null, index: ' ', worktree: 'M', kind: 'modified', submodule: false },
    ],
};

vi.mock('../../api/session-git.svelte', () => ({
    sessionGit: () => ({ status: 'ok', data: STATUS, fetchedAt: 1, error: null, refresh: async () => {}, stop: () => {} }),
    releaseSessionGit: () => {},
}));

vi.mock('../../../lib/browser/screen-host', async (importOriginal) => {
    const real = await importOriginal<typeof import('../../../lib/browser/screen-host')>();
    return { ...real, openBrowser: () => true };
});

import Cell from './Cell.svelte';

async function settle(): Promise<void> {
    for (let i = 0; i < 12; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

describe('the changes widget opens through the files list', () => {
    let shown: ReturnType<typeof mount> | null = null;
    const legacy = { open: vi.fn(), openView: vi.fn() };

    beforeEach(() => {
        server.posts.length = 0;
        legacy.open.mockClear();
        legacy.openView.mockClear();
        (globalThis as { ConfigEditorModal?: unknown }).ConfigEditorModal = legacy;
        document.body.innerHTML = '<div id="host"></div>';
        shown = mount(Cell, { target: document.getElementById('host')!, props: { scope: { sessionId: 'ses_1' } } as never });
        flushSync();
    });

    afterEach(() => {
        if (shown) void unmount(shown);
        shown = null;
        delete (globalThis as { ConfigEditorModal?: unknown }).ConfigEditorModal;
    });

    test('"open" posts a file row named from the session folder, and never the old editor', async () => {
        document.querySelector<HTMLButtonElement>('[data-git-open="app/src/a.py"]')!.click();
        await settle();
        expect(server.posts).toEqual([{ root: 'workdir', path: 'src/a.py', session_uuid: 'u-1', kind: 'file' }]);
        expect(legacy.open).not.toHaveBeenCalled();
    });

    test('a click on the path posts a diff row by its repo path, and never the old editor', async () => {
        document.querySelector<HTMLButtonElement>('[data-git-diff="app/src/a.py"]')!.click();
        await settle();
        expect(server.posts).toEqual([{ root: 'workdir', path: 'app/src/a.py', session_uuid: 'u-1', kind: 'diff' }]);
        expect(legacy.openView).not.toHaveBeenCalled();
    });

    test('a changed file outside the session folder keeps the old editor', async () => {
        document.querySelector<HTMLButtonElement>('[data-git-open="docs/b.md"]')!.click();
        await settle();
        expect(server.posts).toEqual([]);
        expect(legacy.open).toHaveBeenCalledWith('workdir', 'docs/b.md', false, '/r', null);
    });
});
