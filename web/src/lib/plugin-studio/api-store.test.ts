import { afterEach, describe, expect, test, vi } from 'vitest';
import { ApiError, auth, initAuth } from '../../opscenter/api/auth.svelte';
import { pluginsStore } from '../plugins/store.svelte';
import {
    createWorkspace,
    deleteWorkspace,
    extractStudioError,
    getReadiness,
    getWorkspace,
    installWorkspace,
    launchAgent,
    listWorkspaces,
    previewRender,
    publishWorkspace,
    runReadiness,
    startDev,
    stopDev,
    testSandbox,
} from './api';
import { StudioStore, type StudioStreamOpener } from './studio-store.svelte';
import { defaultPreviewThemes, resolveThemePreview } from './theme-bridge';
import type { StudioWorkspace, WorkspaceDetailResponse } from './types';

function makeFakeSseOpener() {
    const encoder = new TextEncoder();
    const sources: Array<{
        url: string;
        signal: AbortSignal | null | undefined;
        emit: (type: string, data?: string) => Promise<void>;
    }> = [];
    const opener: StudioStreamOpener = async (path, init) => {
        let controller!: ReadableStreamDefaultController<Uint8Array>;
        const stream = new ReadableStream<Uint8Array>({
            start(c) {
                controller = c;
            },
        });
        sources.push({
            url: path,
            signal: init.signal,
            emit: async (type, data) => {
                controller.enqueue(encoder.encode(`event: ${type}\ndata: ${data ?? ''}\n\n`));
                await new Promise((r) => setTimeout(r, 0));
            },
        });
        return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
    };
    return { sources, opener };
}

function makeJsonResponse<T>(data: T): T {
    return data;
}

function makeWorkspace(overrides: Partial<StudioWorkspace> = {}): StudioWorkspace {
    return {
        studio_id: 'ws_1',
        plugin_id: 'demo_plugin',
        name: 'DemoPlugin',
        template: 'python',
        prompt: 'build demo tool',
        agent_kind: 'claude',
        folder: '/tmp/studio/ws_1',
        session_id: 'ses_1',
        session_tmux: 'cl_ws_1',
        dev_active: false,
        created_at: '2026-11-26T00:00:00Z',
        updated_at: '2026-11-26T00:00:00Z',
        last_readiness: null,
        ...overrides,
    };
}

