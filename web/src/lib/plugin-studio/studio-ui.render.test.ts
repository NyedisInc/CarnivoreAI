/** @vitest-environment jsdom */
import { flushSync, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { inputFocus } from '../../opscenter/lib/input-focus.svelte';
import { pluginsStore } from '../plugins/store.svelte';
import { appActions } from '../palette/palette-actions';
import * as host from '../../opscenter/api/host';
import * as modal from '../modal';
import LabMenu from '../../plugins/devwidgetlab/LabMenu.svelte';
import LabViewer from '../../plugins/devwidgetlab/LabViewer.svelte';
import MultiThemePreview from './MultiThemePreview.svelte';
import StudioActionsBar from './StudioActionsBar.svelte';
import StudioScreen from './StudioScreen.svelte';
import StudioTerminalPane from './StudioTerminalPane.svelte';
import { closePluginStudio, isPluginStudioOpen, openPluginStudio } from './screen-host';
import { studioStore } from './studio-store.svelte';
import type { PreviewRenderResponse, StudioWorkspace, WorkspaceDetailResponse } from './types';

const cleanups: Array<() => void> = [];

function makeJsonResponse<T>(data: T): T {
    return data;
}

function sampleWorkspace(overrides: Partial<StudioWorkspace> = {}): StudioWorkspace {
    return {
        studio_id: 'ws_demo',
        plugin_id: 'demo_widget',
        name: 'DemoWidget',
        template: 'widget',
        prompt: 'build a status widget',
        agent_kind: 'claude',
        folder: '/tmp/ws_demo',
        session_id: 'ses_demo',
        session_tmux: 'cl_demo',
        dev_active: true,
        created_at: '2026-11-26T00:00:00Z',
        updated_at: '2026-11-26T00:00:00Z',
        last_readiness: {
            ok: false,
            ready: false,
            items: [
                {
                    id: 'manifest_valid',
                    label: 'manifest',
                    category: 'gate',
                    status: 'pass',
                    code: 'ok',
                    detail: 'valid',
                    findings: [],
                },
                {
                    id: 'readme_present',
                    label: 'readme',
                    category: 'gate',
                    status: 'fail',
                    code: 'missing_readme',
                    detail: 'add README',
                    findings: [{ message: 'missing README' }],
                },
            ],
            checked_at: '2026-11-26T00:00:00Z',
            digest: 'abc',
            summary: { pass: 1, fail: 1, advisory: 0, undetermined: 0, unavailable: 0 },
        },
        ...overrides,
    };
}

function sampleDetail(): WorkspaceDetailResponse {
    const ws = sampleWorkspace();
    return {
        workspace: ws,
        files: [{ path: 'carnivore.toml', size: 200, executable: false }],
        session_status: { session_id: 'ses_demo', active: true, status: 'running' },
        dev_status: {
            active: true,
            plugin_id: ws.plugin_id,
            status: 'active',
            reload_count: 1,
            last_reload_ms: 42,
            last_error: null,
            lease: {
                plugin_id: ws.plugin_id,
                baseline_sha: 'deadbeef',
                expires_at: '2026-11-27T00:00:00Z',
            },
        },
        inspector: {
            studio_id: ws.studio_id,
            cplug_id: ws.plugin_id,
            state: 'dev',
            paused: false,
            watchdog: { rss_bytes: 24000, cpu_seconds: 0.4, strikes: 0 },
            surfaces: { widget: true, panel: true, bar: false, settings: false, views: ['panel'], tools: ['demo.ping'], routes: ['ping'] },
            dev_lease: { active: true, baseline_sha: 'deadbeef' },
            secrets_status: {},
            rpc_trace: [],
            capability_checks: [],
            logs_tail: [],
            dev: {
                active: true,
                plugin_id: ws.plugin_id,
                status: 'active',
                reload_count: 1,
                last_reload_ms: 42,
                last_error: null,
                lease: null,
            },
            capabilities: {
                permissions: ['widgets'],
                permission_reasons: { widgets: 'status widget' },
                tools: ['demo.ping'],
                routes: ['ping'],
                views: ['panel'],
                ui_slots: [],
                services_provides: [],
                services_consumes: [],
                events_emit: [],
                events_on: [],
            },
            events: [],
            ui_errors: [],
            slot_renders: {
                'session.row_actions': [{ plugin_id: ws.plugin_id, label: 'RunCheck' }],
            },
        },
        preview: {
            kind: 'declarative',
            surface: 'panel',
            view_url: null,
            doc: { schema: 2, root: { type: 'text', value: 'live preview' } },
            theme_id: 'carnivore',
            width: 480,
            height: 320,
            errors: [],
        },
    };
}

afterEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
    studioStore.dispose();
    studioStore.setFetcherForTest(undefined);
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

describe('Plugin Studio UI & Entry Points', () => {
    test('StudioScreen renders 7 templates, 3 agents, terminal fallback, inspector, readiness, sandbox, and 2-step publish', async () => {
        vi.spyOn(pluginsStore, 'refresh').mockResolvedValue(true);
        vi.spyOn(pluginsStore, 'acquireInspector').mockReturnValue(vi.fn());

        const publishPayloads: Array<Record<string, unknown>> = [];
        const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
            const url = String(input);
            const method = init?.method ?? 'GET';
            if (url === '/cplug-owner/studio/workspaces' && method === 'GET') {
                return makeJsonResponse({ workspaces: [sampleWorkspace()] });
            }
            if (url === '/cplug-owner/studio/workspaces/ws_demo' && method === 'GET') {
                return makeJsonResponse(sampleDetail());
            }
            if (url.endsWith('/preview-render')) {
                const parsed = JSON.parse(String(init?.body ?? '{}')) as { theme_id?: string };
                return makeJsonResponse({
                    ...sampleDetail().preview,
                    theme_id: parsed.theme_id ?? 'carnivore',
                });
            }
            if (url.endsWith('/test-sandbox')) {
                return makeJsonResponse({ ok: true, check: { ok: true, warnings: [] }, unit: { output: '2 passed' }, smoke: null, errors: [], warnings: [] });
            }
            if (url.endsWith('/publish')) {
                const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
                publishPayloads.push(body);
                return makeJsonResponse({
                    ok: true,
                    dry_run: Boolean(body.dry_run),
                    preview: body.dry_run ? { digest: 'sha256:cafe1234' } : null,
                    submission: body.dry_run ? null : { id: 'sub_1' },
                });
            }
            return makeJsonResponse({});
        }) as unknown as typeof import('../../opscenter/api/auth.svelte').authFetch;

        studioStore.setFetcherForTest(fetcher);
        studioStore.selectedThemes = ['carnivore', 'matrix'];

        const hostEl = document.createElement('div');
        document.body.append(hostEl);
        const app = mount(StudioScreen, { target: hostEl, props: { embedded: true, t: (k: string) => k } });
        cleanups.push(() => unmount(app));

        await new Promise((r) => setTimeout(r, 20));
        await tick();
        flushSync();

        const templateSelect = hostEl.querySelector('select[data-studio-template]') as HTMLSelectElement;
        expect(templateSelect).toBeTruthy();
        expect(Array.from(templateSelect.options).map((o) => o.value)).toEqual([
            'no-code',
            'python',
            'typescript',
            'bash',
            'widget',
            'channel',
            'agent-harness',
        ]);

        const agentRadios = hostEl.querySelectorAll('[role="radio"]');
        const radioText = Array.from(agentRadios).map((el) => el.textContent?.trim());
        expect(radioText).toEqual(expect.arrayContaining(['plugin_studio.agent.claude', 'plugin_studio.agent.codex', 'plugin_studio.agent.agy']));

        expect(hostEl.querySelector('[data-studio-terminal-fallback]')).toBeTruthy();
        expect(hostEl.querySelector('[data-studio-files]')?.textContent).toContain('carnivore.toml');

        const stages = hostEl.querySelectorAll('[data-studio-preview-stage]');
        expect(stages.length).toBeGreaterThanOrEqual(2);

        const inspectorTab = hostEl.querySelector('#plugin-studio-tab-inspector') as HTMLButtonElement;
        inspectorTab.click();
        await tick();
        flushSync();
        expect(hostEl.querySelector('[data-studio-inspector]')?.textContent).toContain('demo.ping');
        expect(hostEl.querySelector('[data-studio-slot-renders]')?.textContent).toContain('session.row_actions');
        expect(hostEl.querySelector('[data-studio-slot-renders]')?.textContent).toContain('RunCheck');

        const readinessTab = hostEl.querySelector('#plugin-studio-tab-readiness') as HTMLButtonElement;
        readinessTab.click();
        await tick();
        flushSync();
        expect(hostEl.querySelector('[data-readiness-item="readme_present"]')?.getAttribute('data-readiness-status')).toBe('fail');

        (hostEl.querySelector('[data-studio-sandbox]') as HTMLButtonElement).click();
        await new Promise((r) => setTimeout(r, 10));
        await tick();
        flushSync();
        expect(hostEl.querySelector('[data-studio-sandbox-output]')?.textContent).toContain('2 passed');

        (hostEl.querySelector('[data-studio-publish-toggle]') as HTMLButtonElement).click();
        await tick();
        flushSync();
        expect(hostEl.querySelector('[data-studio-publish-confirm]')).toBeNull();
        (hostEl.querySelector('[data-studio-publish-dryrun]') as HTMLButtonElement).click();
        await new Promise((r) => setTimeout(r, 10));
        await tick();
        flushSync();

        const confirmBtn = hostEl.querySelector('[data-studio-publish-confirm]') as HTMLButtonElement;
        expect(confirmBtn).toBeTruthy();
        confirmBtn.click();
        await new Promise((r) => setTimeout(r, 10));
        await tick();
        flushSync();

        expect(publishPayloads).toHaveLength(2);
        expect(publishPayloads[0]?.dry_run).toBe(true);
        expect(publishPayloads[1]?.dry_run).toBe(false);
        expect(publishPayloads[1]?.digest).toBe('sha256:cafe1234');
    });

    test('StudioScreen surfaces actionable developer_mode_off & agy_profile_not_configured banners and closes modal before opening settings/wrappers', async () => {
        const openSettingsSpy = vi.spyOn(host, 'openSettings').mockReturnValue(true);
        const openWrappersSpy = vi.spyOn(host, 'openWrappers').mockReturnValue(true);
        const onCloseSpy = vi.fn();

        let nextCode: 'developer_mode_off' | 'agy_profile_not_configured' = 'developer_mode_off';
        const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
            const url = String(input);
            const method = init?.method ?? 'GET';
            if (url === '/cplug-owner/studio/workspaces' && method === 'GET') {
                return makeJsonResponse({ workspaces: [] });
            }
            if (url === '/cplug-owner/studio/workspaces' && method === 'POST') {
                throw new ApiError('conflict', 409, nextCode, {
                    detail: { code: nextCode, detail: `${nextCode} detail` },
                });
            }
            return makeJsonResponse({});
        }) as unknown as typeof import('../../opscenter/api/auth.svelte').authFetch;

        studioStore.setFetcherForTest(fetcher);
        const hostEl = document.createElement('div');
        document.body.append(hostEl);
        const app = mount(StudioScreen, { target: hostEl, props: { embedded: true, onClose: onCloseSpy, t: (k: string) => k } });
        cleanups.push(() => unmount(app));

        await new Promise((r) => setTimeout(r, 10));
        await tick();
        flushSync();

        const submitPrompt = async (text: string) => {
            const textarea = hostEl.querySelector('textarea') as HTMLTextAreaElement;
            textarea.value = text;
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
            await tick();
            flushSync();
            const form = hostEl.querySelector('[data-studio-create-form]') as HTMLFormElement;
            form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
            await new Promise((r) => setTimeout(r, 10));
            await tick();
            flushSync();
        };

        await submitPrompt('build plugin');
        expect(hostEl.querySelector('[data-studio-error="developer_mode_off"]')).toBeTruthy();
        (hostEl.querySelector('[data-studio-error-action]') as HTMLButtonElement).click();
        expect(onCloseSpy).toHaveBeenCalledTimes(1);
        expect(openSettingsSpy).toHaveBeenCalledTimes(1);

        nextCode = 'agy_profile_not_configured';
        await submitPrompt('build agy plugin');
        expect(hostEl.querySelector('[data-studio-error="agy_profile_not_configured"]')).toBeTruthy();
        (hostEl.querySelector('[data-studio-error-action]') as HTMLButtonElement).click();
        expect(onCloseSpy).toHaveBeenCalledTimes(2);
        expect(openWrappersSpy).toHaveBeenCalledTimes(1);
    });

    test('StudioTerminalPane formats object dev_status.last_error and manages inputFocus capture/focusout lifecycle', async () => {
        const claimSpy = vi.spyOn(inputFocus, 'claim');
        const releaseSpy = vi.spyOn(inputFocus, 'release');
        const disposeMock = vi.fn();

        vi.stubGlobal('CloudeTerminal', {
            createTerminalClient: vi.fn(() => ({
                dispose: disposeMock,
                init: vi.fn(async () => {}),
                reconnectToExistingSession: vi.fn(async () => {}),
                attach: vi.fn(),
                setTheme: vi.fn(),
            })),
        });
        vi.stubGlobal('TerminalScroll', { create: vi.fn(() => ({})) });
        vi.stubGlobal('TerminalLayout', { create: vi.fn(() => ({})) });
        vi.stubGlobal('TerminalInputBuffer', { create: vi.fn(() => ({})) });
        vi.stubGlobal('AltScreenScroll', { create: vi.fn(() => ({})) });
        vi.stubGlobal('TerminalStartupNotice', { create: vi.fn(() => ({})) });

        const hostEl = document.createElement('div');
        const outsideBtn = document.createElement('button');
        document.body.append(hostEl, outsideBtn);

        const detail = sampleDetail();
        detail.dev_status.last_error = {
            code: 'permission_widened',
            detail: 're-consent required',
            widened: ['network', 'secrets'],
        };

        const app = mount(StudioTerminalPane, {
            target: hostEl,
            props: {
                workspace: detail.workspace,
                files: detail.files,
                sessionStatus: detail.session_status,
                devStatus: detail.dev_status,
                onStartDev: vi.fn(async () => {}),
                onStopDev: vi.fn(async () => {}),
                onRelaunchAgent: vi.fn(async () => {}),
                t: (k: string) => k,
            },
        });
        cleanups.push(() => {
            unmount(app);
            vi.unstubAllGlobals();
        });

        await tick();
        flushSync();

        const errBanner = hostEl.querySelector('[data-studio-dev-error]');
        expect(errBanner?.textContent).not.toContain('[object Object]');
        expect(errBanner?.textContent).toContain('permission_widened');
        expect(errBanner?.textContent).toContain('re-consent required');
        expect(errBanner?.textContent).toContain('network, secrets');

        const termHost = hostEl.querySelector('[data-studio-slot="studio:ws_demo:ses_demo"]') as HTMLElement;
        expect(termHost).toBeTruthy();
        const inner = document.createElement('textarea');
        termHost.append(inner);

        inner.dispatchEvent(new FocusEvent('focus', { bubbles: false }));
        expect(claimSpy).toHaveBeenCalledWith('studio:ws_demo:ses_demo');

        termHost.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: inner }));
        expect(releaseSpy).not.toHaveBeenCalled();

        termHost.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: outsideBtn }));
        expect(releaseSpy).toHaveBeenCalledWith('studio:ws_demo:ses_demo');
    });

    test('StudioActionsBar disables Confirm and shows refusals when preview.can_send is false', async () => {
        const onPublishSpy = vi.fn(async () => {});
        const hostEl = document.createElement('div');
        document.body.append(hostEl);

        const app = mount(StudioActionsBar, {
            target: hostEl,
            props: {
                busyAction: null,
                sandboxResult: null,
                installResult: null,
                publishPreview: {
                    ok: true,
                    dry_run: true,
                    preview: {
                        can_send: false,
                        digest: 'sha256:blocked',
                        refusals: [{ code: 'missing_readme', path: 'README.md', detail: 'README is required' }],
                    },
                    submission: null,
                },
                publishResult: null,
                onTestSandbox: vi.fn(async () => {}),
                onInstall: vi.fn(async () => {}),
                onPublish: onPublishSpy,
                onResetPublish: vi.fn(),
                t: (k: string) => k,
            },
        });
        cleanups.push(() => unmount(app));

        await tick();
        flushSync();

        (hostEl.querySelector('[data-studio-publish-toggle]') as HTMLButtonElement).click();
        await tick();
        flushSync();

        const confirmBtn = hostEl.querySelector('[data-studio-publish-confirm]') as HTMLButtonElement;
        expect(confirmBtn).toBeTruthy();
        expect(confirmBtn.disabled).toBe(true);
        confirmBtn.click();
        expect(onPublishSpy).not.toHaveBeenCalled();

        expect(hostEl.querySelector('[data-studio-publish-blocked]')).toBeTruthy();
        expect(hostEl.querySelector('[data-studio-publish-refusals]')?.textContent).toContain('missing_readme');
        expect(hostEl.querySelector('[data-studio-publish-refusals]')?.textContent).toContain('README is required');
    });

    test('MultiThemePreview applies viewportWidth and viewportHeight CSS custom properties on preview stages', async () => {
        const themes = [{ id: 'carnivore', name: 'Carnivore' }];
        const previewByTheme: Record<string, PreviewRenderResponse> = {
            carnivore: {
                kind: 'declarative',
                surface: 'panel',
                view_url: null,
                doc: { schema: 2, root: { type: 'text', value: 'sized' } },
                theme_id: 'carnivore',
                width: 720,
                height: 480,
                errors: [],
            },
        };

        const hostEl = document.createElement('div');
        document.body.append(hostEl);
        const app = mount(MultiThemePreview, {
            target: hostEl,
            props: {
                workspace: sampleWorkspace(),
                capabilities: sampleDetail().inspector.capabilities,
                previewByTheme,
                fallbackPreview: null,
                selectedThemes: ['carnivore'],
                themeChoices: themes,
                surfaceId: null,
                viewportWidth: 720,
                viewportHeight: 480,
                onToggleTheme: vi.fn(),
                onSelectSurface: vi.fn(),
                onSelectViewport: vi.fn(),
                onRefresh: vi.fn(async () => {}),
                t: (k: string) => k,
            },
        });
        cleanups.push(() => unmount(app));

        await tick();
        flushSync();

        const canvas = hostEl.querySelector('.ps-stage__canvas') as HTMLElement;
        expect(canvas.style.getPropertyValue('--ps-stage-w')).toBe('720px');
        expect(canvas.style.getPropertyValue('--ps-stage-h')).toBe('480px');
    });

    test('closePluginStudio cancels in-flight openPluginStudio before modal mounts', async () => {
        const openModalSpy = vi.spyOn(modal, 'openModal').mockResolvedValue(null);
        const pending = openPluginStudio();
        expect(isPluginStudioOpen()).toBe(true);
        expect(closePluginStudio()).toBe(true);
        const opened = await pending;
        expect(opened).toBe(false);
        expect(isPluginStudioOpen()).toBe(false);
        expect(openModalSpy).not.toHaveBeenCalled();
    });

    test('MultiThemePreview renders both declarative <Renderer> and iframe <ViewFrame> across 2+ themes simultaneously', async () => {
        const themes = [
            { id: 'carnivore', name: 'Carnivore' },
            { id: 'matrix', name: 'Matrix' },
        ];
        const previewByTheme: Record<string, PreviewRenderResponse> = {
            carnivore: {
                kind: 'declarative',
                surface: 'panel',
                view_url: null,
                doc: { schema: 2, root: { type: 'text', value: 'hello carnivore' } },
                theme_id: 'carnivore',
                width: 480,
                height: 320,
                errors: [],
            },
            matrix: {
                kind: 'view',
                surface: 'panel',
                view_url: 'https://preview.example.com/matrix-view',
                doc: null,
                theme_id: 'matrix',
                width: 480,
                height: 320,
                errors: [],
            },
        };

        const hostEl = document.createElement('div');
        document.body.append(hostEl);
        const app = mount(MultiThemePreview, {
            target: hostEl,
            props: {
                workspace: sampleWorkspace(),
                capabilities: sampleDetail().inspector.capabilities,
                previewByTheme,
                fallbackPreview: null,
                selectedThemes: ['carnivore', 'matrix'],
                themeChoices: themes,
                surfaceId: null,
                viewportWidth: 480,
                onToggleTheme: vi.fn(),
                onSelectSurface: vi.fn(),
                onSelectViewport: vi.fn(),
                onRefresh: vi.fn(async () => {}),
                t: (k: string) => k,
            },
        });
        cleanups.push(() => unmount(app));

        await tick();
        flushSync();

        const carnivoreStage = hostEl.querySelector('[data-studio-preview-stage="carnivore"]');
        const matrixStage = hostEl.querySelector('[data-studio-preview-stage="matrix"]');
        expect(carnivoreStage?.querySelector('[data-session-theme="carnivore"]')).toBeTruthy();
        expect(carnivoreStage?.querySelector('[data-cu-root]')).toBeTruthy();
        expect(matrixStage?.querySelector('iframe')?.getAttribute('src')).toBe('https://preview.example.com/matrix-view');
    });

    test('Command palette and devwidgetlab expose Studio entry actions cleanly', async () => {
        const openSpy = vi.spyOn(host, 'openPluginStudio').mockReturnValue(true);
        const actions = appActions([]);
        const buildAction = actions.find((a) => a.id === 'action:build-plugin');
        expect(buildAction).toBeTruthy();
        buildAction?.run({ popout: false });
        expect(openSpy).toHaveBeenCalledTimes(1);

        const menuHost = document.createElement('div');
        document.body.append(menuHost);
        const m1 = mount(LabMenu, { target: menuHost });
        cleanups.push(() => unmount(m1));
        await tick();
        expect(menuHost.querySelector('[data-dwl-studio]')).toBeTruthy();

        const viewerHost = document.createElement('div');
        document.body.append(viewerHost);
        const m2 = mount(LabViewer, { target: viewerHost });
        cleanups.push(() => unmount(m2));
        await tick();
        expect(viewerHost.querySelector('[data-dwl-studio]')).toBeTruthy();
    });
});
