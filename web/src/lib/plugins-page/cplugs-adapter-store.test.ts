/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { CplugRow } from './cplugs-adapter';

const mockState = vi.hoisted(() => ({
    fetches: [] as { path: string; method: string }[],
    rows: [] as CplugRow[],
    nextFetchImpl: null as null | ((path: string, init?: RequestInit) => Promise<unknown>),
    pushRegistrations: [] as { stopped: number }[],
}));

vi.mock('../../opscenter/api/auth.svelte', async (original) => {
    const mod = await original<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...mod,
        authFetch: vi.fn(async (path: string, init: RequestInit = {}) => {
            mockState.fetches.push({ path, method: init.method ?? 'GET' });
            if (mockState.nextFetchImpl) return mockState.nextFetchImpl(path, init);
            if (path.startsWith('/cplugs')) return { cplugs: mockState.rows };
            return {};
        }),
    };
});

vi.mock('../resource-push/boot', () => ({
    resourcePush: () => ({
        isLive: () => true,
        onChange: () => () => {},
        pushOrPoll: () => {
            const entry = { stopped: 0 };
            mockState.pushRegistrations.push(entry);
            return () => {
                entry.stopped += 1;
            };
        },
    }),
}));

vi.mock('../cplug-ui/surface.svelte', () => ({
    watchSurface: vi.fn(() => () => {}),
}));

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { ApiError, auth } from '../../opscenter/api/auth.svelte';
import { pluginsStore } from '../plugins/store.svelte';
import type { Translate } from '../sessions/types';
import { listCplugItems } from './cplugs-adapter';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (err: unknown) => void;
    const promise = new Promise<T>((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
}

function sampleRow(): CplugRow {
    return {
        id: 'huddle',
        name_key: 'cplug.huddle.name',
        description_key: 'cplug.huddle.description',
        version: '1.0.0',
        tier: 'builtin',
        enabled: true,
        state: 'active',
        permissions: { app: [] },
        grants: { app: [] },
        revision: 1,
    };
}

function agentPluginRow(): CplugRow {
    return {
        id: 'cc-lint',
        kind: 'agent-plugin',
        runtime: 'agent-plugin',
        name: 'CC Lint',
        version: '0.1.0',
        enabled: null,
        state: 'active',
        permissions: { app: [] },
        grants: { app: [] },
        revision: 1,
    };
}

beforeEach(() => {
    auth.state = 'signed-in';
    mockState.fetches = [];
    mockState.rows = [sampleRow()];
    mockState.nextFetchImpl = null;
    mockState.pushRegistrations = [];
    pluginsStore.resetForTest();
});

afterEach(() => {
    pluginsStore.resetForTest();
    auth.state = 'signed-out';
});

describe('listCplugItems -> pluginsStore consolidation', () => {
    test('populates pluginsStore.rows on default authFetch path and works while signed out', async () => {
        auth.state = 'signed-out';
        const items = await listCplugItems(t);

        expect(mockState.fetches).toEqual([{ path: '/cplugs?include_agent_plugins=true', method: 'GET' }]);
        expect(pluginsStore.read).toBe(true);
        expect(pluginsStore.rows).toHaveLength(1);
        expect(pluginsStore.rowOf('huddle')?.enabled).toBe(true);
        expect(items.map((item) => item.id)).toEqual(['cplug:huddle']);
    });

    test('coalesces concurrent listCplugItems(t) and pluginsStore.acquire({ includeAgentPlugins: true }) into 1 fetch', async () => {
        const gate = deferred<{ cplugs: CplugRow[] }>();
        mockState.nextFetchImpl = () => gate.promise;

        const listPromise = listCplugItems(t);
        const stop = pluginsStore.acquire({ includeAgentPlugins: true });

        expect(mockState.fetches).toEqual([{ path: '/cplugs?include_agent_plugins=true', method: 'GET' }]);

        gate.resolve({ cplugs: [sampleRow()] });
        const items = await listPromise;
        await vi.waitFor(() => expect(pluginsStore.read).toBe(true));

        expect(mockState.fetches).toHaveLength(1);
        expect(items.map((item) => item.cplugId)).toEqual(['huddle']);
        stop();
    });

    test('acquire({ includeAgentPlugins: true }) upgrades non-agent store rows once, then coalesces subsequent acquires', async () => {
        await pluginsStore.refresh({ allowSignedOut: true });
        expect(mockState.fetches).toEqual([{ path: '/cplugs', method: 'GET' }]);

        const gate = deferred<{ cplugs: CplugRow[] }>();
        mockState.nextFetchImpl = () => gate.promise;
        const stop = pluginsStore.acquire({ includeAgentPlugins: true });
        expect(mockState.fetches).toEqual([
            { path: '/cplugs', method: 'GET' },
            { path: '/cplugs?include_agent_plugins=true', method: 'GET' },
        ]);

        gate.resolve({ cplugs: [sampleRow()] });
        await vi.waitFor(() => expect(pluginsStore.loading).toBe(false));

        const gate2 = deferred<{ cplugs: CplugRow[] }>();
        mockState.nextFetchImpl = () => gate2.promise;
        const p2 = pluginsStore.refresh({ allowSignedOut: true, includeAgentPlugins: true });
        const stop2 = pluginsStore.acquire({ includeAgentPlugins: true });
        expect(mockState.fetches).toHaveLength(3);
        gate2.resolve({ cplugs: [sampleRow()] });
        expect(await p2).toBe(true);
        stop2();
        stop();
    });

    test('surfaces pluginsStore.error when refresh fails', async () => {
        mockState.nextFetchImpl = async () => {
            throw new ApiError('HTTP 503', 503, 'unavailable', {
                detail: { code: 'unavailable', detail: 'plugin host offline' },
            });
        };

        await expect(listCplugItems(t)).rejects.toThrow('plugin host offline');
        expect(pluginsStore.error).toBe('plugin host offline');
    });

    test('falls back to translated manager.error.title when refresh fails with pluginsStore.error === null', async () => {
        const refreshSpy = vi.spyOn(pluginsStore, 'refresh').mockResolvedValueOnce(false);
        expect(pluginsStore.error).toBeNull();

        await expect(listCplugItems(t)).rejects.toThrow(t('manager.error.title'));
        expect(t('manager.error.title')).toBe('could not read the list');
        refreshSpy.mockRestore();
    });

    test('active acquire({ includeAgentPlugins: true }) + listCplugItems(t, undefined, false) preserves agent-plugin rows without downgrade fetch and omits them from return', async () => {
        mockState.rows = [sampleRow(), agentPluginRow()];
        const stop = pluginsStore.acquire({ includeAgentPlugins: true });
        await vi.waitFor(() => expect(pluginsStore.read).toBe(true));

        const items = await listCplugItems(t, undefined, false);
        expect(mockState.fetches.some((f) => f.path === '/cplugs')).toBe(false);
        expect(pluginsStore.rows.map((row) => row.id)).toEqual(['huddle', 'cc-lint']);
        expect(items.map((item) => item.cplugId)).toEqual(['huddle']);
        stop();
    });

    test('concurrent in-flight acquire({ includeAgentPlugins: true }) + listCplugItems(t, undefined, false) coalesces to 1 fetch and omits agent-plugin items', async () => {
        const gate = deferred<{ cplugs: CplugRow[] }>();
        mockState.nextFetchImpl = () => gate.promise;

        const stop = pluginsStore.acquire({ includeAgentPlugins: true });
        const listPromise = listCplugItems(t, undefined, false);

        expect(mockState.fetches).toEqual([{ path: '/cplugs?include_agent_plugins=true', method: 'GET' }]);

        gate.resolve({ cplugs: [sampleRow(), agentPluginRow()] });
        const items = await listPromise;
        await vi.waitFor(() => expect(pluginsStore.loading).toBe(false));

        expect(mockState.fetches).toHaveLength(1);
        expect(pluginsStore.rows.map((row) => row.id)).toEqual(['huddle', 'cc-lint']);
        expect(items.map((item) => item.cplugId)).toEqual(['huddle']);
        stop();
    });

    test('keeps explicit injected fetcher isolated from pluginsStore', async () => {
        const customFetcher = vi.fn(async () => ({ cplugs: [sampleRow()] }));
        const items = await listCplugItems(t, customFetcher as never, false);

        expect(customFetcher).toHaveBeenCalledWith('/cplugs');
        expect(mockState.fetches).toHaveLength(0);
        expect(pluginsStore.read).toBe(false);
        expect(items.map((item) => item.cplugId)).toEqual(['huddle']);
    });
});
