import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setCacheBackend, type CacheBackend } from '../../lib/data-cache/cache';
import { readTaskManagerSnapshot, saveTaskManagerSnapshot } from './task-manager-snapshot';
import type { HuddleItem, TaskManagerGroup } from './huddle-model';

const map = new Map<string, unknown>();
const memory: CacheBackend = {
    get: async (k) => map.get(k),
    put: async (k, v) => { map.set(k, v); },
    clear: async () => { map.clear(); },
};

beforeEach(() => {
    map.clear();
    setCacheBackend(memory);
    vi.useFakeTimers();
    vi.stubGlobal('localStorage', { getItem: () => `h.${btoa(JSON.stringify({ sub: 'alice' }))}.s` });
    vi.stubGlobal('location', { origin: 'https://mini.local:8000' });
});
afterEach(() => {
    vi.useRealTimers();
    setCacheBackend(null);
    vi.unstubAllGlobals();
});

describe('task manager snapshot', () => {
    it('saves open items only and reads them back', async () => {
        const item = (id: number, state: string): HuddleItem => ({ id, state, text: `t${id}` } as unknown as HuddleItem);
        const group = { list: '1', name: 'p', project_id: 1, revision: 1, items: [item(1, 'open'), item(2, 'done')] } as unknown as TaskManagerGroup;
        saveTaskManagerSnapshot('aggregate', [group]);
        await vi.runAllTimersAsync();
        const snap = await readTaskManagerSnapshot();
        expect(snap?.aggregate?.[0].items.map((i) => i.id)).toEqual([1]);
    });
});
