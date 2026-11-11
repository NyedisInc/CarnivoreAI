import { describe, expect, test } from 'vitest';
import { createSideloadStore, type SideloadApi } from './sideload-store.svelte';
import type { SideloadStatus } from './sideload-switch';

const status = (enabled: boolean, developer_mode: boolean): SideloadStatus => ({ enabled, developer_mode, expires_at: null, hours: 12, items: [] });

function rig(initial: SideloadStatus) {
    const calls: string[] = [];
    let current = initial;
    const api: SideloadApi = {
        load: async () => { calls.push('load'); return current; },
        save: async (enabled) => { calls.push(`save:${enabled}`); current = status(enabled, current.developer_mode === true); return current; },
        developerMode: async (on) => { calls.push(`dev:${on}`); current = { ...current, developer_mode: on }; },
        folder: async () => ({}), git: async () => ({}), resync: async () => ({}), remove: async () => ({}),
    };
    return { store: createSideloadStore(api), calls };
}

describe('the one developer switch', () => {
    test('turning on writes developer mode first, then the timer', async () => {
        const { store, calls } = rig(status(false, false));
        await store.refresh();
        calls.length = 0;
        await store.setSwitch(true, 12);
        expect(calls).toEqual(['dev:true', 'save:true']);
    });
    test('developer mode already on is not written again', async () => {
        const { store, calls } = rig(status(false, true));
        await store.refresh();
        calls.length = 0;
        await store.setSwitch(true, null);
        expect(calls).toEqual(['save:true']);
    });
    test('turning off ends the timer, then developer mode, and reads the result', async () => {
        const { store, calls } = rig(status(true, true));
        await store.refresh();
        calls.length = 0;
        await store.setSwitch(false);
        expect(calls).toEqual(['save:false', 'dev:false', 'load']);
        expect(store.status?.developer_mode).toBe(false);
    });
});
