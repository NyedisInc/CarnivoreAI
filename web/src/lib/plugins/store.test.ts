/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { CplugRow } from '../plugins-page/cplugs-adapter';

const mockState = vi.hoisted(() => ({
    fetches: [] as { path: string; method: string; body: unknown }[],
    rows: [] as CplugRow[],
    pushRegistrations: [] as { refresh: () => void; ms: number; topics: readonly string[]; stopped: number }[],
    changeListeners: new Set<(topics: string[]) => void>(),
    isLive: true,
    onChangeCalls: 0,
    nextFetchImpl: null as null | ((path: string, init?: RequestInit) => Promise<unknown>),
}));

vi.mock('../../opscenter/api/auth.svelte', async (original) => {
    const mod = await original<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...mod,
        authFetch: vi.fn(async (path: string, init: RequestInit = {}) => {
            const method = init.method ?? 'GET';
            const body = init.body ? JSON.parse(String(init.body)) : null;
            mockState.fetches.push({ path, method, body });
            if (mockState.nextFetchImpl) return mockState.nextFetchImpl(path, init);
            if (path === '/cplugs') return { cplugs: mockState.rows };
            return {};
        }),
    };
});

vi.mock('../resource-push/boot', () => ({
    resourcePush: () => ({
        isLive: () => mockState.isLive,
        onChange: (fn: (topics: string[]) => void) => {
            mockState.onChangeCalls += 1;
            mockState.changeListeners.add(fn);
            return () => {
                mockState.changeListeners.delete(fn);
            };
        },
        pushOrPoll: (refresh: () => void, ms: number, topics: readonly string[]) => {
            const entry = { refresh, ms, topics, stopped: 0 };
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

import { ApiError, auth } from '../../opscenter/api/auth.svelte';
import { cplugEnablement, followEnablement } from '../../plugins/host/enablement.svelte';
import { flowPrefs, followFlowPrefs } from '../../plugins/flow/flow-prefs.svelte';
import { followPrefs, prefsSettled, taskManagerPrefs } from '../../plugins/taskmanager/task-manager-prefs.svelte';
import { startOverlays, overlays } from '../cplug-ui/overlay-views.svelte';
import { syncBarIndicators, thirdPartyBarIndicators } from '../cplug-ui/bar-indicators.svelte';
import { pluginSettingsIndex } from '../settings-page/plugin-settings/plugin-settings-index.svelte';
import {
    CPLUGS_TOPIC,
    CPLUG_INSPECTOR_TOPIC,
    CPLUG_SLOTS_TOPIC,
    POLL_MS,
    errorMessageOf,
    pluginsStore,
    type CplugSlotsResponse,
    type GithubInstallResponse,
    type GithubPreviewResponse,
    type PluginInspectorSnapshot,
} from './store.svelte';
import { LIVENESS } from '../resource-push/store';

function sampleRows(): CplugRow[] {
    return [
        {
            id: 'huddle',
            name_key: 'cplug.huddle.name',
            version: '1.0.0',
            tier: 'builtin',
            kind: 'plugin',
            trust_tier: 'builtin',
            trust_badge: 'Built-in',
            scope: 'global',
            enabled: true,
            state: 'active',
            revision: 3,
            settings: { compact: true },
        },
        {
            id: 'gh-clock',
            runtime: 'sidecar',
            name: 'Clock',
            version: '0.2.0',
            kind: 'plugin',
            trust_tier: 'unverified_github',
            trust_badge: 'Unverified GitHub Repo',
            unverified: true,
            scope: 'global',
            enabled: true,
            state: 'active',
            install_key: 'inst-1',
            views: [{ name: 'hud', surfaces: ['overlay'] }],
            routes: ['tick'],
            declared_tools: ['clock_now'],
            runtime_paused: false,
            runtime_active: false,
            secrets_status: { API_KEY: { present: true, needs_reentry: false } },
            watchdog: {
                memory_limit_bytes: 134_217_728,
                rss_bytes: 1024,
                cpu_percent: 0.4,
                restart_count: 0,
                strikes: 0,
                crash_loop_paused: false,
            },
            dev_lease: {
                active: true,
                source_realpath: '/Users/dev/clock',
                baseline_sha: 'deadbeef',
                ttl_remaining_seconds: 120.5,
            },
            git_source: {
                url: 'https://github.com/acme/clock.git',
                ref: 'v0.2.0',
                subdir: '',
                commit: '0123456789abcdef',
                synced_at: '2026-11-24T00:00:00Z',
            },
        },
    ];
}

function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (err: unknown) => void;
    const promise = new Promise<T>((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
}

beforeEach(() => {
    auth.state = 'signed-in';
    mockState.fetches = [];
    mockState.rows = sampleRows();
    mockState.pushRegistrations = [];
    mockState.changeListeners.clear();
    mockState.isLive = true;
    mockState.onChangeCalls = 0;
    mockState.nextFetchImpl = null;
    pluginsStore.resetForTest();
});

afterEach(() => {
    pluginsStore.resetForTest();
    auth.state = 'signed-out';
});

describe('pluginsStore consolidation across all 4 legacy entry points', () => {
    test('starting followEnablement, startOverlays, thirdPartyBarIndicators, and pluginSettingsIndex.start registers 1 cplugs subscription and 1 single-flight fetch', async () => {
        const enablementChanged = vi.fn();

        followEnablement(enablementChanged);
        startOverlays();
        thirdPartyBarIndicators();
        const stopSettings = pluginSettingsIndex.start();

        expect(mockState.pushRegistrations).toHaveLength(1);
        expect(mockState.pushRegistrations[0]!.topics).toEqual([CPLUGS_TOPIC]);
        expect(mockState.pushRegistrations[0]!.ms).toBe(POLL_MS);
        expect(mockState.onChangeCalls).toBe(0);
        expect(mockState.fetches.filter((f) => f.path === '/cplugs')).toHaveLength(1);

        await vi.waitFor(() => expect(pluginsStore.read).toBe(true));

        expect(enablementChanged).toHaveBeenCalledTimes(1);
        expect(cplugEnablement.read).toBe(true);
        expect(cplugEnablement.enabled['huddle']).toBe(true);
        expect(cplugEnablement.settings['huddle']).toEqual({ compact: true });
        expect(overlays.list.map((o) => o.key)).toEqual(['gh-clock:inst-1:hud']);
        expect(pluginSettingsIndex.rows).toHaveLength(2);
        expect(pluginSettingsIndex.read).toBe(true);

        mockState.rows = [{ ...sampleRows()[0]!, enabled: false, state: 'disabled' }];
        mockState.pushRegistrations[0]!.refresh();

        await vi.waitFor(() => expect(cplugEnablement.enabled['huddle']).toBe(false));
        expect(mockState.fetches.filter((f) => f.path === '/cplugs')).toHaveLength(2);
        expect(overlays.list).toEqual([]);
        expect(pluginSettingsIndex.rows).toHaveLength(1);

        stopSettings();
        expect(mockState.pushRegistrations[0]!.stopped).toBe(0);
    });

    test('followEnablement, followFlowPrefs, and followPrefs consolidate onto 1 cplugs subscription and 1 single-flight fetch', async () => {
        mockState.rows = [
            {
                id: 'taskmanager',
                name_key: 'cplug.huddle.name',
                version: '1.0.0',
                tier: 'builtin',
                kind: 'plugin',
                enabled: true,
                state: 'active',
                revision: 5,
                settings: { hideCompleted: true },
            },
            {
                id: 'flow',
                name_key: 'cplug.flow.name',
                version: '1.0.0',
                tier: 'builtin',
                kind: 'plugin',
                enabled: true,
                state: 'active',
                revision: 2,
                settings: { showTab: true },
            },
        ];

        followEnablement();
        followFlowPrefs();
        followPrefs();

        expect(mockState.pushRegistrations).toHaveLength(1);
        expect(mockState.pushRegistrations[0]!.topics).toEqual([CPLUGS_TOPIC]);
        expect(mockState.onChangeCalls).toBe(0);
        expect(mockState.fetches.filter((f) => f.path === '/cplugs')).toHaveLength(1);
        expect(mockState.fetches.filter((f) => f.path === '/cplugs/flow' || f.path === '/cplugs/huddle')).toHaveLength(0);

        await prefsSettled();
        expect(flowPrefs.showTab).toBe(true);
        expect(taskManagerPrefs.hideCompleted).toBe(true);
        expect(taskManagerPrefs.revision).toBe(5);

        mockState.rows = [
            { ...mockState.rows[0]!, revision: 6, settings: { hideCompleted: false } },
            { ...mockState.rows[1]!, revision: 3, settings: { showTab: false } },
        ];
        mockState.pushRegistrations[0]!.refresh();

        await vi.waitFor(() => expect(flowPrefs.showTab).toBe(false));
        expect(taskManagerPrefs.hideCompleted).toBe(false);
        expect(taskManagerPrefs.revision).toBe(6);
        expect(mockState.fetches.filter((f) => f.path === '/cplugs')).toHaveLength(2);
    });
});

describe('acquire / release reference counting', () => {
    test('tears down pushOrPoll only when the last holder releases, and re-acquires cleanly', async () => {
        const r1 = pluginsStore.acquire();
        const r2 = pluginsStore.acquire();
        await vi.waitFor(() => expect(pluginsStore.read).toBe(true));

        expect(mockState.pushRegistrations).toHaveLength(1);
        r1();
        r1(); // idempotent
        expect(mockState.pushRegistrations[0]!.stopped).toBe(0);

        r2();
        expect(mockState.pushRegistrations[0]!.stopped).toBe(1);

        const r3 = pluginsStore.acquire();
        await vi.waitFor(() => expect(mockState.fetches).toHaveLength(2));
        expect(mockState.pushRegistrations).toHaveLength(2);
        r3();
        expect(mockState.pushRegistrations[1]!.stopped).toBe(1);
    });
});

describe('refresh single-flight, force, error handling, and resetForTest', () => {
    test('coalesces concurrent refresh() calls and forces a fresh read when force: true', async () => {
        const gate = deferred<{ cplugs: CplugRow[] }>();
        mockState.nextFetchImpl = () => gate.promise;

        const p1 = pluginsStore.refresh();
        const p2 = pluginsStore.refresh();
        expect(mockState.fetches).toHaveLength(1);

        const forced = pluginsStore.refresh({ force: true });
        mockState.nextFetchImpl = null;
        mockState.rows = [sampleRows()[0]!];
        gate.resolve({ cplugs: sampleRows() });
        expect(await p1).toBe(true);
        expect(await p2).toBe(true);
        expect(await forced).toBe(true);
        expect(mockState.fetches).toHaveLength(2);
        expect(pluginsStore.rows).toHaveLength(1);
    });

    test('preserves prior rows and read flag on error, and resetForTest clears all state', async () => {
        await pluginsStore.refresh();
        expect(pluginsStore.read).toBe(true);
        expect(pluginsStore.rows).toHaveLength(2);

        mockState.nextFetchImpl = async () => {
            throw new Error('network down');
        };
        expect(await pluginsStore.refresh({ force: true })).toBe(false);
        expect(pluginsStore.error).toBe('network down');
        expect(pluginsStore.read).toBe(true);
        expect(pluginsStore.rows).toHaveLength(2);

        const stop = pluginsStore.acquire();
        void stop;
        pluginsStore.resetForTest();
        expect(pluginsStore.rows).toEqual([]);
        expect(pluginsStore.read).toBe(false);
        expect(pluginsStore.error).toBeNull();
        expect(pluginsStore.enabled).toEqual({});
        expect(pluginsStore.settings).toEqual({});
        expect(mockState.pushRegistrations[0]!.stopped).toBe(1);
    });
});

describe('signed-out guard', () => {
    test('makes zero fetches and zero push subscriptions while signed out', async () => {
        auth.state = 'signed-out';

        expect(await pluginsStore.refresh()).toBe(false);
        const stop = pluginsStore.acquire();
        startOverlays();
        expect(thirdPartyBarIndicators()).toEqual([]);
        await syncBarIndicators();
        stop();

        expect(mockState.fetches).toHaveLength(0);
        expect(mockState.pushRegistrations).toHaveLength(0);
    });
});

describe('rowOf, items, and typed v3 endpoints', () => {
    test('maps v3 row metadata via rowOf and items(t)', async () => {
        await pluginsStore.refresh();
        expect(pluginsStore.rowOf('gh-clock')?.trust_tier).toBe('unverified_github');
        const mapped = pluginsStore.items((key) => key);
        const clock = mapped.find((item) => item.cplugId === 'gh-clock');
        expect(clock).toMatchObject({
            pluginKind: 'plugin',
            trustTier: 'unverified_github',
            trustBadge: 'Unverified GitHub Repo',
            scope: 'global',
            runtimePaused: false,
            runtimeActive: false,
            watchdog: {
                memory_limit_bytes: 134_217_728,
                rss_bytes: 1024,
                cpu_percent: 0.4,
                restart_count: 0,
                strikes: 0,
                crash_loop_paused: false,
            },
            devLease: {
                active: true,
                source_realpath: '/Users/dev/clock',
                baseline_sha: 'deadbeef',
                ttl_remaining_seconds: 120.5,
            },
            gitSource: {
                url: 'https://github.com/acme/clock.git',
                ref: 'v0.2.0',
                subdir: '',
                commit: '0123456789abcdef',
                synced_at: '2026-11-24T00:00:00Z',
            },
        });
    });

    test('previewGithub, installGithub, fetchInspector, pause/resume/restart, and updatePlugin hit v3 routes with exact backend wire shapes', async () => {
        const previewFixture: GithubPreviewResponse = {
            id: 'gh-clock',
            item_id: 'github/gh-clock',
            name: 'Clock',
            description: 'Clock plugin',
            version: '0.2.0',
            kind: 'cplug',
            trust_tier: 'unverified_github',
            trust_badge: 'Unverified GitHub Repo',
            unverified: true,
            code_sha256: 'sha-code-1',
            permissions: [
                {
                    name: 'network_hosts:api.github.com',
                    risk: 'medium',
                    reason: 'Check clock updates',
                    granted: false,
                    needs_tick: true,
                },
            ],
            risks: { 'network_hosts:api.github.com': 'medium' },
            warnings: [{ code: 'sends_transcripts', reads: 'sessions.read', host: 'api.github.com' }],
            consent_sheet: {
                id: 'gh-clock',
                version: '0.2.0',
                digest: 'sha-code-1',
                body_sha: 'body-sha-1',
                grants_sha: 'grants-sha-1',
            },
            secrets: [{ name: 'API_KEY', label: 'API Key', hosts: ['api.github.com'] }],
            scope: 'global',
            supported_scopes: ['global'],
            project_path: null,
            runtime_active: true,
            source: {
                url: 'https://github.com/acme/clock.git',
                ref: 'v0.2.0',
                commit: '0123456789abcdef',
                subdir: '',
            },
        };
        const installFixture: GithubInstallResponse = {
            id: 'gh-clock',
            item_id: 'github/gh-clock',
            install_key: 'inst-1',
            kind: 'cplug',
            trust_tier: 'unverified_github',
            trust_badge: 'Unverified GitHub Repo',
            unverified: true,
            code_sha256: 'sha-code-1',
            scope: 'global',
            supported_scopes: ['global'],
            enabled: true,
            runtime_active: true,
            secrets_status: { API_KEY: { present: true, needs_reentry: false } },
            git: {
                url: 'https://github.com/acme/clock.git',
                ref: 'v0.2.0',
                subdir: '',
                commit: '0123456789abcdef',
                synced_at: '2026-11-24T00:00:00Z',
            },
        };
        const inspectorFixture: PluginInspectorSnapshot = {
            cplug_id: 'gh-clock',
            plugin_id: 'gh-clock',
            install_key: 'inst-1',
            kind: 'plugin',
            trust_tier: 'unverified_github',
            trust_badge: 'Unverified GitHub Repo',
            unverified: true,
            state: 'running',
            paused: false,
            watchdog: {
                pid: 4242,
                memory_limit_bytes: 134_217_728,
                rss_bytes: 2048,
                cpu_seconds: 0.4,
                cpu_percent: 1.5,
                disk_bytes: 512,
                disk_quota_bytes: 67_108_864,
                disk_files: 2,
                disk_quota_files: 1024,
                restart_count: 0,
                strikes: 0,
                crash_loop_paused: false,
                uptime_seconds: 42.5,
            },
            surfaces: {
                widget: true,
                panel: false,
                bar: true,
                settings: true,
                views: ['hud'],
                absent_surfaces: [],
                tools: ['clock_now'],
                routes: ['tick'],
                timers: [],
            },
            dev_lease: {
                active: true,
                source_realpath: '/Users/dev/clock',
                baseline_sha: 'deadbeef',
                ttl_remaining_seconds: 120.0,
            },
            secrets_status: { API_KEY: { present: true, needs_reentry: false } },
            rpc_trace: [
                {
                    ts: 1700000000,
                    source: 'cli_sock',
                    method: 'http.fetch',
                    target: 'https://api.github.com/zen',
                    latency_ms: 12.3,
                    ok: true,
                    error_code: '',
                    error_message: '',
                },
            ],
            capability_checks: [
                {
                    ts: 1700000000,
                    permission: 'network_hosts:api.github.com',
                    allowed: true,
                    reason: 'granted',
                    caller: 'rpc',
                },
            ],
            logs_tail: [
                { source: 'stderr', line: 'ready' },
                { seq: 1, ts: 1700000001, source: 'reloaded', payload: { ms: 42 } },
            ],
        };

        mockState.nextFetchImpl = async (path) => {
            if (path === '/cplug-owner/github/preview') return previewFixture;
            if (path === '/cplug-owner/github/install') return installFixture;
            if (path === '/cplugs/gh-clock/inspector') return inspectorFixture;
            if (path === '/cplugs') return { cplugs: mockState.rows };
            return { id: 'gh-clock', paused: false, runtime_paused: false, state: 'running' };
        };

        const preview = await pluginsStore.previewGithub({ source: 'acme/clock', ref: 'v0.2.0', subdir: '' });
        expect(preview.permissions?.[0]?.needs_tick).toBe(true);
        expect(preview.secrets?.[0]).toEqual({ name: 'API_KEY', label: 'API Key', hosts: ['api.github.com'] });
        expect(preview.supported_scopes).toEqual(['global']);
        expect(preview.source?.commit).toBe('0123456789abcdef');
        expect(mockState.fetches.at(-1)).toEqual({
            path: '/cplug-owner/github/preview',
            method: 'POST',
            body: { source: 'acme/clock', ref: 'v0.2.0', subdir: '' },
        });

        const installed = await pluginsStore.installGithub({
            source: 'acme/clock',
            ref: 'v0.2.0',
            subdir: '',
            enable: true,
            activate_runtime: true,
            secrets: { API_KEY: 'secret-val' },
            consent: {
                digest: 'sha-code-1',
                body_sha: 'body-sha-1',
                grants_sha: 'grants-sha-1',
                ticks: ['network_hosts:api.github.com'],
            },
        });
        expect(installed.install_key).toBe('inst-1');
        expect(installed.secrets_status?.API_KEY?.present).toBe(true);
        expect(mockState.fetches.slice(-2)).toEqual([
            {
                path: '/cplug-owner/github/install',
                method: 'POST',
                body: {
                    source: 'acme/clock',
                    ref: 'v0.2.0',
                    subdir: '',
                    enable: true,
                    activate_runtime: true,
                    secrets: { API_KEY: 'secret-val' },
                    consent: {
                        digest: 'sha-code-1',
                        body_sha: 'body-sha-1',
                        grants_sha: 'grants-sha-1',
                        ticks: ['network_hosts:api.github.com'],
                    },
                },
            },
            { path: '/cplugs', method: 'GET', body: null },
        ]);

        const snapshot = await pluginsStore.fetchInspector('gh-clock');
        expect(snapshot.surfaces?.views).toEqual(['hud']);
        expect(snapshot.surfaces?.widget).toBe(true);
        expect(snapshot.watchdog.memory_limit_bytes).toBe(134_217_728);
        expect(snapshot.watchdog.cpu_percent).toBe(1.5);
        expect(snapshot.dev_lease?.ttl_remaining_seconds).toBe(120.0);
        expect(snapshot.logs_tail[0]).toEqual({ source: 'stderr', line: 'ready' });
        expect(snapshot.secrets_status?.API_KEY?.present).toBe(true);
        expect(mockState.fetches.at(-1)).toEqual({
            path: '/cplugs/gh-clock/inspector',
            method: 'GET',
            body: null,
        });

        await pluginsStore.pausePlugin('gh-clock');
        expect(mockState.fetches.slice(-3).map((f) => `${f.method} ${f.path}`)).toEqual([
            'POST /cplugs/gh-clock/pause',
            'GET /cplugs',
            'GET /cplugs/gh-clock/inspector',
        ]);

        await pluginsStore.resumePlugin('gh-clock');
        expect(mockState.fetches.slice(-3).map((f) => `${f.method} ${f.path}`)).toEqual([
            'POST /cplugs/gh-clock/resume',
            'GET /cplugs',
            'GET /cplugs/gh-clock/inspector',
        ]);

        await pluginsStore.restartPlugin('gh-clock');
        expect(mockState.fetches.slice(-3).map((f) => `${f.method} ${f.path}`)).toEqual([
            'POST /cplugs/gh-clock/restart',
            'GET /cplugs',
            'GET /cplugs/gh-clock/inspector',
        ]);

        mockState.nextFetchImpl = async (path, init) => {
            if (path === '/cplugs/gh-clock' && (!init?.method || init.method === 'GET')) {
                return { id: 'gh-clock', revision: 7, enabled: false, state: 'disabled' };
            }
            if (path === '/cplugs') return { cplugs: mockState.rows };
            return { id: 'gh-clock', revision: 8, enabled: true, state: 'active' };
        };
        await pluginsStore.updatePlugin('gh-clock', {
            enabled: true,
            activate_runtime: true,
            secrets: { API_KEY: 'updated' },
        });
        expect(mockState.fetches.slice(-3)).toEqual([
            { path: '/cplugs/gh-clock', method: 'GET', body: null },
            {
                path: '/cplugs/gh-clock',
                method: 'PUT',
                body: {
                    revision: 7,
                    enabled: true,
                    activate_runtime: true,
                    secrets: { API_KEY: 'updated' },
                },
            },
            { path: '/cplugs', method: 'GET', body: null },
        ]);
    });

    test('parses detail.detail and detail.message envelopes cleanly on refresh and v3 actions', async () => {
        expect(errorMessageOf({ detail: { code: 'cplug_unknown', detail: 'no plugin missing' } })).toBe('no plugin missing');
        expect(errorMessageOf({ detail: { code: 'cplug_unknown', message: 'unknown plugin: missing' } })).toBe('unknown plugin: missing');
        expect(
            errorMessageOf(new ApiError('fallback', 404, 'cplug_unknown', { detail: { code: 'cplug_unknown', message: 'unknown plugin: missing' } })),
        ).toBe('unknown plugin: missing');
        expect(
            errorMessageOf(new ApiError('fallback', 409, 'safe_mode_forced', { detail: { code: 'safe_mode_forced', detail: 'runtime safe mode is forced' } })),
        ).toBe('runtime safe mode is forced');

        mockState.nextFetchImpl = async () => {
            throw new ApiError('HTTP 404', 404, 'cplug_unknown', {
                detail: { code: 'cplug_unknown', message: 'unknown plugin: missing' },
            });
        };
        await expect(pluginsStore.fetchInspector('missing')).rejects.toThrow('HTTP 404');
        expect(pluginsStore.error).toBe('unknown plugin: missing');

        mockState.nextFetchImpl = async () => {
            throw { detail: { code: 'ledger_error', detail: 'install ledger write failed' } };
        };
        expect(await pluginsStore.refresh({ force: true })).toBe(false);
        expect(pluginsStore.error).toBe('install ledger write failed');
    });
});

describe('includeAgentPlugins and acquireInspector (M3.2)', () => {
    test('includeAgentPlugins queries /cplugs?include_agent_plugins=true when requested and stays default /cplugs otherwise', async () => {
        mockState.nextFetchImpl = async () => ({ cplugs: mockState.rows });

        await pluginsStore.refresh();
        expect(mockState.fetches.at(-1)?.path).toBe('/cplugs');

        await pluginsStore.refresh({ force: true, includeAgentPlugins: true });
        expect(mockState.fetches.at(-1)?.path).toBe('/cplugs?include_agent_plugins=true');

        const stop = pluginsStore.acquire({ includeAgentPlugins: true });
        await vi.waitFor(() => expect(mockState.fetches.at(-1)?.path).toBe('/cplugs?include_agent_plugins=true'));

        mockState.pushRegistrations[0]!.refresh();
        await vi.waitFor(() => expect(mockState.fetches.filter((f) => f.path === '/cplugs?include_agent_plugins=true').length).toBeGreaterThanOrEqual(3));

        stop();
        await pluginsStore.refresh({ force: true });
        expect(mockState.fetches.at(-1)?.path).toBe('/cplugs');
    });

    test('active acquire({ includeAgentPlugins: true }) prevents refresh({ includeAgentPlugins: false }) from downgrading rows', async () => {
        const agentRow: CplugRow = {
            id: 'cc-lint',
            kind: 'agent-plugin',
            runtime: 'agent-plugin',
            name: 'CC Lint',
            enabled: null,
            state: 'active',
        };
        mockState.nextFetchImpl = async (path) => ({
            cplugs: path === '/cplugs?include_agent_plugins=true' ? [...mockState.rows, agentRow] : mockState.rows,
        });

        const stop = pluginsStore.acquire({ includeAgentPlugins: true });
        await vi.waitFor(() => expect(pluginsStore.rowOf('cc-lint')).toBeDefined());

        expect(await pluginsStore.refresh({ allowSignedOut: true, includeAgentPlugins: false })).toBe(true);
        expect(mockState.fetches.at(-1)?.path).toBe('/cplugs?include_agent_plugins=true');
        expect(pluginsStore.rowOf('cc-lint')?.kind).toBe('agent-plugin');

        stop();
        expect(await pluginsStore.refresh({ allowSignedOut: true, includeAgentPlugins: false })).toBe(true);
        expect(mockState.fetches.at(-1)?.path).toBe('/cplugs');
        expect(pluginsStore.rowOf('cc-lint')).toBeUndefined();
    });

    test('acquireInspector ref-counts, updates inspectors on cplug_inspector:<id>, <installKey>, and LIVENESS, and cleans up on release/resetForTest', async () => {
        let count = 0;
        const makeSnapshot = (rss: number): PluginInspectorSnapshot => ({
            cplug_id: 'gh-clock',
            install_key: 'inst-1',
            state: 'running',
            paused: false,
            watchdog: {
                memory_limit_bytes: 134_217_728,
                rss_bytes: rss,
                cpu_percent: 1.2,
                restart_count: 0,
                strikes: 0,
                crash_loop_paused: false,
                last_call: 'http.fetch https://api.github.com/zen',
                last_event: 'reloaded',
            },
            rpc_trace: [],
            capability_checks: [],
            logs_tail: [],
        });

        mockState.nextFetchImpl = async (path) => {
            if (path === '/cplugs/gh-clock/inspector') {
                count += 1;
                return makeSnapshot(1024 * count);
            }
            return { cplugs: mockState.rows };
        };

        expect(pluginsStore.inspectorOf('gh-clock')).toBeNull();
        const r1 = pluginsStore.acquireInspector('gh-clock', 'inst-1');
        const r2 = pluginsStore.acquireInspector('gh-clock');
        expect(mockState.changeListeners.size).toBe(1);
        await vi.waitFor(() => expect(pluginsStore.inspectorOf('gh-clock')?.watchdog.rss_bytes).toBe(1024));
        expect(count).toBe(1);

        for (const fn of mockState.changeListeners) fn([`${CPLUG_INSPECTOR_TOPIC}:other`]);
        await Promise.resolve();
        expect(count).toBe(1);

        for (const fn of mockState.changeListeners) fn([`${CPLUG_INSPECTOR_TOPIC}:gh-clock`]);
        await vi.waitFor(() => expect(pluginsStore.inspectorOf('gh-clock')?.watchdog.rss_bytes).toBe(2048));
        expect(count).toBe(2);

        for (const fn of mockState.changeListeners) fn([`${CPLUG_INSPECTOR_TOPIC}:inst-1`]);
        await vi.waitFor(() => expect(pluginsStore.inspectorOf('gh-clock')?.watchdog.rss_bytes).toBe(3072));
        expect(count).toBe(3);

        mockState.isLive = false;
        for (const fn of mockState.changeListeners) fn([LIVENESS]);
        await Promise.resolve();
        expect(count).toBe(3);
        mockState.isLive = true;
        for (const fn of mockState.changeListeners) fn([LIVENESS]);
        await vi.waitFor(() => expect(pluginsStore.inspectorOf('gh-clock')?.watchdog.rss_bytes).toBe(4096));
        expect(count).toBe(4);

        r1();
        r1(); // idempotent
        expect(mockState.changeListeners.size).toBe(1);
        r2();
        expect(mockState.changeListeners.size).toBe(0);

        pluginsStore.acquireInspector('gh-clock', 'inst-1');
        await vi.waitFor(() => expect(count).toBe(5));
        expect(mockState.changeListeners.size).toBe(1);
        pluginsStore.resetForTest();
        expect(mockState.changeListeners.size).toBe(0);
        expect(pluginsStore.inspectorOf('gh-clock')).toBeNull();
        expect(pluginsStore.inspectors).toEqual({});
    });

    test('pausePlugin, resumePlugin, and restartPlugin refresh cached inspectors[id] without SSE push', async () => {
        let currentInspector: PluginInspectorSnapshot = {
            cplug_id: 'gh-clock',
            state: 'crash_loop',
            paused: true,
            watchdog: {
                memory_limit_bytes: 134_217_728,
                rss_bytes: 2048,
                cpu_percent: 0.5,
                restart_count: 3,
                strikes: 3,
                crash_loop_paused: true,
            },
            rpc_trace: [],
            capability_checks: [],
            logs_tail: [],
        };

        mockState.nextFetchImpl = async (path) => {
            if (path === '/cplugs/gh-clock/inspector') return currentInspector;
            if (path === '/cplugs') return { cplugs: mockState.rows };
            return { id: 'gh-clock' };
        };

        await pluginsStore.pausePlugin('gh-clock');
        expect(mockState.fetches.some((f) => f.path === '/cplugs/gh-clock/inspector')).toBe(false);

        await pluginsStore.fetchInspector('gh-clock');
        expect(pluginsStore.inspectorOf('gh-clock')?.paused).toBe(true);
        expect(pluginsStore.inspectorOf('gh-clock')?.watchdog.crash_loop_paused).toBe(true);

        currentInspector = {
            ...currentInspector,
            state: 'running',
            paused: false,
            watchdog: { ...currentInspector.watchdog, crash_loop_paused: false },
        };
        await pluginsStore.resumePlugin('gh-clock');
        expect(pluginsStore.inspectorOf('gh-clock')?.paused).toBe(false);
        expect(pluginsStore.inspectorOf('gh-clock')?.state).toBe('running');
        expect(pluginsStore.inspectorOf('gh-clock')?.watchdog.crash_loop_paused).toBe(false);

        currentInspector = {
            ...currentInspector,
            state: 'paused',
            paused: true,
        };
        await pluginsStore.pausePlugin('gh-clock');
        expect(pluginsStore.inspectorOf('gh-clock')?.paused).toBe(true);
        expect(pluginsStore.inspectorOf('gh-clock')?.state).toBe('paused');

        currentInspector = {
            ...currentInspector,
            state: 'running',
            paused: false,
            watchdog: { ...currentInspector.watchdog, crash_loop_paused: false, restart_count: 4 },
        };
        await pluginsStore.restartPlugin('gh-clock');
        expect(pluginsStore.inspectorOf('gh-clock')?.paused).toBe(false);
        expect(pluginsStore.inspectorOf('gh-clock')?.state).toBe('running');
        expect(pluginsStore.inspectorOf('gh-clock')?.watchdog.restart_count).toBe(4);
    });
});

describe('cplug_slots subscription, aliasing, and mutations (M4.1c)', () => {
    test('acquireSlots subscribes ref-counted cplug_slots, normalizes aliases, coalesces single-flight, and cleans up on resetForTest', async () => {
        let slotsResponse: CplugSlotsResponse = {
            slots: {
                terminal_toolbar: [
                    {
                        plugin_id: 'gh-clock',
                        install_key: 'inst-1',
                        slot: 'terminal.toolbar',
                        declared_slot: 'terminal_toolbar',
                        item: { id: 'clock-btn', label: 'Clock', route: 'tick' },
                    },
                ],
                'custom.board': [
                    {
                        plugin_id: 'gh-clock',
                        install_key: 'inst-1',
                        slot: 'custom.board',
                        declared_slot: 'custom.board',
                        item: { schema: 2, root: { type: 'text', value: 'hello' } },
                    },
                ],
            },
            owners: { 'custom.board': 'gh-clock' },
        };

        mockState.nextFetchImpl = async (path) => {
            if (path === '/cplugs/slots') return slotsResponse;
            if (path === '/cplugs') return { cplugs: mockState.rows };
            return {};
        };

        const seenUpdates: number[] = [];
        const offSlots = pluginsStore.onSlots((slots) => {
            seenUpdates.push(slots['terminal.toolbar']?.length ?? 0);
        });

        const r1 = pluginsStore.acquireSlots();
        const r2 = pluginsStore.acquireSlots();
        await vi.waitFor(() => expect(pluginsStore.slotsRead).toBe(true));

        expect(mockState.pushRegistrations).toHaveLength(1);
        expect(mockState.pushRegistrations[0]!.topics).toEqual([CPLUG_SLOTS_TOPIC]);
        expect(pluginsStore.slotsFor('terminal.toolbar')).toHaveLength(1);
        expect(pluginsStore.slotsFor('terminal_toolbar')).toHaveLength(1);
        expect(pluginsStore.slotOwnerOf('custom.board')).toBe('gh-clock');
        expect(seenUpdates).toEqual([1]);

        slotsResponse = { slots: {}, owners: {} };
        mockState.pushRegistrations[0]!.refresh();
        await vi.waitFor(() => expect(pluginsStore.slotsFor('terminal.toolbar')).toHaveLength(0));
        expect(seenUpdates).toEqual([1, 0]);

        r1();
        expect(mockState.pushRegistrations[0]!.stopped).toBe(0);
        r2();
        expect(mockState.pushRegistrations[0]!.stopped).toBe(1);

        slotsResponse = {
            slots: {
                'project.panels': [
                    {
                        plugin_id: 'gh-clock',
                        install_key: 'inst-1',
                        slot: 'project.panels',
                        declared_slot: 'project.panels',
                        item: { id: 'p1', label: 'Clock Panel', route: 'tick' },
                    },
                ],
            },
            owners: {},
        };
        await pluginsStore.pausePlugin('gh-clock');
        expect(pluginsStore.slotsFor('project_panels')).toHaveLength(1);

        offSlots();
        pluginsStore.resetForTest();
        expect(pluginsStore.slotsRead).toBe(false);
        expect(pluginsStore.slots).toEqual({});
        expect(pluginsStore.slotOwners).toEqual({});

        auth.state = 'signed-out';
        expect(await pluginsStore.refreshSlots()).toBe(false);
    });
});
