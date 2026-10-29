import { describe, expect, test } from 'vitest';

import { createManagerController } from './manager-controller.svelte';
import type { ManagerAdapter, ManagerItem } from './types';

const FALLBACK = 'could not read the list';

function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (error: unknown) => void;
    const promise = new Promise<T>((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
}

const ONE: ManagerItem = { id: 'p1', name: 'mark unread', enabled: false };

describe('load', () => {
    test('starts loading, then ready with the answer', async () => {
        const ctl = createManagerController({ list: async () => [ONE] }, FALLBACK);
        expect(ctl.status.kind).toBe('loading');
        await ctl.load();
        expect(ctl.status).toEqual({ kind: 'ready' });
        expect(ctl.items).toEqual([ONE]);
    });

    test('a rejection is an error carrying its own sentence, or the fallback', async () => {
        const said = createManagerController({ list: async () => Promise.reject(new Error('route missing')) }, FALLBACK);
        await said.load();
        expect(said.status).toEqual({ kind: 'error', message: 'route missing' });

        const bare = createManagerController({ list: async () => Promise.reject({ status: 500 }) }, FALLBACK);
        await bare.load();
        expect(bare.status).toEqual({ kind: 'error', message: FALLBACK });
    });

    test('the newest load wins over an older one that lands later', async () => {
        const first = deferred<ManagerItem[]>();
        const second = deferred<ManagerItem[]>();
        const answers = [first.promise, second.promise];
        const ctl = createManagerController({ list: () => answers.shift()! }, FALLBACK);
        const a = ctl.load();
        const b = ctl.load();
        second.resolve([{ id: 'new', name: 'new' }]);
        await b;
        first.resolve([{ id: 'old', name: 'old' }]);
        await a;
        expect(ctl.items.map((i) => i.id)).toEqual(['new']);
    });
});

describe('toggle', () => {
    test('no enable route: canToggle is false and toggle does nothing', async () => {
        const ctl = createManagerController({ list: async () => [ONE] }, FALLBACK);
        await ctl.load();
        expect(ctl.canToggle).toBe(false);
        await ctl.toggle('p1', true);
        expect(ctl.items).toEqual([ONE]);
        expect(ctl.toggles).toEqual({});
    });

    test('busy while in flight, then shows what the server returned', async () => {
        const reply = deferred<ManagerItem>();
        const calls: [string, boolean][] = [];
        const adapter: ManagerAdapter = {
            list: async () => [ONE],
            setEnabled: (id, on) => {
                calls.push([id, on]);
                return reply.promise;
            },
        };
        const ctl = createManagerController(adapter, FALLBACK);
        await ctl.load();
        const pending = ctl.toggle('p1', true);
        expect(ctl.toggles.p1).toEqual({ busy: true, error: null });
        await ctl.toggle('p1', true);
        expect(calls).toEqual([['p1', true]]);
        reply.resolve({ ...ONE, enabled: false, meta: 'v2' });
        await pending;
        expect(ctl.items[0]).toEqual({ ...ONE, enabled: false, meta: 'v2' });
        expect(ctl.toggles.p1).toEqual({ busy: false, error: null });
    });

    test('a rejected toggle keeps the old item and records the refusal', async () => {
        const ctl = createManagerController(
            { list: async () => [ONE], setEnabled: async () => Promise.reject(new Error('not allowed')) },
            FALLBACK,
        );
        await ctl.load();
        await ctl.toggle('p1', true);
        expect(ctl.items).toEqual([ONE]);
        expect(ctl.toggles.p1).toEqual({ busy: false, error: 'not allowed' });
    });
});

describe('export and remove (issue #888)', () => {
    test('with no routes there is nothing to offer and the calls are no-ops', async () => {
        const ctl = createManagerController({ list: async () => [ONE] }, FALLBACK);
        expect([ctl.canExport, ctl.canRemove]).toEqual([false, false]);
        await ctl.exportItem('p1');
        expect(await ctl.remove('p1')).toBe(false);
        expect(ctl.actions).toEqual({});
    });

    test('export hands the route answer to the download and records the file', async () => {
        const saved: Array<[string, unknown]> = [];
        const ctl = createManagerController(
            { list: async () => [ONE], exportItem: async (id) => ({ filename: `${id}.json`, document: { id } }) },
            FALLBACK,
            (filename, document) => {
                saved.push([filename, document]);
                return filename;
            },
        );
        await ctl.load();
        await ctl.exportItem('p1');
        expect(saved).toEqual([['p1.json', { id: 'p1' }]]);
        expect(ctl.actions.p1).toEqual({ busy: false, error: null, exported: 'p1.json' });
    });

    test('a refused export saves nothing and says why', async () => {
        const saved: string[] = [];
        const ctl = createManagerController(
            { list: async () => [ONE], exportItem: async () => Promise.reject(new Error('no such plugin')) },
            FALLBACK,
            (filename) => (saved.push(filename), filename),
        );
        await ctl.exportItem('p1');
        expect(saved).toEqual([]);
        expect(ctl.actions.p1).toEqual({ busy: false, error: 'no such plugin', exported: null });
    });

    test('remove calls its route, re-reads the list and names what went', async () => {
        let rows: ManagerItem[] = [ONE, { id: 'p2', name: 'two' }];
        let lists = 0;
        const ctl = createManagerController(
            {
                list: async () => (lists++, rows),
                remove: async (id) => {
                    rows = rows.filter((r) => r.id !== id);
                },
            },
            FALLBACK,
        );
        await ctl.load();
        expect(await ctl.remove('p1')).toBe(true);
        expect(lists).toBe(2);
        expect(ctl.items.map((i) => i.id)).toEqual(['p2']);
        expect(ctl.removed).toBe('mark unread');
    });

    test('a refused remove keeps the item, re-reads nothing and records the reason', async () => {
        let lists = 0;
        const ctl = createManagerController(
            { list: async () => (lists++, [ONE]), remove: async () => Promise.reject(new Error('in use')) },
            FALLBACK,
        );
        await ctl.load();
        expect(await ctl.remove('p1')).toBe(false);
        expect(lists).toBe(1);
        expect(ctl.items).toEqual([ONE]);
        expect(ctl.removed).toBeNull();
        expect(ctl.actions.p1?.error).toBe('in use');
    });

    test('a second remove while one is in flight is ignored', async () => {
        const reply = deferred<void>();
        const calls: string[] = [];
        const ctl = createManagerController(
            { list: async () => [ONE], remove: (id) => (calls.push(id), reply.promise) },
            FALLBACK,
        );
        await ctl.load();
        const first = ctl.remove('p1');
        expect(await ctl.remove('p1')).toBe(false);
        reply.resolve();
        await first;
        expect(calls).toEqual(['p1']);
    });
});