function makeDetail(overrides: Partial<WorkspaceDetailResponse> = {}): WorkspaceDetailResponse {
    const ws = overrides.workspace ?? makeWorkspace();
    return {
        workspace: ws,
        files: [{ path: 'carnivore.toml', size: 120, executable: false }],
        session_status: { session_id: ws.session_id, active: true, status: 'running', tmux_session: ws.session_tmux },
        dev_status: {
            active: ws.dev_active,
            plugin_id: ws.plugin_id,
            status: ws.dev_active ? 'active' : 'stopped',
            reload_count: 0,
            last_reload_ms: null,
            last_error: null,
            lease: null,
        },
        inspector: {
            studio_id: ws.studio_id,
            cplug_id: ws.plugin_id,
            state: 'dev',
            paused: false,
            watchdog: { rss_bytes: 12000, cpu_seconds: 0.2, strikes: 0 },
            surfaces: { widget: false, panel: true, bar: false, settings: false, views: ['panel'], tools: ['demo.echo'], routes: ['echo'] },
            dev_lease: null,
            secrets_status: {},
            rpc_trace: [],
            capability_checks: [],
            logs_tail: [],
            dev: {
                active: ws.dev_active,
                plugin_id: ws.plugin_id,
                status: 'stopped',
                reload_count: 0,
                last_reload_ms: null,
                last_error: null,
                lease: null,
            },
            capabilities: {
                permissions: ['routes'],
                permission_reasons: { routes: 'ui actions' },
                tools: ['demo.echo'],
                routes: ['echo'],
                views: ['panel'],
                ui_slots: [],
                services_provides: [],
                services_consumes: [],
                events_emit: [],
                events_on: [],
            },
            events: [],
            ui_errors: [],
            slot_renders: { 'session.row_actions': [{ plugin_id: ws.plugin_id, label: 'Echo' }] },
        },
        preview: {
            kind: 'declarative',
            surface: 'panel',
            view_url: null,
            doc: { v: 2, root: { type: 'text', text: 'hello' } },
            theme_id: 'carnivore',
            width: 480,
            height: 320,
            errors: [],
        },
        ...overrides,
    };
}

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe('plugin-studio API client & theme-bridge', () => {
    test('wraps all 13 /cplug-owner/studio/* endpoints with expected HTTP methods and payloads', async () => {
        const calls: Array<{ url: string; method: string; body?: string }> = [];
        const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
            const url = String(input);
            const method = init?.method ?? 'GET';
            calls.push({ url, method, body: typeof init?.body === 'string' ? init.body : undefined });
            if (url === '/cplug-owner/studio/workspaces' && method === 'GET') {
                return makeJsonResponse({ workspaces: [makeWorkspace()] });
            }
            if (url === '/cplug-owner/studio/workspaces' && method === 'POST') {
                return makeJsonResponse({ workspace: makeWorkspace(), files: [], session: null, dev: null });
            }
            if (url === '/cplug-owner/studio/workspaces/ws_1' && method === 'GET') {
                return makeJsonResponse(makeDetail());
            }
            if (url.startsWith('/cplug-owner/studio/workspaces/ws_1?delete_files=') && method === 'DELETE') {
                return makeJsonResponse({ ok: true, studio_id: 'ws_1' });
            }
            if (url.endsWith('/agent')) {
                return makeJsonResponse({ session_id: 'ses_2', tmux_session: null, agent_kind: 'codex', agent_type: 'codex', opening_prompt: 'p' });
            }
            if (url.endsWith('/dev/start')) {
                return makeJsonResponse({ active: true, plugin_id: 'demo_plugin', lease: { plugin_id: 'demo_plugin', baseline_sha: 'abc1234', expires_at: '2026-11-27T00:00:00Z' } });
            }
            if (url.endsWith('/dev/stop')) {
                return makeJsonResponse({ active: false });
            }
            if (url.includes('/readiness')) {
                return makeJsonResponse({ ok: true, ready: true, items: [], checked_at: 'now', digest: 'd', summary: { pass: 1, fail: 0, advisory: 0, undetermined: 0, unavailable: 0 } });
            }
            if (url.endsWith('/test-sandbox')) {
                return makeJsonResponse({ ok: true, check: { ok: true, warnings: [] }, unit: { output: 'ok' }, smoke: null, errors: [], warnings: [] });
            }
            if (url.endsWith('/install')) {
                return makeJsonResponse({ ok: true, plugin_id: 'demo_plugin', item_id: 'item_1', enabled: true, runtime_active: true, digest: 'd1' });
            }
            if (url.endsWith('/publish')) {
                return makeJsonResponse({ ok: true, dry_run: true, preview: { digest: 'd1' }, submission: null });
            }
            if (url.endsWith('/preview-render')) {
                return makeJsonResponse(makeDetail().preview);
            }
            return makeJsonResponse({});
        }) as unknown as typeof import('../../opscenter/api/auth.svelte').authFetch;

        expect(await listWorkspaces(fetcher)).toHaveLength(1);
        await createWorkspace({ prompt: 'build tool', template: 'widget', agent_kind: 'agy', start_agent: true, start_dev: true }, fetcher);
        await getWorkspace('ws_1', fetcher);
        await deleteWorkspace('ws_1', true, fetcher);
        await launchAgent('ws_1', { agent_kind: 'codex' }, fetcher);
        await startDev('ws_1', { auto_approve: true }, fetcher);
        await stopDev('ws_1', fetcher);
        await getReadiness('ws_1', false, fetcher);
        await runReadiness('ws_1', { run_tests: true }, fetcher);
        await testSandbox('ws_1', {}, fetcher);
        await installWorkspace('ws_1', { activate_runtime: true, auto_approve: true }, fetcher);
        await publishWorkspace('ws_1', { mode: 'github', pointer: 'a/b@v1', dry_run: true }, fetcher);
        await previewRender('ws_1', { theme_id: 'matrix', width: 320, height: 240 }, fetcher);

        expect(calls).toHaveLength(13);
        expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
            'GET /cplug-owner/studio/workspaces',
            'POST /cplug-owner/studio/workspaces',
            'GET /cplug-owner/studio/workspaces/ws_1',
            'DELETE /cplug-owner/studio/workspaces/ws_1?delete_files=true',
            'POST /cplug-owner/studio/workspaces/ws_1/agent',
            'POST /cplug-owner/studio/workspaces/ws_1/dev/start',
            'POST /cplug-owner/studio/workspaces/ws_1/dev/stop',
            'GET /cplug-owner/studio/workspaces/ws_1/readiness?run_tests=false',
            'POST /cplug-owner/studio/workspaces/ws_1/readiness',
            'POST /cplug-owner/studio/workspaces/ws_1/test-sandbox',
            'POST /cplug-owner/studio/workspaces/ws_1/install',
            'POST /cplug-owner/studio/workspaces/ws_1/publish',
            'POST /cplug-owner/studio/workspaces/ws_1/preview-render',
        ]);
    });

    test('extractStudioError extracts developer_mode_off, agy_profile_not_configured, and folder_refused refusals', () => {
        const devErr = new ApiError('conflict', 409, 'developer_mode_off', {
            detail: { code: 'developer_mode_off', detail: 'turn developer mode on' },
        });
        expect(extractStudioError(devErr)).toMatchObject({
            code: 'developer_mode_off',
            message: 'turn developer mode on',
            status: 409,
        });

        const agyErr = new ApiError('conflict', 409, 'agy_profile_not_configured', {
            detail: { code: 'agy_profile_not_configured', detail: 'configure agy profile' },
        });
        expect(extractStudioError(agyErr)).toMatchObject({
            code: 'agy_profile_not_configured',
            status: 409,
        });

        const refuseErr = new ApiError('refused', 409, 'folder_refused', {
            detail: {
                code: 'folder_refused',
                detail: 'missing changelog',
                refusals: [{ code: 'missing_readme', reason: 'missing README' }],
            },
        });
        expect(extractStudioError(refuseErr).refusals).toHaveLength(1);
    });

    test('theme-bridge builds safe ocStyle and themeValues and selects >=2 default themes', () => {
        const choices = [
            { id: 'carnivore', name: 'Carnivore' },
            { id: 'matrix', name: 'Matrix' },
            { id: 'nord', name: 'Nord' },
        ];
        expect(defaultPreviewThemes(choices, 'nord')).toEqual(['nord', 'matrix']);

        const preview = resolveThemePreview('matrix', choices, () => ({
            '--oc-ground-page': '#001100',
            '--oc-text-primary': '#33ff66',
            '--oc-cyan': 'url(//blocked)',
        }));
        expect(preview.name).toBe('Matrix');
        expect(preview.ocStyle).toContain('--oc-ground-page: #001100');
        expect(preview.ocStyle).not.toContain('blocked');
        expect(preview.themeValues['--oc-ground-page']).toBe('#001100');
        expect(preview.themeValues['ground-page']).toBe('#001100');
    });
});

