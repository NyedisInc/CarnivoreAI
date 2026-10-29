/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';

vi.mock('../browser/drawer-repaint', () => ({ repaintDrawer: () => {} }));

import type { OpenFileInfo } from './api.svelte';
import { anyDirty, bufferIds, bufferOf, dropBuffer, isDirty, loadBuffer, setCurrent } from './buffers.svelte';
import { reconcileBuffers, type OrphanDeps } from './orphans.svelte';
import { saveFile, type SaveDeps } from './save-flow';

const ROW: OpenFileInfo = {
    id: 'a1b2c3d4e5f60718', kind: 'file', root: 'workdir', path: 'src/main.py', session_uuid: 'u-1', title: 'main.py',
    opened_at: 1, seq: 1,
};
const OTHER: OpenFileInfo = { ...ROW, id: 'e1b2c3d4e5f60718', path: 'b.txt', title: 'b.txt' };

function loaded(id: string, text: string, sha: string): void {
    loadBuffer(id, { id, viewable: true, content: text, sha256: sha });
}

function deps(answer: boolean, reopenedId = 'f1b2c3d4e5f60718'): OrphanDeps & { asked: string[]; reopened: unknown[]; alerts: string[] } {
    const asked: string[] = [];
    const reopened: unknown[] = [];
    const alerts: string[] = [];
    return {
        asked, reopened, alerts,
        confirm: async (title) => { asked.push(title); return answer; },
        reopen: async (request) => { reopened.push(request); return { ...ROW, id: reopenedId }; },
        alert: (text) => { alerts.push(text); },
    };
}

afterEach(() => {
    for (const id of bufferIds()) dropBuffer(id);
});

describe('a row that leaves the list with unsaved edits', () => {
    test('asks, and keep reopens the file carrying the same edits and base', async () => {
        await reconcileBuffers([ROW, OTHER], deps(true));
        loaded(ROW.id, 'one\n', 's-1');
        setCurrent(ROW.id, 'mine\n');
        const d = deps(false);
        await reconcileBuffers([OTHER], d);
        expect(d.asked).toEqual(['discard unsaved edits?']);
        expect(d.reopened).toEqual([{ root: 'workdir', path: 'src/main.py', session_uuid: 'u-1', kind: 'file' }]);
        expect(bufferOf(ROW.id)).toBeNull();
        const moved = bufferOf('f1b2c3d4e5f60718');
        expect(moved?.current).toBe('mine\n');
        expect(moved?.sha256).toBe('s-1');
        expect(isDirty('f1b2c3d4e5f60718')).toBe(true);
    });

    test('discard drops the edits, so leaving the page no longer asks', async () => {
        await reconcileBuffers([ROW], deps(true));
        loaded(ROW.id, 'one\n', 's-1');
        setCurrent(ROW.id, 'mine\n');
        const d = deps(true);
        await reconcileBuffers([], d);
        expect(d.reopened).toEqual([]);
        expect(bufferOf(ROW.id)).toBeNull();
        expect(anyDirty()).toBe(false);
    });

    test('a clean orphan is forgotten with no question', async () => {
        await reconcileBuffers([ROW], deps(true));
        loaded(ROW.id, 'one\n', 's-1');
        const d = deps(true);
        await reconcileBuffers([], d);
        expect(d.asked).toEqual([]);
        expect(bufferOf(ROW.id)).toBeNull();
    });

    test('a reopen that fails keeps the edits and says so', async () => {
        await reconcileBuffers([ROW], deps(true));
        loaded(ROW.id, 'one\n', 's-1');
        setCurrent(ROW.id, 'mine\n');
        const d = deps(false);
        d.reopen = async () => { throw new Error('the session is gone'); };
        await reconcileBuffers([], d);
        expect(isDirty(ROW.id)).toBe(true);
        expect(d.alerts[0]).toContain('main.py');
    });
});

describe('a save that landed with no new revision', () => {
    function saveDeps(read: Record<string, unknown>): SaveDeps {
        return {
            confirm: async () => true,
            save: async (id) => ({ id, backed_up: true, is_executable: false, is_sensitive: false, sha256: null, mtime_ns: null }),
            read: async (id) => ({ id, viewable: true, ...read }),
        };
    }

    test('re-reads, and the read revision is the next base when it shows the saved text', async () => {
        loaded(ROW.id, 'one\n', 's-1');
        setCurrent(ROW.id, 'two\n');
        expect(await saveFile(ROW.id, ROW.path, false, saveDeps({ content: 'two\n', sha256: 's-2' }))).toEqual({ kind: 'saved', backedUp: true });
        expect(bufferOf(ROW.id)?.sha256).toBe('s-2');
        expect(isDirty(ROW.id)).toBe(false);
    });

    test('a read showing other text leaves no base, so the next save is refused, never a silent overwrite', async () => {
        loaded(ROW.id, 'one\n', 's-1');
        setCurrent(ROW.id, 'two\n');
        await saveFile(ROW.id, ROW.path, false, saveDeps({ content: 'theirs\n', sha256: 's-3' }));
        expect(bufferOf(ROW.id)?.sha256).toBe('');
    });
});