describe('StudioStore lifecycle, SSE stream, and pluginsStore sync', () => {
    test('subscribes to authenticated SSE stream while dev is active and refreshes pluginsStore after dev start and install', async () => {
        const { sources, opener } = makeFakeSseOpener();

        const refreshSpy = vi.spyOn(pluginsStore, 'refresh').mockResolvedValue(true);
        vi.spyOn(pluginsStore, 'acquireInspector').mockReturnValue(vi.fn());

        let devActive = true;
        const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
            const url = String(input);
            const method = init?.method ?? 'GET';
            if (url === '/cplug-owner/studio/workspaces' && method === 'GET') {
                return makeJsonResponse({ workspaces: [makeWorkspace({ dev_active: devActive })] });
            }
            if (url === '/cplug-owner/studio/workspaces/ws_1' && method === 'GET') {
                return makeJsonResponse(makeDetail({ workspace: makeWorkspace({ dev_active: devActive }) }));
            }
            if (url.endsWith('/preview-render')) {
                return makeJsonResponse(makeDetail().preview);
            }
            if (url.endsWith('/dev/start')) {
                devActive = true;
                return makeJsonResponse({ active: true, plugin_id: 'demo_plugin', lease: { plugin_id: 'demo_plugin', baseline_sha: 'abc', expires_at: 'later' } });
            }
            if (url.endsWith('/dev/stop')) {
                devActive = false;
                return makeJsonResponse({ active: false });
            }
            if (url.endsWith('/install')) {
                return makeJsonResponse({ ok: true, plugin_id: 'demo_plugin', item_id: 'item_1', enabled: true, runtime_active: true, digest: 'd1' });
            }
            return makeJsonResponse({});
        }) as unknown as typeof import('../../opscenter/api/auth.svelte').authFetch;

        const store = new StudioStore();
        store.setFetcherForTest(fetcher);
        store.setStreamOpenerForTest(opener);
        store.selectedThemes = ['carnivore', 'matrix'];

        await store.refreshWorkspaces();
        expect(sources).toHaveLength(1);
        expect(sources[0]?.url).toBe('/cplug-owner/dev/stream/demo_plugin');

        refreshSpy.mockClear();

        await sources[0]?.emit('reloaded', JSON.stringify({ seq: 1, type: 'reloaded', data: { status: 'reloaded' } }));
        expect(store.devEvents[0]?.type).toBe('reloaded');
        expect(refreshSpy).toHaveBeenCalledWith({ force: true });

        refreshSpy.mockClear();
        await sources[0]?.emit('permission_widened', JSON.stringify({ seq: 2, type: 'permission_widened', data: { widened: ['network'] } }));
        expect(store.devEvents[0]?.type).toBe('permission_widened');
        expect(refreshSpy).toHaveBeenCalledWith({ force: true });

        refreshSpy.mockClear();
        await sources[0]?.emit('ui_error', JSON.stringify({ seq: 3, type: 'ui_error', data: { code: 'invalid_doc' } }));
        expect(store.devEvents[0]?.type).toBe('ui_error');
        expect(refreshSpy).toHaveBeenCalledWith({ force: true });

        refreshSpy.mockClear();
        await sources[0]?.emit('reload_error', JSON.stringify({ seq: 4, type: 'reload_error', data: { code: 'syntax_error' } }));
        expect(store.devEvents[0]?.type).toBe('reload_error');
        expect(refreshSpy).toHaveBeenCalledWith({ force: true });

        refreshSpy.mockClear();
        await sources[0]?.emit('stderr', JSON.stringify({ seq: 5, type: 'stderr', data: { text: 'traceback' } }));
        expect(store.devEvents[0]?.type).toBe('stderr');
        expect(refreshSpy).not.toHaveBeenCalled();

        await store.installActive();
        expect(store.installResult?.ok).toBe(true);
        expect(refreshSpy).toHaveBeenCalledWith({ force: true });

        await store.stopDevMode();
        expect(sources[0]?.signal?.aborted).toBe(true);
        store.dispose();
    });

    test('dispose() drops in-flight refreshDetail without opening SSE stream or acquireInspector and allows remount', async () => {
        const { sources, opener } = makeFakeSseOpener();
        vi.spyOn(pluginsStore, 'refresh').mockResolvedValue(true);
        const acquireSpy = vi.spyOn(pluginsStore, 'acquireInspector').mockReturnValue(vi.fn());

        let resolvePendingDetail!: (value: WorkspaceDetailResponse) => void;
        let markDetailRequested!: () => void;
        const detailRequested = new Promise<void>((resolve) => {
            markDetailRequested = resolve;
        });
        let holdDetail = true;

        const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
            const url = String(input);
            const method = init?.method ?? 'GET';
            if (url === '/cplug-owner/studio/workspaces' && method === 'GET') {
                return makeJsonResponse({ workspaces: [makeWorkspace({ dev_active: true })] });
            }
            if (url === '/cplug-owner/studio/workspaces/ws_1' && method === 'GET') {
                if (holdDetail) {
                    markDetailRequested();
                    return await new Promise<WorkspaceDetailResponse>((resolve) => {
                        resolvePendingDetail = resolve;
                    });
                }
                return makeJsonResponse(makeDetail({ workspace: makeWorkspace({ dev_active: true }) }));
            }
            if (url.endsWith('/preview-render')) {
                return makeJsonResponse(makeDetail().preview);
            }
            return makeJsonResponse({});
        }) as unknown as typeof import('../../opscenter/api/auth.svelte').authFetch;

        const store = new StudioStore();
        store.setFetcherForTest(fetcher);
        store.setStreamOpenerForTest(opener);
        store.selectedThemes = ['carnivore', 'matrix'];

        const pendingRefresh = store.refreshWorkspaces();
        await detailRequested;
        store.dispose();

        resolvePendingDetail(makeDetail({ workspace: makeWorkspace({ dev_active: true }) }));
        await pendingRefresh;

        expect(sources).toHaveLength(0);
        expect(acquireSpy).not.toHaveBeenCalled();
        expect(store.detail).toBeNull();
        expect(store.loading).toBe(false);
        expect(store.busyAction).toBeNull();

        holdDetail = false;
        await store.refreshWorkspaces();
        expect(sources).toHaveLength(1);
        expect(sources[0]?.url).toBe('/cplug-owner/dev/stream/demo_plugin');
        expect(acquireSpy).toHaveBeenCalledTimes(1);
        expect(store.detail?.workspace.studio_id).toBe('ws_1');
        expect(store.loading).toBe(false);
        expect(store.busyAction).toBeNull();
        store.dispose();
    });

    test('selectWorkspace("ws_2") drops stale in-flight refreshDetail("ws_1") and refreshPreviews("ws_1")', async () => {
        const { sources, opener } = makeFakeSseOpener();
        vi.spyOn(pluginsStore, 'refresh').mockResolvedValue(true);
        vi.spyOn(pluginsStore, 'acquireInspector').mockReturnValue(vi.fn());

        const ws1 = makeWorkspace({ studio_id: 'ws_1', plugin_id: 'plugin_one', dev_active: true });
        const ws2 = makeWorkspace({ studio_id: 'ws_2', plugin_id: 'plugin_two', dev_active: true });

        let resolveWs1Detail!: (value: WorkspaceDetailResponse) => void;
        let markWs1DetailRequested!: () => void;
        const ws1DetailRequested = new Promise<void>((resolve) => {
            markWs1DetailRequested = resolve;
        });

        const resolveWs1Previews: Array<(value: WorkspaceDetailResponse['preview']) => void> = [];
        let markWs1PreviewRequested!: () => void;
        const ws1PreviewRequested = new Promise<void>((resolve) => {
            markWs1PreviewRequested = resolve;
        });

        const ws2Preview = {
            ...makeDetail().preview,
            doc: { v: 2, root: { type: 'text', text: 'plugin_two preview' } },
        };
        const staleWs1Preview = {
            ...makeDetail().preview,
            doc: { v: 2, root: { type: 'text', text: 'stale plugin_one preview' } },
        };

        const fetcher = (async (input: RequestInfo | URL) => {
            const url = String(input);
            if (url === '/cplug-owner/studio/workspaces/ws_1') {
                markWs1DetailRequested();
                return await new Promise<WorkspaceDetailResponse>((resolve) => {
                    resolveWs1Detail = resolve;
                });
            }
            if (url === '/cplug-owner/studio/workspaces/ws_2') {
                return makeJsonResponse(makeDetail({ workspace: ws2, preview: ws2Preview }));
            }
            if (url === '/cplug-owner/studio/workspaces/ws_1/preview-render') {
                markWs1PreviewRequested();
                return await new Promise<WorkspaceDetailResponse['preview']>((resolve) => {
                    resolveWs1Previews.push(resolve);
                });
            }
            if (url === '/cplug-owner/studio/workspaces/ws_2/preview-render') {
                return makeJsonResponse(ws2Preview);
            }
            return makeJsonResponse({});
        }) as unknown as typeof import('../../opscenter/api/auth.svelte').authFetch;

        const store = new StudioStore();
        store.setFetcherForTest(fetcher);
        store.setStreamOpenerForTest(opener);
        store.selectedThemes = ['carnivore', 'matrix'];

        const pendingDetailWs1 = store.selectWorkspace('ws_1');
        await ws1DetailRequested;
        await store.selectWorkspace('ws_2');
        resolveWs1Detail(makeDetail({ workspace: ws1 }));
        await pendingDetailWs1;

        expect(store.activeId).toBe('ws_2');
        expect(store.detail?.workspace.plugin_id).toBe('plugin_two');
        expect(sources.map((s) => s.url)).toEqual(['/cplug-owner/dev/stream/plugin_two']);
        expect(store.previewByTheme['carnivore']?.doc).toEqual(ws2Preview.doc);

        store.activeId = 'ws_1';
        const pendingPreviewsWs1 = store.refreshPreviews('ws_1');
        await ws1PreviewRequested;
        await store.selectWorkspace('ws_2');
        for (const resolve of resolveWs1Previews) resolve(staleWs1Preview);
        await pendingPreviewsWs1;

        expect(store.activeId).toBe('ws_2');
        expect(store.previewByTheme['carnivore']?.doc).toEqual(ws2Preview.doc);
        expect(store.previewByTheme['matrix']?.doc).toEqual(ws2Preview.doc);
        expect(store.busyAction).toBeNull();
        store.dispose();
    });

    test('switching from ws_1 to ws_2 clears readiness, surfaceId, handles, and stale detail on ws_2 fetch error', async () => {
        const { sources, opener } = makeFakeSseOpener();
        vi.spyOn(pluginsStore, 'refresh').mockResolvedValue(true);
        const releaseSpy = vi.fn();
        vi.spyOn(pluginsStore, 'acquireInspector').mockReturnValue(releaseSpy);

        const ws1Readiness = {
            ok: false,
            ready: false,
            items: [],
            checked_at: '2026-11-26T00:00:00Z',
            digest: 'd_ws1',
            summary: { pass: 1, fail: 2, advisory: 0, undetermined: 0, unavailable: 0 },
        };
        const ws1 = makeWorkspace({ studio_id: 'ws_1', plugin_id: 'plugin_one', dev_active: true, last_readiness: ws1Readiness });
        const ws2 = makeWorkspace({ studio_id: 'ws_2', plugin_id: 'plugin_two', dev_active: false, last_readiness: null });
        let failWs2 = false;

        const fetcher = (async (input: RequestInfo | URL) => {
            const url = String(input);
            if (url === '/cplug-owner/studio/workspaces/ws_1') {
                return makeJsonResponse(makeDetail({ workspace: ws1 }));
            }
            if (url === '/cplug-owner/studio/workspaces/ws_2') {
                if (failWs2) {
                    throw new ApiError('not found', 404, 'studio_workspace_not_found', {
                        detail: { code: 'studio_workspace_not_found', detail: 'ws_2 missing' },
                    });
                }
                return makeJsonResponse(makeDetail({ workspace: ws2 }));
            }
            if (url.endsWith('/preview-render')) {
                return makeJsonResponse(makeDetail().preview);
            }
            return makeJsonResponse({});
        }) as unknown as typeof import('../../opscenter/api/auth.svelte').authFetch;

        const store = new StudioStore();
        store.setFetcherForTest(fetcher);
        store.setStreamOpenerForTest(opener);
        store.selectedThemes = ['carnivore', 'matrix'];

        await store.selectWorkspace('ws_1');
        store.setSurface('main');
        expect(store.readiness?.summary.fail).toBe(2);
        expect(store.surfaceId).toBe('main');
        expect(sources).toHaveLength(1);
        expect(releaseSpy).not.toHaveBeenCalled();

        await store.selectWorkspace('ws_2');
        expect(store.activeId).toBe('ws_2');
        expect(store.readiness).toBeNull();
        expect(store.surfaceId).toBeNull();
        expect(sources[0]?.signal?.aborted).toBe(true);
        expect(releaseSpy).toHaveBeenCalledTimes(1);

        await store.selectWorkspace('ws_1');
        store.setSurface('main');
        expect(store.readiness?.summary.fail).toBe(2);
        expect(store.detail?.workspace.studio_id).toBe('ws_1');

        failWs2 = true;
        await store.selectWorkspace('ws_2');
        expect(store.activeId).toBe('ws_2');
        expect(store.readiness).toBeNull();
        expect(store.surfaceId).toBeNull();
        expect(store.detail).toBeNull();
        expect(store.error?.code).toBe('studio_workspace_not_found');
        expect(sources[1]?.signal?.aborted).toBe(true);
        expect(releaseSpy).toHaveBeenCalledTimes(2);
        store.dispose();
    });

    test('default SSE opener uses authFetchStream with Bearer token and ignores keepalive comments', async () => {
        vi.spyOn(pluginsStore, 'refresh').mockResolvedValue(true);
        vi.spyOn(pluginsStore, 'acquireInspector').mockReturnValue(vi.fn());

        const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
            const url = String(input);
            if (url === '/api/v1/cplug-owner/dev/stream/demo_plugin') {
                const encoder = new TextEncoder();
                const stream = new ReadableStream<Uint8Array>({
                    start(c) {
                        c.enqueue(encoder.encode(': keepalive\n\nevent: stderr\n'));
                        c.enqueue(encoder.encode('data: {"seq":9,"type":"stderr","data":{"text":"ok"}}\n\n'));
                        c.close();
                    },
                });
                return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
            }
            return new Response('{}', { status: 200 });
        });
        const storage = new Map<string, string>([['claude_tunnel_token', 'test-jwt-token']]);
        vi.stubGlobal('localStorage', {
            getItem: (k: string) => storage.get(k) ?? null,
            setItem: (k: string, v: string) => storage.set(k, v),
            removeItem: (k: string) => storage.delete(k),
        });
        initAuth();
        try {
            const store = new StudioStore();
            const ws = makeWorkspace({ dev_active: true });
            store.workspaces = [ws];
            store.activeId = ws.studio_id;
            store.detail = makeDetail({ workspace: ws });
            (store as unknown as { syncDevStream: (id: string | null) => void }).syncDevStream('demo_plugin');
            await new Promise((r) => setTimeout(r, 20));

            const streamCall = fetchSpy.mock.calls.find((c) => String(c[0]) === '/api/v1/cplug-owner/dev/stream/demo_plugin');
            expect(streamCall).toBeDefined();
            const headers = new Headers(streamCall?.[1]?.headers);
            expect(headers.get('Authorization')).toBe('Bearer test-jwt-token');
            expect(headers.get('Accept')).toBe('text/event-stream');
            expect(store.devEvents).toHaveLength(1);
            expect(store.devEvents[0]?.type).toBe('stderr');
            store.dispose();
        } finally {
            vi.unstubAllGlobals();
            initAuth();
            fetchSpy.mockRestore();
        }
    });

    test('selectWorkspace("ws_2") while refreshWorkspaces() is in flight settles with loading === false', async () => {
        vi.spyOn(pluginsStore, 'refresh').mockResolvedValue(true);
        vi.spyOn(pluginsStore, 'acquireInspector').mockReturnValue(vi.fn());

        const ws1 = makeWorkspace({ studio_id: 'ws_1', plugin_id: 'plugin_one' });
        const ws2 = makeWorkspace({ studio_id: 'ws_2', plugin_id: 'plugin_two' });

        let resolveList!: (value: { workspaces: StudioWorkspace[] }) => void;
        let markListRequested!: () => void;
        const listRequested = new Promise<void>((resolve) => {
            markListRequested = resolve;
        });

        const fetcher = (async (input: RequestInfo | URL) => {
            const url = String(input);
            if (url === '/cplug-owner/studio/workspaces') {
                markListRequested();
                return await new Promise<{ workspaces: StudioWorkspace[] }>((resolve) => {
                    resolveList = resolve;
                });
            }
            if (url === '/cplug-owner/studio/workspaces/ws_2') {
                return makeJsonResponse(makeDetail({ workspace: ws2 }));
            }
            if (url.endsWith('/preview-render')) {
                return makeJsonResponse(makeDetail({ workspace: ws2 }).preview);
            }
            return makeJsonResponse({});
        }) as unknown as typeof import('../../opscenter/api/auth.svelte').authFetch;

        const store = new StudioStore();
        store.setFetcherForTest(fetcher);
        store.selectedThemes = ['carnivore', 'matrix'];

        const pendingList = store.refreshWorkspaces();
        await listRequested;
        expect(store.loading).toBe(true);

        const pendingSelect = store.selectWorkspace('ws_2');
        await pendingSelect;
        expect(store.loading).toBe(false);
        expect(store.activeId).toBe('ws_2');

        resolveList({ workspaces: [ws1, ws2] });
        await pendingList;

        expect(store.loading).toBe(false);
        expect(store.busyAction).toBeNull();
        expect(store.activeId).toBe('ws_2');
        expect(store.detail?.workspace.studio_id).toBe('ws_2');
        store.dispose();
    });

    test('normalizes cross-chunk CRLF and standalone CR SSE splits', async () => {
        vi.spyOn(pluginsStore, 'refresh').mockResolvedValue(true);
        vi.spyOn(pluginsStore, 'acquireInspector').mockReturnValue(vi.fn());

        const encoder = new TextEncoder();
        const opener: StudioStreamOpener = async () => {
            const stream = new ReadableStream<Uint8Array>({
                start(c) {
                    c.enqueue(encoder.encode('event: stderr\r'));
                    c.enqueue(encoder.encode('\ndata: ok\r\n\r'));
                    c.enqueue(encoder.encode('\nevent: reloaded\rdata: {"seq":10}\r\r'));
                    c.close();
                },
            });
            return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
        };

        const store = new StudioStore();
        store.setStreamOpenerForTest(opener);
        const ws = makeWorkspace({ dev_active: true });
        store.workspaces = [ws];
        store.activeId = ws.studio_id;
        store.detail = makeDetail({ workspace: ws });

        (store as unknown as { syncDevStream: (id: string | null) => void }).syncDevStream('demo_plugin');
        await new Promise((r) => setTimeout(r, 20));

        expect(store.devEvents).toHaveLength(2);
        expect(store.devEvents[0]).toMatchObject({ type: 'reloaded', payload: { seq: 10 } });
        expect(store.devEvents[1]).toMatchObject({ type: 'stderr', payload: 'ok' });
        store.dispose();
    });

    test('cancels response.body when syncDevStream opener resolves after dispose/abort', async () => {
        const cancelSpy = vi.fn().mockResolvedValue(undefined);
        let resolveResponse!: (res: Response) => void;
        let markOpened!: () => void;
        const opened = new Promise<void>((resolve) => {
            markOpened = resolve;
        });

        const opener: StudioStreamOpener = async () => {
            markOpened();
            return await new Promise<Response>((resolve) => {
                resolveResponse = resolve;
            });
        };

        const store = new StudioStore();
        store.setStreamOpenerForTest(opener);
        (store as unknown as { syncDevStream: (id: string | null) => void }).syncDevStream('demo_plugin');
        await opened;

        store.dispose();

        const fakeBody = {
            cancel: cancelSpy,
            getReader: vi.fn(),
        } as unknown as ReadableStream<Uint8Array>;
        resolveResponse({ body: fakeBody } as unknown as Response);
        await new Promise((r) => setTimeout(r, 10));

        expect(cancelSpy).toHaveBeenCalledTimes(1);
    });

    test('no-ops refreshWorkspaces() and syncDevStream() while auth.state === "signed-out"', async () => {
        const prevState = auth.state;
        const fetchSpy = vi.spyOn(globalThis, 'fetch');
        auth.state = 'signed-out';
        try {
            const store = new StudioStore();
            const list = await store.refreshWorkspaces();
            expect(list).toEqual([]);
            expect(store.loading).toBe(false);
            expect(store.busyAction).toBeNull();
            expect(store.error).toBeNull();

            (store as unknown as { syncDevStream: (id: string | null) => void }).syncDevStream('demo_plugin');
            await new Promise((r) => setTimeout(r, 10));

            expect(fetchSpy).not.toHaveBeenCalled();
            store.dispose();
        } finally {
            auth.state = prevState;
            fetchSpy.mockRestore();
        }
    });
});
